"""Run all six V3 ground builds together and sample them every three game minutes."""

from __future__ import annotations

import argparse
import asyncio
import shutil
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
for extra in (PROJECT_ROOT, PROJECT_ROOT / "v3"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from s2clientprotocol import data_pb2 as data_pb  # noqa: E402

from sc2team.custom_config import CustomLauncherConfig, SlotConfig  # noqa: E402
from sc2team.custom_runtime import player_setups  # noqa: E402
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


def make_config() -> CustomLauncherConfig:
    by_slot = {case.logical_slot: case for case in CASES}
    slots = []
    for slot_id in range(1, 15):
        case = by_slot.get(slot_id)
        controller = "human" if slot_id == 1 else "custom_ai" if case else "empty"
        race = case.race if case else "Random"
        fallback = {"Terran": "bio_tank", "Protoss": "stalker_immortal", "Zerg": "roach_hydra", "Random": "random_ground"}[race]
        slots.append(SlotConfig(slot=slot_id, controller=controller, team=1 if slot_id <= 7 else 2, race=race, build=fallback, melee_build="Macro" if case else ""))
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
    buildings = sum(1 for unit in units if unit.unit_type in structures)
    bases = sum(counts[name] for name in TOWN_HALLS)
    army_units = [unit for unit in units if unit.unit_type not in structures and names.get(unit.unit_type) not in WORKERS | SUPPORT]
    army_supply = sum(abs(float(data[unit.unit_type].food_required)) for unit in army_units if unit.unit_type in data)
    supply_cap = sum(max(0.0, float(data[unit.unit_type].food_provided)) for unit in units if unit.unit_type in data)
    return {
        "army_supply": round(army_supply, 1),
        "supply_cap": round(supply_cap, 1),
        "workers": workers,
        "army": len(army_units),
        "buildings": buildings,
        "bases": bases,
        "expansions": max(0, bases - baseline_bases),
        "counts": counts,
    }


async def run(duration: int, archive_baseline_mod: bool = False) -> int:
    config = make_config()
    v3_config = V3BuildConfig(campaign_units=True, player_builds=tuple((case.logical_slot, case.key) for case in CASES))
    build_v3_map(PROJECT_ROOT, BASE_MAP, OUTPUT_MAP, config, v3_config, observer_mode=True, active_config_file=OUTPUT_MAP.with_suffix(".json"))
    if archive_baseline_mod:
        if not ARCHIVE_BASELINE_MOD.is_file():
            raise FileNotFoundError(f"03:47 기준 mod를 찾을 수 없습니다: {ARCHIVE_BASELINE_MOD}")
        shutil.copy2(ARCHIVE_BASELINE_MOD, PROJECT_ROOT / "runtime" / "mods" / "SC2TeamV3AI.SC2Mod")
        print("V3_MOD_SOURCE=ARCHIVE_0347")
    else:
        print("V3_MOD_SOURCE=FORMAL_REBUILD")
    executable = discover_sc2_executable()
    install_v3_mod(PROJECT_ROOT, executable.parents[2])
    process = launch_sc2(executable, PORT, 0, width=1280, height=720, fullscreen=False)
    connection: Sc2Connection | None = None
    failures: list[str] = []
    final: dict[int, dict[str, Any]] = {}
    peak_roster: dict[int, Counter[str]] = {owner: Counter() for owner in range(1, len(CASES) + 1)}
    peak_expansions: dict[int, int] = {owner: 0 for owner in range(1, len(CASES) + 1)}
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
            owner: sum(1 for unit in first.observation.raw_data.units if unit.owner == owner and names.get(unit.unit_type) in TOWN_HALLS)
            for owner in range(1, len(CASES) + 1)
        }
        print(f"V3_GROUND_COMPILE=PASS players={len(CASES)} unit_types={len(data)}")
        elapsed = 5
        for game_seconds in range(180, duration + 1, 180):
            await connection.step((game_seconds - elapsed) * 16)
            elapsed = game_seconds
            observation = await connection.observation(disable_fog=True)
            print(f"SAMPLE minute={game_seconds // 60}")
            for owner, case in enumerate(CASES, start=1):
                state = snapshot(observation, owner, names, data, structures, baseline_bases[owner])
                final[owner] = state
                for unit_name in case.roster:
                    peak_roster[owner][unit_name] = max(peak_roster[owner][unit_name], state["counts"][unit_name])
                peak_expansions[owner] = max(peak_expansions[owner], state["expansions"])
                roster = {name: state["counts"][name] for name in case.roster}
                print(
                    f"  P{owner} {case.label}: pop={state['army_supply']:g}/{state['supply_cap']:g} "
                    f"workers={state['workers']} army={state['army']} buildings={state['buildings']} "
                    f"bases={state['bases']} expansions={state['expansions']} roster={roster}"
                )
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

    for owner, case in enumerate(CASES, start=1):
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
        for owner, case in enumerate(CASES, start=1):
            state = final.get(owner)
            if state is not None and state["workers"] <= 14:
                failures.append(f"P{owner} {case.label} workers stalled at {state['workers']}")
            if peak_expansions[owner] < 1:
                failures.append(f"P{owner} {case.label} did not complete the first expansion")
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
    args = parser.parse_args()
    if args.duration < 180 or args.duration % 180:
        parser.error("duration must be a multiple of 180 and at least 180 seconds")
    return asyncio.run(run(args.duration, args.archive_baseline_mod))


if __name__ == "__main__":
    raise SystemExit(main())
