from __future__ import annotations

"""Stepped engine probe for the neutral-hostile P15 Zerg controller.

P15 is not a lobby Computer, so ordinary melee-AI production probes cannot see
whether its map-side LarvaTrain orders actually resolve.  This keeps every
lobby opponent out of the way and records P15's real Larvae, Eggs, structures,
and army units at 20-game-second intervals.
"""

import asyncio
from collections import Counter
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from s2clientprotocol import sc2api_pb2 as sc_pb

from sc2team.custom_config import CustomLauncherConfig, SlotConfig
from sc2team.custom_runtime import RACE_VALUES, build_runtime_map, player_setups
from sc2team.process import discover_sc2_executable, launch_sc2, stop_process
from sc2team.protocol import Sc2Connection


BASE_MAP_FILE = PROJECT_ROOT / "map" / "source" / "europe-melee-2-7v7-rich-50000-fixed-teams.SC2Map"
RUNTIME_MAP_FILE = PROJECT_ROOT / "runtime" / "maps" / "hostile-wild-production-probe.SC2Map"
PORT = 14130
STEP_LOOPS = 448  # 20 game seconds per sample.
MAX_GAME_LOOPS = 11_200  # 500 game seconds: past the seven-minute activation gate.
P15 = 15
TRACKED_NAMES = (
    "Larva", "Egg", "Drone", "Overlord", "Zergling", "Roach", "Hydralisk",
    "Hatchery", "Lair", "Hive", "SpawningPool", "RoachWarren", "HydraliskDen",
)
ARMY_NAMES = {"Zergling", "Roach", "Hydralisk"}


def probe_config() -> CustomLauncherConfig:
    slots = []
    for slot_id in range(1, 15):
        controller, race, build = (
            ("human", "Terran", "bio_tank")
            if slot_id == 1
            else ("custom_ai", "Protoss", "gateway")
            if slot_id == 8
            else ("empty", "Random", "random_ground")
        )
        slots.append(
            SlotConfig(
                slot=slot_id,
                controller=controller,
                team=1 if slot_id <= 7 else 2,
                race=race,
                build=build,
            )
        )
    config = CustomLauncherConfig(version=1, slots=tuple(slots))
    config.validate()
    return config


async def main() -> None:
    config = probe_config()
    build_runtime_map(
        PROJECT_ROOT,
        BASE_MAP_FILE,
        RUNTIME_MAP_FILE,
        config,
        strategy_bridge=True,
        campaign_units_pilot=True,
        active_config_file=RUNTIME_MAP_FILE.with_suffix(".json"),
    )

    process = launch_sc2(discover_sc2_executable(), PORT, 0)
    print(f"SC2 launch pid={process.pid}", flush=True)
    connection: Sc2Connection | None = None
    try:
        # Cold starts on this workstation occasionally need longer than the
        # generic 45-second API wait, especially after SC2 was just closed.
        connection = await Sc2Connection.open(PORT, timeout=120.0)
        await connection.create_game_with_setups(
            RUNTIME_MAP_FILE.name,
            RUNTIME_MAP_FILE.read_bytes(),
            player_setups(config),
            realtime=False,
        )
        await connection.join_game(RACE_VALUES[config.human.race], "P15 Wild Production Probe", None)

        data_request = sc_pb.Request()
        data_request.data.CopyFrom(sc_pb.RequestData(unit_type_id=True))
        game_data = (await connection.request(data_request)).data
        ids = {unit.name: unit.unit_id for unit in game_data.units}
        tracked_ids = {name: ids[name] for name in TRACKED_NAMES}
        army_ids = {ids[name] for name in ARMY_NAMES}
        larva_id = ids["Larva"]
        baseline_army_tags: set[int] | None = None
        max_eggs = 0
        max_army = 0
        max_new_army = 0

        while True:
            await connection.step(STEP_LOOPS)
            observation = await connection.observation(disable_fog=True)
            units = [
                unit for unit in observation.observation.raw_data.units if unit.owner == P15
            ]
            counts = Counter(unit.unit_type for unit in units)
            army_tags = {unit.tag for unit in units if unit.unit_type in army_ids}
            if baseline_army_tags is None:
                baseline_army_tags = set(army_tags)
            new_army = army_tags - baseline_army_tags
            larvae_with_orders = sum(
                1
                for unit in units
                if unit.unit_type == larva_id and unit.orders
            )
            max_eggs = max(max_eggs, counts[ids["Egg"]])
            max_army = max(max_army, len(army_tags))
            max_new_army = max(max_new_army, len(new_army))
            seconds = observation.observation.game_loop / 22.4
            summary = " ".join(
                f"{name}={counts[unit_id]}" for name, unit_id in tracked_ids.items()
            )
            print(
                f"t={seconds:.0f}s {summary} army={len(army_tags)} "
                f"new_army={len(new_army)} larva_orders={larvae_with_orders}"
            )
            if observation.player_result:
                raise RuntimeError(f"P15_WILD_PRODUCTION=FAIL game ended at {seconds:.0f}s")
            if observation.observation.game_loop >= MAX_GAME_LOOPS:
                break

        if max_eggs == 0:
            raise RuntimeError("P15_WILD_PRODUCTION=FAIL no Egg: LarvaTrain never resolved")
        if max_new_army == 0:
            raise RuntimeError(
                "P15_WILD_PRODUCTION=FAIL no newly trained Zergling/Roach/Hydralisk"
            )
        print(
            "P15_WILD_PRODUCTION=PASS "
            f"max_eggs={max_eggs} max_army={max_army} max_new_army={max_new_army}"
        )
    finally:
        if connection is not None:
            await connection.quit()
            await connection.close()
        stop_process(process)
        print(f"SC2 exit_code={process.poll()}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
