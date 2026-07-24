"""Run all six V3 ground builds together and sample them every three game minutes."""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
for extra in (PROJECT_ROOT, PROJECT_ROOT / "v3"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from s2clientprotocol import data_pb2 as data_pb  # noqa: E402
from s2clientprotocol import sc2api_pb2 as sc_pb  # noqa: E402

from sc2team.custom_config import CustomLauncherConfig, SlotConfig  # noqa: E402
from sc2team.custom_runtime import build_runtime_map, player_setups  # noqa: E402
from sc2team.process import discover_sc2_executable, launch_sc2, stop_process  # noqa: E402
from sc2team.protocol import Sc2Connection  # noqa: E402
from sc2team_v3.config import V3BuildConfig  # noqa: E402
from sc2team_v3.runtime import build_v3_map, install_v3_mod  # noqa: E402


BASE_MAP = PROJECT_ROOT / "maps" / "generated" / "europe-melee-2-7v7-rich-50000-fixed-teams.SC2Map"
OUTPUT_MAP = PROJECT_ROOT / "runtime" / "maps" / "v3-ground-builds-probe.SC2Map"
ARCHIVE_BASELINE_MOD = PROJECT_ROOT / "runtime" / "v3-opening-static-check" / "SC2TeamV3AI.SC2Mod"
PORT = 14183
WORKERS = frozenset({"SCV", "Probe", "Drone"})
TOWN_HALLS = frozenset({"CommandCenter", "OrbitalCommand", "PlanetaryFortress", "Nexus", "Hatchery", "Lair", "Hive"})
SUPPORT = frozenset({"Overlord", "Overseer", "Queen", "Observer"})
AIR_COMBAT = frozenset({"VikingFighter", "Banshee", "Battlecruiser", "Phoenix", "VoidRay", "Carrier", "Tempest", "Mutalisk", "Corruptor", "BroodLord", "Viper"})
PRODUCTION_BUILDINGS = frozenset({"Barracks", "Factory", "Gateway", "WarpGate", "RoboticsFacility", "Hatchery", "Lair", "Hive"})
GAS_BUILDINGS = frozenset({"Refinery", "RefineryRich", "Assimilator", "AssimilatorRich", "Extractor", "ExtractorRich"})
POWER_BUILDINGS = frozenset({"Pylon"})


@dataclass(frozen=True)
class BuildCase:
    logical_slot: int
    race: str
    key: str
    label: str
    roster: tuple[str, ...]


CASES = (
    BuildCase(1, "Terran", "terran_bionic", "테란 바이오닉", ("Marine", "Marauder", "SC2TeamMedic", "SiegeTank")),
    BuildCase(2, "Terran", "terran_mechanic", "테란 메카닉", ("SC2TeamGoliath", "Cyclone", "SiegeTank", "Thor")),
    BuildCase(3, "Protoss", "protoss_gateway", "프로토스 관문", ("Zealot", "Archon", "HighTemplar", "Sentry")),
    BuildCase(8, "Protoss", "protoss_gateway_robo", "프로토스 관문+로보", ("Zealot", "Stalker", "Sentry", "Immortal", "Colossus")),
    BuildCase(9, "Zerg", "zerg_roach_hydra_ultra", "저그 바퀴·히드라", ("Roach", "Hydralisk", "Ultralisk")),
    BuildCase(10, "Zerg", "zerg_ling_bane_ultra", "저그 저글링·맹독충", ("Zergling", "Baneling", "Ultralisk")),
)


def make_config(cases: tuple[BuildCase, ...], *, melee_build: str = "Macro") -> CustomLauncherConfig:
    by_slot = {case.logical_slot: case for case in cases}
    slots = []
    for slot_id in range(1, 15):
        case = by_slot.get(slot_id)
        # The map contract requires both teams.  In a single-build probe P8
        # is only a normal melee opponent; it never receives build ID 142 and
        # therefore cannot contend as another V3 expansion policy.
        controller = "human" if slot_id == 1 else "custom_ai" if case or (len(cases) == 1 and slot_id == 8) else "empty"
        race = case.race if case else "Random"
        fallback = {"Terran": "bio_tank", "Protoss": "stalker_immortal", "Zerg": "roach_hydra", "Random": "random_ground"}[race]
        slots.append(SlotConfig(slot=slot_id, controller=controller, team=1 if slot_id <= 7 else 2, race=race, build=fallback, melee_build=melee_build if case else ""))
    config = CustomLauncherConfig(version=1, slots=tuple(slots), allow_support_air=False, protoss_faction="Standard", wild_zerg=False, unit_control=False, fullscreen=False)
    config.validate()
    return config


async def unit_data(connection: Sc2Connection) -> tuple[dict[int, str], dict[int, Any], set[int]]:
    request = sc_pb.Request()
    request.data.CopyFrom(sc_pb.RequestData(unit_type_id=True))
    response = (await connection.request(request)).data
    names = {unit.unit_id: unit.name for unit in response.units}
    data = {unit.unit_id: unit for unit in response.units}
    structures = {unit.unit_id for unit in response.units if data_pb.Structure in unit.attributes}
    return names, data, structures


async def ability_metadata(connection: Sc2Connection) -> dict[int, dict[str, str | int]]:
    """Return order ability labels/indexes for research-order attribution."""

    request = sc_pb.Request()
    request.data.CopyFrom(sc_pb.RequestData(ability_id=True))
    try:
        abilities = (await connection.request(request)).data.abilities
        return {
            int(ability.ability_id): {
                "link_name": str(ability.link_name or ""),
                "link_index": int(ability.link_index or 0),
                "friendly_name": str(ability.friendly_name or ""),
                "button_name": str(ability.button_name or ""),
            }
            for ability in abilities
        }
    except Exception:
        return {}


def scan_research_orders(
    observation: Any,
    player_count: int,
    ability_meta: dict[int, dict[str, str | int]],
    research_seen: dict[int, dict[int, dict[str, str | int]]],
) -> None:
    """Record all visible AI research orders with one raw-unit pass."""

    for unit in observation.observation.raw_data.units:
        owner = int(unit.owner)
        if not 1 <= owner <= player_count or not unit.orders:
            continue
        for order in unit.orders:
            ability_id = int(order.ability_id)
            metadata = ability_meta.get(ability_id)
            if metadata is not None:
                link_name = str(metadata["link_name"])
                friendly_name = str(metadata["friendly_name"])
                research_label = f"{link_name} {friendly_name}".lower()
                if research_label and "research" not in research_label:
                    continue
                name = friendly_name or link_name or str(ability_id)
                link_index = int(metadata["link_index"])
            else:
                # An unavailable/unknown ability record is ambiguous: retain it
                # rather than losing a custom research order.
                name = str(ability_id)
                link_name = ""
                link_index = 0
            entry = research_seen[owner].setdefault(
                ability_id,
                {
                    "name": name,
                    "link_name": link_name,
                    "link_index": link_index,
                    "count_frames": 0,
                },
            )
            entry["count_frames"] = int(entry["count_frames"]) + 1


def snapshot(observation: Any, owner: int, names: dict[int, str], data: dict[int, Any], structures: set[int], baseline_bases: int) -> dict[str, Any]:
    units = [unit for unit in observation.observation.raw_data.units if unit.owner == owner]
    counts = Counter(names.get(unit.unit_type, str(unit.unit_type)) for unit in units)
    workers = sum(counts[name] for name in WORKERS)
    larva = counts["Larva"]
    buildings = sum(1 for unit in units if unit.unit_type in structures)
    gas_tags = {
        unit.tag
        for unit in units
        if names.get(unit.unit_type) in GAS_BUILDINGS and unit.build_progress >= 1
    }
    gas_positions = [
        (float(unit.pos.x), float(unit.pos.y))
        for unit in units
        if names.get(unit.unit_type) in GAS_BUILDINGS and unit.build_progress >= 1
    ]
    gas_workers = sum(
        1
        for unit in units
        if names.get(unit.unit_type) in WORKERS
        and len(unit.orders) > 0
        and unit.orders[0].target_unit_tag in gas_tags
    )
    gas_workers_nearby = sum(
        1
        for unit in units
        if names.get(unit.unit_type) in WORKERS
        and any((float(unit.pos.x) - x) ** 2 + (float(unit.pos.y) - y) ** 2 <= 25.0 for x, y in gas_positions)
    )
    gas_buildings = len(gas_tags)
    army_units = [unit for unit in units if unit.unit_type not in structures and names.get(unit.unit_type) not in WORKERS | SUPPORT]
    army_supply = sum(abs(float(data[unit.unit_type].food_required)) for unit in army_units if unit.unit_type in data)
    combat_upgrade_levels = {
        "attack": max((int(unit.attack_upgrade_level) for unit in army_units), default=0),
        "armor": max((int(unit.armor_upgrade_level) for unit in army_units), default=0),
        "shield": max((int(unit.shield_upgrade_level) for unit in army_units), default=0),
    }
    supply_cap = sum(max(0.0, float(data[unit.unit_type].food_provided)) for unit in units if unit.unit_type in data)
    mineral_points = [
        (float(unit.pos.x), float(unit.pos.y))
        for unit in observation.observation.raw_data.units
        if unit.mineral_contents > 0
    ]
    towns = []
    for unit in units:
        if names.get(unit.unit_type) not in TOWN_HALLS or unit.build_progress < 1:
            continue
        x, y = float(unit.pos.x), float(unit.pos.y)
        mineral_patches = sum(
            1 for mineral_x, mineral_y in mineral_points
            if (x - mineral_x) ** 2 + (y - mineral_y) ** 2 <= 196.0
        )
        towns.append((names.get(unit.unit_type, str(unit.unit_type)), x, y, mineral_patches))
    # A Zerg macro Hatchery is not a mining base.  Resource centers on this
    # map have a cluster of mineral fields within 14 game units; the report
    # records the patch count so this classification stays auditable.
    mining_towns = [town for town in towns if town[3] >= 5]
    bases = len(mining_towns)
    town_halls = len(towns)
    macro_hatcheries = max(0, town_halls - bases) if any(town[0] in {"Hatchery", "Lair", "Hive"} for town in towns) else 0
    production_sites = []
    power_sites = []
    for unit in units:
        name = names.get(unit.unit_type, str(unit.unit_type))
        if name not in PRODUCTION_BUILDINGS | POWER_BUILDINGS or name in TOWN_HALLS:
            continue
        nearest = min(mining_towns, key=lambda town: (float(unit.pos.x) - town[1]) ** 2 + (float(unit.pos.y) - town[2]) ** 2, default=None)
        site = {
            "type": name,
            "x": round(float(unit.pos.x), 1),
            "y": round(float(unit.pos.y), 1),
            "progress": round(float(unit.build_progress), 2),
            "nearest_town": nearest[0] if nearest else None,
            "nearest_x": round(nearest[1], 1) if nearest else None,
            "nearest_y": round(nearest[2], 1) if nearest else None,
            "distance": round((((float(unit.pos.x) - nearest[1]) ** 2 + (float(unit.pos.y) - nearest[2]) ** 2) ** 0.5), 1) if nearest else None,
        }
        if name in POWER_BUILDINGS:
            power_sites.append(site)
        else:
            production_sites.append(site)
    # Engine-authoritative saturation: the harvester counts the sim maintains on
    # each resource structure. Unlike the order-target gas_workers count, this does
    # not miss workers on the return leg of a gas round-trip. ideal is 3 per gas.
    gas_assigned = sum(
        int(unit.assigned_harvesters)
        for unit in units
        if names.get(unit.unit_type) in GAS_BUILDINGS and unit.build_progress >= 1
    )
    gas_ideal = sum(
        int(unit.ideal_harvesters)
        for unit in units
        if names.get(unit.unit_type) in GAS_BUILDINGS and unit.build_progress >= 1
    )
    mineral_assigned = sum(
        int(unit.assigned_harvesters)
        for unit in units
        if names.get(unit.unit_type) in TOWN_HALLS and unit.build_progress >= 1
    )
    mineral_ideal = sum(
        int(unit.ideal_harvesters)
        for unit in units
        if names.get(unit.unit_type) in TOWN_HALLS and unit.build_progress >= 1
    )
    # Combat / sally-out signals.  engaged_target_tag is the tag of the unit this
    # unit's weapon is currently locked onto -- a direct "attacking right now"
    # indicator (0 when idle).  away/fwd_dist measure how far the army has left
    # its own town halls: sallying out to attack vs sitting at home.
    home_points = [(town_x, town_y) for _, town_x, town_y, _ in towns]
    army_positions = [(float(unit.pos.x), float(unit.pos.y)) for unit in army_units]
    engaged = sum(1 for unit in army_units if int(getattr(unit, "engaged_target_tag", 0)) != 0)
    away = 0
    fwd_dist = 0.0
    if army_positions and home_points:
        def _min_home_dist(px: float, py: float) -> float:
            return min(((px - hx) ** 2 + (py - hy) ** 2) ** 0.5 for hx, hy in home_points)
        away = sum(1 for px, py in army_positions if _min_home_dist(px, py) > 30.0)
        centroid_x = sum(px for px, _ in army_positions) / len(army_positions)
        centroid_y = sum(py for _, py in army_positions) / len(army_positions)
        fwd_dist = round(_min_home_dist(centroid_x, centroid_y), 1)
    return {
        "army_supply": round(army_supply, 1),
        "engaged": engaged,
        "away": away,
        "fwd_dist": fwd_dist,
        "supply_cap": round(supply_cap, 1),
        "workers": workers,
        "larva": larva,
        "gas_workers": gas_workers,
        "gas_workers_nearby": gas_workers_nearby,
        "gas_buildings": gas_buildings,
        "gas_assigned": gas_assigned,
        "gas_ideal": gas_ideal,
        "mineral_assigned": mineral_assigned,
        "mineral_ideal": mineral_ideal,
        "combat_upgrade_levels": combat_upgrade_levels,
        "army": len(army_units),
        "buildings": buildings,
        "bases": bases,
        "town_halls": town_halls,
        "macro_hatcheries": macro_hatcheries,
        "expansions": max(0, bases - baseline_bases),
        "counts": counts,
        "towns": [
            {"type": name, "x": round(x, 1), "y": round(y, 1), "mineral_patches": patches}
            for name, x, y, patches in towns
        ],
        "power_sites": power_sites,
        "production_sites": production_sites,
    }


def combat_signals(observation: Any, owner: int, names: dict[int, str], structures: set[int]) -> tuple[int, int, int]:
    """Lean per-tick combat read (no mineral scan) for high-frequency polling.

    Returns (engaged, away, army_count): units currently attacking a target,
    units more than 30 from every own town hall (sallied out), and total army.
    """
    army: list[tuple[float, float, int]] = []
    homes: list[tuple[float, float]] = []
    for unit in observation.observation.raw_data.units:
        if unit.owner != owner:
            continue
        name = names.get(unit.unit_type)
        if unit.unit_type in structures:
            if name in TOWN_HALLS and unit.build_progress >= 1:
                homes.append((float(unit.pos.x), float(unit.pos.y)))
            continue
        if name in WORKERS | SUPPORT:
            continue
        army.append((float(unit.pos.x), float(unit.pos.y), int(getattr(unit, "engaged_target_tag", 0))))
    engaged = sum(1 for _, _, tag in army if tag != 0)
    away = 0
    if army and homes:
        for px, py, _ in army:
            if min(((px - hx) ** 2 + (py - hy) ** 2) ** 0.5 for hx, hy in homes) > 30.0:
                away += 1
    return engaged, away, len(army)


async def run(
    duration: int,
    cases: tuple[BuildCase, ...],
    archive_baseline_mod: bool = False,
    report_path: Path | None = None,
    *,
    upstream_timing: bool = False,
) -> int:
    # Blizzard exposes only coarse AIBuild values through the API.  Timing is
    # the upstream pool containing the Ling/Bane opening; the resulting report
    # records the actual roster so callers must retain only BanelingNest runs.
    config = make_config(cases, melee_build="Timing" if upstream_timing else "Macro")
    if upstream_timing:
        build_runtime_map(
            PROJECT_ROOT,
            BASE_MAP,
            OUTPUT_MAP,
            config,
            melee_only=True,
            campaign_units_pilot=True,
            observer_mode=True,
            active_config_file=OUTPUT_MAP.with_suffix(".json"),
        )
        print("AI_SOURCE=UPSTREAM_TIMING")
    else:
        v3_config = V3BuildConfig(campaign_units=True, player_builds=tuple((case.logical_slot, case.key) for case in cases))
        build_v3_map(PROJECT_ROOT, BASE_MAP, OUTPUT_MAP, config, v3_config, observer_mode=True, active_config_file=OUTPUT_MAP.with_suffix(".json"))
        print("AI_SOURCE=V3_CUSTOM")
    if archive_baseline_mod and not upstream_timing:
        if not ARCHIVE_BASELINE_MOD.is_file():
            raise FileNotFoundError(f"03:47 기준 mod를 찾을 수 없습니다: {ARCHIVE_BASELINE_MOD}")
        shutil.copy2(ARCHIVE_BASELINE_MOD, PROJECT_ROOT / "runtime" / "mods" / "SC2TeamV3AI.SC2Mod")
        print("V3_MOD_SOURCE=ARCHIVE_0347")
    elif not upstream_timing:
        print("V3_MOD_SOURCE=FORMAL_REBUILD")
    executable = discover_sc2_executable()
    if not upstream_timing:
        install_v3_mod(PROJECT_ROOT, executable.parents[2])
    process = launch_sc2(executable, PORT, 0, width=1280, height=720, fullscreen=False)
    connection: Sc2Connection | None = None
    failures: list[str] = []
    final: dict[int, dict[str, Any]] = {}
    peak_roster: dict[int, Counter[str]] = {owner: Counter() for owner in range(1, len(cases) + 1)}
    peak_expansions: dict[int, int] = {owner: 0 for owner in range(1, len(cases) + 1)}
    samples: list[dict[str, Any]] = []
    research_seen: dict[int, dict[int, dict[str, str | int]]] = {
        owner: {} for owner in range(1, len(cases) + 1)
    }
    try:
        connection = await Sc2Connection.open(PORT)
        await connection.create_game_with_setups(OUTPUT_MAP.name, OUTPUT_MAP.read_bytes(), player_setups(config, observer=True), realtime=False)
        await connection.join_as_observer()
        names, data, structures = await unit_data(connection)
        ability_meta = await ability_metadata(connection)
        ability_dump = sorted(
            (
                str(meta["link_name"]),
                int(meta["link_index"]),
                ability_id,
                str(meta["friendly_name"]),
                str(meta["button_name"]),
            )
            for ability_id, meta in ability_meta.items()
            if "research" in str(meta["link_name"]).lower()
            or "raptor" in str(meta["friendly_name"]).lower()
            or "raptor" in str(meta["button_name"]).lower()
            or "adrenal" in str(meta["friendly_name"]).lower()
            or "adrenal" in str(meta["button_name"]).lower()
        )
        for link_name, link_index, ability_id, friendly_name, button_name in ability_dump:
            print(
                f"ABILITY_DUMP link={link_name}#{link_index} id={ability_id} "
                f"friendly='{friendly_name}' button='{button_name}'"
            )
        await connection.step(5 * 16)
        first = await connection.observation(disable_fog=True)
        owner_counts = Counter(int(unit.owner) for unit in first.observation.raw_data.units)
        print(f"RAW_OWNERS at=5s counts={dict(sorted(owner_counts.items()))}")
        baseline_bases = {
            owner: snapshot(first, owner, names, data, structures, 0)["bases"]
            for owner in range(1, len(cases) + 1)
        }
        print(f"GROUND_COMPILE=PASS source={'UPSTREAM_TIMING' if upstream_timing else 'V3_CUSTOM'} players={len(cases)} unit_types={len(data)}")
        # High-frequency (30s) combat accumulators, independent of the 180s
        # structural snapshots.  combat_ticks/sally_ticks measure how OFTEN a
        # slot is fighting / sallied out across the whole run, not just at the
        # six coarse samples.
        combat_ticks = {owner: 0 for owner in range(1, len(cases) + 1)}
        sally_ticks = {owner: 0 for owner in range(1, len(cases) + 1)}
        peak_engaged = {owner: 0 for owner in range(1, len(cases) + 1)}
        sum_engaged = {owner: 0 for owner in range(1, len(cases) + 1)}
        poll_count = 0
        elapsed = 5
        for game_seconds in range(30, duration + 1, 30):
            await connection.step((game_seconds - elapsed) * 16)
            elapsed = game_seconds
            observation = await connection.observation(disable_fog=True)
            scan_research_orders(observation, len(cases), ability_meta, research_seen)
            poll_count += 1
            for combat_owner in range(1, len(cases) + 1):
                tick_engaged, tick_away, _ = combat_signals(observation, combat_owner, names, structures)
                if tick_engaged > 0:
                    combat_ticks[combat_owner] += 1
                if tick_away >= 4:
                    sally_ticks[combat_owner] += 1
                peak_engaged[combat_owner] = max(peak_engaged[combat_owner], tick_engaged)
                sum_engaged[combat_owner] += tick_engaged
            if game_seconds % 180:
                continue
            print(f"SAMPLE minute={game_seconds // 60}")
            sample = {"second": game_seconds, "players": {}}
            for owner, case in enumerate(cases, start=1):
                state = snapshot(observation, owner, names, data, structures, baseline_bases[owner])
                final[owner] = state
                sample["players"][str(owner)] = {
                    **{key: value for key, value in state.items() if key != "counts"},
                    "counts": dict(state["counts"]),
                }
                for unit_name in case.roster:
                    peak_roster[owner][unit_name] = max(peak_roster[owner][unit_name], state["counts"][unit_name])
                peak_expansions[owner] = max(peak_expansions[owner], state["expansions"])
                roster = {name: state["counts"][name] for name in case.roster}
                production = {name: state["counts"][name] for name in PRODUCTION_BUILDINGS if state["counts"][name] > 0}
                print(
                    f"  P{owner} {case.label}: pop={state['army_supply']:g}/{state['supply_cap']:g} "
                    f"workers={state['workers']} larva={state['larva']} army={state['army']} "
                    f"buildings={state['buildings']} gas={state['gas_buildings']} "
                    f"gas_sat={state['gas_assigned']}/{state['gas_ideal']} "
                    f"min_sat={state['mineral_assigned']}/{state['mineral_ideal']} "
                    f"gas_workers_nearby={state['gas_workers_nearby']} "
                    f"upgrades={state['combat_upgrade_levels']['attack']}/{state['combat_upgrade_levels']['armor']} "
                    f"engaged={state['engaged']} away={state['away']} fwd={state['fwd_dist']:g} "
                    f"bases={state['bases']} macro_hatcheries={state['macro_hatcheries']} "
                    f"expansions={state['expansions']} production={production} roster={roster}"
                )
            entries = list(sample["players"].values())
            count = len(entries)
            if count > 1:
                def mean(getter: Any) -> float:
                    return sum(getter(entry) for entry in entries) / count
                print(
                    f"  AVG(n={count}): "
                    f"army_supply={mean(lambda e: e['army_supply']):.1f} "
                    f"supply_cap={mean(lambda e: e['supply_cap']):.1f} "
                    f"workers={mean(lambda e: e['workers']):.1f} "
                    f"larva={mean(lambda e: e['larva']):.1f} "
                    f"army={mean(lambda e: e['army']):.1f} "
                    f"buildings={mean(lambda e: e['buildings']):.1f} "
                    f"gas={mean(lambda e: e['gas_buildings']):.1f} "
                    f"gas_sat={mean(lambda e: e['gas_assigned']):.1f}/{mean(lambda e: e['gas_ideal']):.1f} "
                    f"min_sat={mean(lambda e: e['mineral_assigned']):.1f}/{mean(lambda e: e['mineral_ideal']):.1f} "
                    f"gas_workers_nearby={mean(lambda e: e['gas_workers_nearby']):.1f} "
                    f"upgrades={mean(lambda e: e['combat_upgrade_levels']['attack']):.2f}/"
                    f"{mean(lambda e: e['combat_upgrade_levels']['armor']):.2f} "
                    f"engaged={mean(lambda e: e['engaged']):.1f} "
                    f"away={mean(lambda e: e['away']):.1f} "
                    f"fwd={mean(lambda e: e['fwd_dist']):.1f} "
                    f"bases={mean(lambda e: e['bases']):.1f} "
                    f"macro_hatcheries={mean(lambda e: e['macro_hatcheries']):.1f} "
                    f"expansions={mean(lambda e: e['expansions']):.1f}"
                )
            samples.append(sample)
        if poll_count > 0:
            print(f"COMBAT_FREQ polls={poll_count} interval=30s")
            for owner, case in enumerate(cases, start=1):
                combat_ratio = combat_ticks[owner] / poll_count
                sally_ratio = sally_ticks[owner] / poll_count
                avg_engaged = sum_engaged[owner] / poll_count
                print(
                    f"  P{owner} {case.label}: combat_tick_ratio={combat_ratio:.0%} "
                    f"sally_ratio={sally_ratio:.0%} peak_engaged={peak_engaged[owner]} "
                    f"avg_engaged={avg_engaged:.1f}"
                )
            n = len(cases)
            print(
                f"  COMBAT_AVG: combat_tick_ratio={sum(combat_ticks.values()) / (poll_count * n):.0%} "
                f"sally_ratio={sum(sally_ticks.values()) / (poll_count * n):.0%} "
                f"peak_engaged={sum(peak_engaged.values()) / n:.1f} "
                f"avg_engaged={sum(sum_engaged.values()) / (poll_count * n):.1f}"
            )
        for owner in range(1, len(cases) + 1):
            records = [
                {"ability_id": ability_id, **entry}
                for ability_id, entry in sorted(research_seen[owner].items())
            ]
            print(f"RESEARCH_SEEN P{owner}={records}")
        adrenal_owners = [
            owner
            for owner, abilities in research_seen.items()
            if any(
                "adrenal" in f"{entry['name']} {entry['link_name']}".lower()
                for entry in abilities.values()
            )
        ]
        raptor_owners = [
            owner
            for owner, abilities in research_seen.items()
            if any(
                "raptor" in f"{entry['name']} {entry['link_name']}".lower()
                or "raptor" in str(ability_meta.get(ability_id, {}).get("button_name", "")).lower()
                or (
                    entry["link_name"] == "SpawningPoolResearch"
                    and int(entry["link_index"]) in (9, 10)
                )
                for ability_id, entry in abilities.items()
            )
        ]
        print(f"ADRENAL_RESEARCH_SEEN={adrenal_owners}")
        print(f"RAPTOR_RESEARCH_SEEN={raptor_owners}")
    finally:
        if connection is not None:
            try:
                await connection.quit()
            except Exception:
                pass
            try:
                await connection.close()
            except Exception:
                pass
        stop_process(process)

    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps({
            "source": "upstream_timing" if upstream_timing else "v3_custom",
            "requested_melee_build": "Timing" if upstream_timing else "Macro",
            "cases": [case.__dict__ for case in cases],
            "samples": samples,
            "research_seen": {
                str(owner): {str(ability_id): entry for ability_id, entry in abilities.items()}
                for owner, abilities in research_seen.items()
            },
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"V3_GROUND_REPORT={report_path}")

    for owner, case in enumerate(cases, start=1):
        state = final.get(owner)
        if state is None:
            failures.append(f"P{owner} has no final snapshot")
            continue
        produced = [name for name in case.roster if peak_roster[owner][name] > 0]
        if len(produced) < 2:
            failures.append(f"P{owner} produced too little of selected roster: {produced}")
        unwanted_air = sorted(name for name in AIR_COMBAT if state["counts"][name] > 0)
        if unwanted_air:
            failures.append(f"P{owner} produced combat air: {unwanted_air}")
    if duration >= 360:
        for owner, case in enumerate(cases, start=1):
            state = final.get(owner)
            if state is not None and state["workers"] <= 14:
                failures.append(f"P{owner} {case.label} workers stalled at {state['workers']}")
            if peak_expansions[owner] < 1:
                failures.append(f"P{owner} {case.label} did not complete the first expansion")
    if duration >= 540:
        for owner, case in enumerate(cases, start=1):
            state = final.get(owner)
            if state is None:
                continue
            if state["gas_buildings"] > 0 and state["gas_workers_nearby"] == 0:
                failures.append(f"P{owner} {case.label} has gas structures but no nearby gas workers")
            if state["army_supply"] < 10:
                failures.append(f"P{owner} {case.label} army supply too low at {duration // 60} minutes: {state['army_supply']:g}")
    if failures:
        print("V3_GROUND_BUILDS=FAIL " + "; ".join(failures))
        return 1
    print("V3_GROUND_BUILDS=PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=int, default=900)
    parser.add_argument(
        "--archive-baseline-mod",
        action="store_true",
        help="install the immutable 03:47 MPQ after map assembly",
    )
    parser.add_argument(
        "--upstream-timing",
        action="store_true",
        help="run Blizzard's unmodified Timing melee AI; retain a Zerg run only if it actually selects BanelingNest",
    )
    parser.add_argument("--build", choices=[case.key for case in CASES], help="run one build alone as runtime P1")
    parser.add_argument(
        "--all-lingbane",
        action="store_true",
        help="fill a 6v6 (12 players) with the Zerg Ling/Bane build to average out run-to-run variance",
    )
    parser.add_argument(
        "--all-roach-hydra",
        action="store_true",
        help="fill a 6v6 (12 players) with the Zerg Roach/Hydra build to average out run-to-run variance",
    )
    parser.add_argument(
        "--all-gateway",
        action="store_true",
        help="fill a 6v6 (12 players) with the Protoss Gateway build to average out run-to-run variance",
    )
    parser.add_argument("--report", type=Path, help="write samples and production coordinates as JSON")
    parser.add_argument("--mirror-count", type=int, default=12, help="even number of mirror slots (2..12); split evenly across the two teams")
    args = parser.parse_args()
    if args.duration < 180 or args.duration % 180:
        parser.error("duration must be a multiple of 180 and at least 180 seconds")
    mirror_keys = [
        key
        for flag, key in (
            (args.all_lingbane, "zerg_ling_bane_ultra"),
            (args.all_roach_hydra, "zerg_roach_hydra_ultra"),
            (args.all_gateway, "protoss_gateway"),
        )
        if flag
    ]
    if len(mirror_keys) > 1:
        parser.error("choose only one mirror flag")
    if mirror_keys and args.build:
        parser.error("a mirror flag and --build are mutually exclusive")
    cases = CASES
    if mirror_keys:
        template = next(case for case in CASES if case.key == mirror_keys[0])
        # Slot 1 is the human/observer slot (a Computer at runtime P1 in observer
        # mode); slots 7 and 14 stay empty so this is a symmetric 6v6 mirror.
        if args.mirror_count < 2 or args.mirror_count > 12 or args.mirror_count % 2:
            parser.error("--mirror-count must be an even number between 2 and 12")
        per_team = args.mirror_count // 2
        team_a = (1, 2, 3, 4, 5, 6)[:per_team]
        team_b = (8, 9, 10, 11, 12, 13)[:per_team]
        mirror_slots = team_a + team_b
        cases = tuple(replace(template, logical_slot=slot) for slot in mirror_slots)
    elif args.build:
        selected = next(case for case in CASES if case.key == args.build)
        cases = (replace(selected, logical_slot=1),)
    return asyncio.run(run(
        args.duration,
        cases,
        args.archive_baseline_mod,
        args.report,
        upstream_timing=args.upstream_timing,
    ))


if __name__ == "__main__":
    raise SystemExit(main())
