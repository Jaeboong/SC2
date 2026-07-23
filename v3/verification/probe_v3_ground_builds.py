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
    from s2clientprotocol import sc2api_pb2 as sc_pb

    request = sc_pb.Request()
    request.data.CopyFrom(sc_pb.RequestData(unit_type_id=True))
    response = (await connection.request(request)).data
    names = {unit.unit_id: unit.name for unit in response.units}
    data = {unit.unit_id: unit for unit in response.units}
    structures = {unit.unit_id for unit in response.units if data_pb.Structure in unit.attributes}
    return names, data, structures


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
    return {
        "army_supply": round(army_supply, 1),
        "supply_cap": round(supply_cap, 1),
        "workers": workers,
        "larva": larva,
        "gas_workers": gas_workers,
        "gas_workers_nearby": gas_workers_nearby,
        "gas_buildings": gas_buildings,
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
    try:
        connection = await Sc2Connection.open(PORT)
        await connection.create_game_with_setups(OUTPUT_MAP.name, OUTPUT_MAP.read_bytes(), player_setups(config, observer=True), realtime=False)
        await connection.join_as_observer()
        names, data, structures = await unit_data(connection)
        await connection.step(5 * 16)
        first = await connection.observation(disable_fog=True)
        owner_counts = Counter(int(unit.owner) for unit in first.observation.raw_data.units)
        print(f"RAW_OWNERS at=5s counts={dict(sorted(owner_counts.items()))}")
        baseline_bases = {
            owner: snapshot(first, owner, names, data, structures, 0)["bases"]
            for owner in range(1, len(cases) + 1)
        }
        print(f"GROUND_COMPILE=PASS source={'UPSTREAM_TIMING' if upstream_timing else 'V3_CUSTOM'} players={len(cases)} unit_types={len(data)}")
        elapsed = 5
        for game_seconds in range(180, duration + 1, 180):
            await connection.step((game_seconds - elapsed) * 16)
            elapsed = game_seconds
            observation = await connection.observation(disable_fog=True)
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
                    f"gas_workers_nearby={state['gas_workers_nearby']} "
                    f"upgrades={state['combat_upgrade_levels']['attack']}/{state['combat_upgrade_levels']['armor']} "
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
                    f"gas_workers_nearby={mean(lambda e: e['gas_workers_nearby']):.1f} "
                    f"upgrades={mean(lambda e: e['combat_upgrade_levels']['attack']):.2f}/"
                    f"{mean(lambda e: e['combat_upgrade_levels']['armor']):.2f} "
                    f"bases={mean(lambda e: e['bases']):.1f} "
                    f"macro_hatcheries={mean(lambda e: e['macro_hatcheries']):.1f} "
                    f"expansions={mean(lambda e: e['expansions']):.1f}"
                )
            samples.append(sample)
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
    parser.add_argument("--report", type=Path, help="write samples and production coordinates as JSON")
    args = parser.parse_args()
    if args.duration < 180 or args.duration % 180:
        parser.error("duration must be a multiple of 180 and at least 180 seconds")
    if args.all_lingbane and args.build:
        parser.error("--all-lingbane and --build are mutually exclusive")
    cases = CASES
    if args.all_lingbane:
        template = next(case for case in CASES if case.key == "zerg_ling_bane_ultra")
        # Slot 1 is the human/observer slot (a Computer at runtime P1 in observer
        # mode); slots 7 and 14 stay empty so this is a symmetric 6v6 mirror.
        mirror_slots = (1, 2, 3, 4, 5, 6, 8, 9, 10, 11, 12, 13)
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
