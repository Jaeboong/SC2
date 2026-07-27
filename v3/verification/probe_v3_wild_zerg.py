"""Measure P15's embedded campaign economy through the SC2 engine.

The policy develops and defends from game start, keeps proactive attack state
at Wait until 540 seconds, then releases its gathered army.  This probe checks
actual production and gas assignment; it does not rely on source markers.
"""

from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
for extra in (PROJECT_ROOT, PROJECT_ROOT / "v3"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from s2clientprotocol import sc2api_pb2 as sc_pb  # noqa: E402

from sc2team.custom_config import CustomLauncherConfig, SlotConfig  # noqa: E402
from sc2team.custom_runtime import player_setups  # noqa: E402
from sc2team.process import discover_sc2_executable, launch_sc2, stop_process  # noqa: E402
from sc2team.protocol import Sc2Connection  # noqa: E402
from sc2team_v3.config import V3BuildConfig  # noqa: E402
from sc2team_v3.runtime import build_v3_map, install_v3_mod, make_v3_plan  # noqa: E402


BASE_MAP = PROJECT_ROOT / "maps" / "generated" / "europe-melee-2-7v7-rich-50000-fixed-teams.SC2Map"
OUTPUT_MAP = PROJECT_ROOT / "runtime" / "maps" / "v3-wild-zerg-probe.SC2Map"
PORT = 14184
RESILIENCE_PORT = 14185
P15 = 15
GAS_TYPES = frozenset({"Extractor", "ExtractorRich"})
TOWN_HALL_TYPES = frozenset({"Hatchery", "Lair", "Hive"})
COMBAT_SUPPLY_TENTHS = {
    "Zergling": 5,
    "Baneling": 5,
    "Roach": 20,
    "Ravager": 30,
    "Hydralisk": 20,
    "LurkerMP": 30,
    "Ultralisk": 80,
}


def make_config() -> CustomLauncherConfig:
    slots = []
    for slot in range(1, 15):
        if slot == 1:
            controller, race, build = "human", "Terran", "bio_tank"
        else:
            controller, race, build = "empty", "Random", "random_ground"
        slots.append(SlotConfig(slot=slot, controller=controller, team=1 if slot <= 7 else 2, race=race, build=build))
    config = CustomLauncherConfig(version=1, slots=tuple(slots), wild_zerg=True, unit_control=False)
    config.validate()
    return config


async def unit_names(connection: Sc2Connection) -> dict[int, str]:
    request = sc_pb.Request()
    request.data.CopyFrom(sc_pb.RequestData(unit_type_id=True))
    return {unit.unit_id: unit.name for unit in (await connection.request(request)).data.units}


def snapshot(observation: Any, names: dict[int, str]) -> dict[str, int]:
    units = [unit for unit in observation.observation.raw_data.units if int(unit.owner) == P15]
    counts = Counter(names.get(unit.unit_type, str(unit.unit_type)) for unit in units)
    extractors = [
        unit for unit in units
        if names.get(unit.unit_type) in GAS_TYPES and float(unit.build_progress) >= 1.0
    ]
    gas_tags = {unit.tag for unit in extractors}
    army_supply_tenths = sum(
        count * COMBAT_SUPPLY_TENTHS.get(name, 0)
        for name, count in counts.items()
    )
    gas_order_workers = sum(
        1
        for unit in units
        if names.get(unit.unit_type) == "Drone"
        and any(order.target_unit_tag in gas_tags for order in unit.orders)
    )
    return {
        "drones": int(counts["Drone"]),
        "zerglings": int(counts["Zergling"]),
        "roaches": int(counts["Roach"]),
        "hydralisks": int(counts["Hydralisk"]),
        "ultralisks": int(counts["Ultralisk"]),
        "queens": int(counts["Queen"]),
        "hatcheries": int(counts["Hatchery"] + counts["Lair"] + counts["Hive"]),
        "spines": int(counts["SpineCrawler"]),
        "spores": int(counts["SporeCrawler"]),
        "eggs": int(counts["Egg"]),
        "extractors": len(extractors),
        "gas_order_workers": gas_order_workers,
        "gas_assigned": sum(int(unit.assigned_harvesters) for unit in extractors),
        "gas_ideal": sum(int(unit.ideal_harvesters) for unit in extractors),
        "infestation_pits": int(counts["InfestationPit"]),
        "hives": int(counts["Hive"]),
        "ultralisk_caverns": int(counts["UltraliskCavern"]),
        "army_supply_estimate": army_supply_tenths // 10,
        "total_supply_estimate": (
            army_supply_tenths + int(counts["Drone"]) * 10 + int(counts["Queen"]) * 20
        ) // 10,
    }


def points_for(observation: Any, names: dict[int, str], owner: int, types: frozenset[str]) -> list[tuple[float, float]]:
    return [
        (float(unit.pos.x), float(unit.pos.y))
        for unit in observation.observation.raw_data.units
        if int(unit.owner) == owner and names.get(unit.unit_type) in types
    ]


def position_metrics(
    observation: Any,
    names: dict[int, str],
    nest_points: list[tuple[float, float]],
    enemy_base_points: list[tuple[float, float]],
) -> dict[str, int]:
    combat_points = [
        (float(unit.pos.x), float(unit.pos.y))
        for unit in observation.observation.raw_data.units
        if int(unit.owner) == P15 and names.get(unit.unit_type) in COMBAT_SUPPLY_TENTHS
    ]

    def nearby(point: tuple[float, float], radius: float) -> int:
        radius_sq = radius * radius
        return sum(
            1
            for combat in combat_points
            if (combat[0] - point[0]) ** 2 + (combat[1] - point[1]) ** 2 <= radius_sq
        )

    local_counts = [nearby(point, 24.0) for point in nest_points]
    alpha = min(nest_points, key=lambda point: (point[0] - 237.5) ** 2 + (point[1] - 240.5) ** 2)
    far_from_nests = sum(
        1
        for combat in combat_points
        if all((combat[0] - nest[0]) ** 2 + (combat[1] - nest[1]) ** 2 > 32.0**2 for nest in nest_points)
    )
    return {
        "garrisoned_nests": sum(count >= 4 for count in local_counts),
        "nest_count": len(nest_points),
        "alpha_garrison": nearby(alpha, 30.0),
        "far_from_nests": far_from_nests,
        "enemy_base_pressure": sum(nearby(point, 30.0) for point in enemy_base_points),
    }


def combat_tags(observation: Any, names: dict[int, str]) -> set[int]:
    return {
        int(unit.tag)
        for unit in observation.observation.raw_data.units
        if int(unit.owner) == P15 and names.get(unit.unit_type) in COMBAT_SUPPLY_TENTHS
    }


async def run(*, destroy_locals: bool = False) -> int:
    config = make_config()
    standalone_plan = make_v3_plan(config, V3BuildConfig(), observer_mode=False)
    if standalone_plan["players"] or standalone_plan["wild_zerg"] is not True:
        raise RuntimeError("P15-only normal-game V3 plan contract failed")
    OUTPUT_MAP.parent.mkdir(parents=True, exist_ok=True)
    runtime_map = build_v3_map(
        PROJECT_ROOT,
        BASE_MAP,
        OUTPUT_MAP,
        config,
        # No P1-P14 custom build is selected. Observer mode turns logical P1
        # into the sole ordinary Computer opponent; P15 build 315 is independent
        # of both the 7v7 roster and normal V3 build selections.
        V3BuildConfig(),
        observer_mode=True,
        active_config_file=OUTPUT_MAP.with_suffix(".json"),
    )
    if destroy_locals:
        subprocess.run(
            [
                "node",
                str(PROJECT_ROOT / "v3" / "tools" / "patch_v3_wild_resilience_probe.cjs"),
                str(runtime_map),
            ],
            cwd=PROJECT_ROOT,
            check=True,
        )
    executable = discover_sc2_executable()
    install_v3_mod(PROJECT_ROOT, executable.parents[2])
    port = RESILIENCE_PORT if destroy_locals else PORT
    process = launch_sc2(executable, port, 0)
    connection: Sc2Connection | None = None
    elapsed = 0
    samples: dict[int, dict[str, int]] = {}
    try:
        connection = await Sc2Connection.open(port)
        await connection.create_game_with_setups(runtime_map.name, runtime_map.read_bytes(), player_setups(config, observer=True), realtime=False)
        await connection.join_as_observer()
        names = await unit_names(connection)
        nest_points: list[tuple[float, float]] = []
        enemy_base_points: list[tuple[float, float]] = []
        tags_before_destroy: set[int] = set()
        for checkpoint in (120, 360, 539, 541, 600, 720):
            await connection.step((checkpoint - elapsed) * 16)
            elapsed = checkpoint
            observation = await connection.observation(disable_fog=True)
            samples[checkpoint] = snapshot(observation, names)
            if not nest_points:
                nest_points = points_for(observation, names, P15, TOWN_HALL_TYPES)
                enemy_base_points = [
                    (float(unit.pos.x), float(unit.pos.y))
                    for unit in observation.observation.raw_data.units
                    if int(unit.owner) != P15
                    and 1 <= int(unit.owner) <= 14
                    and names.get(unit.unit_type) in {
                        "CommandCenter", "OrbitalCommand", "PlanetaryFortress",
                        "Nexus", "Hatchery", "Lair", "Hive",
                    }
                ]
            samples[checkpoint].update(
                position_metrics(observation, names, nest_points, enemy_base_points)
            )
            if tags_before_destroy:
                samples[checkpoint]["new_combat_since_destroy"] = len(
                    combat_tags(observation, names) - tags_before_destroy
                )
            print(f"P15_WILD @{checkpoint}s {samples[checkpoint]}")
            if destroy_locals and checkpoint == 360:
                tags_before_destroy = combat_tags(observation, names)
                print("P15_LOCAL_WIPE scheduled=361s radius=42")
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

    before = samples[120]
    developed = samples[539]
    after = samples[720]
    failures = []
    if destroy_locals:
        if developed["hatcheries"] >= samples[360]["hatcheries"]:
            failures.append("local wipe did not reduce P15 town halls")
        if developed["alpha_garrison"] < 16:
            failures.append(
                "alpha garrison collapsed after local wipe "
                f"({developed['alpha_garrison']})"
            )
        if developed.get("new_combat_since_destroy", 0) < 4:
            failures.append(
                "alpha did not produce fresh combat units after local wipe "
                f"({developed.get('new_combat_since_destroy', 0)})"
            )
        if failures:
            print("V3_WILD_ZERG_RESILIENCE=FAIL " + "; ".join(failures))
            return 1
        print("V3_WILD_ZERG_RESILIENCE=PASS")
        return 0
    if developed["drones"] < 32:
        failures.append(
            "Drone production did not establish the multi-town economy "
            f"({developed['drones']})"
        )
    if developed["roaches"] <= before["roaches"] and developed["hydralisks"] <= before["hydralisks"]:
        failures.append("Roach/Hydralisk production did not grow before 9:00")
    if developed["spines"] + developed["spores"] <= before["spines"] + before["spores"]:
        failures.append("town-defense structures did not grow before 9:00")
    if developed["garrisoned_nests"] < min(4, developed["nest_count"]):
        failures.append(
            "local GuardHome reserves did not cover enough nests "
            f"({developed['garrisoned_nests']}/{developed['nest_count']})"
        )
    if developed["enemy_base_pressure"] > 0:
        failures.append(
            "P15 combat units reached an enemy base before 9:00 "
            f"({developed['enemy_base_pressure']})"
        )
    if after["far_from_nests"] < 12:
        failures.append(
            "surplus army did not leave the nest network after 9:00 "
            f"({after['far_from_nests']})"
        )
    if developed["ultralisk_caverns"] < 1 or developed["ultralisks"] < 1:
        failures.append("alpha Hive/Ultralisk development did not produce an Ultralisk before 9:00")
    if failures:
        print("V3_WILD_ZERG_DRONES=FAIL " + "; ".join(failures))
        return 1
    print("V3_WILD_ZERG_CAMPAIGN=PASS")
    if after["extractors"] > 0 and after["gas_assigned"] == 0:
        print("V3_WILD_ZERG_GAS=UNRESOLVED completed_extractors_without_assigned_workers")
    else:
        print("V3_WILD_ZERG_GAS=PASS")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--destroy-locals",
        action="store_true",
        help="At 6:00, test-wipe P15 outside the alpha region and verify alpha recovery",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    raise SystemExit(asyncio.run(run(destroy_locals=args.destroy_locals)))
