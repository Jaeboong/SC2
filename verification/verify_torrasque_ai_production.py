from __future__ import annotations

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


BASE_MAP_FILE = (
    PROJECT_ROOT
    / "maps"
    / "generated"
    / "europe-melee-2-7v7-rich-50000-fixed-teams.SC2Map"
)
RUNTIME_MAP_FILE = PROJECT_ROOT / "runtime" / "maps" / "torrasque-production-probe.SC2Map"
PORT = 14115
ZERG_AI_RUNTIME_PLAYER = 2
MAX_GAME_LOOPS = 33_600  # 1,500 in-game seconds; Hive tech is intentionally slow.
STEP_LOOPS = 448  # 20 in-game seconds per observation.


def probe_config() -> CustomLauncherConfig:
    players = {
        1: ("human", "Terran", "bio_tank"),
        2: ("custom_ai", "Zerg", "ultra_ling_bane"),
        8: ("custom_ai", "Terran", "mech_macro"),
    }
    slots = []
    for slot_id in range(1, 15):
        controller, race, build = players.get(
            slot_id, ("empty", "Random", "random_ground")
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
    connection: Sc2Connection | None = None
    try:
        connection = await Sc2Connection.open(PORT)
        await connection.create_game_with_setups(
            RUNTIME_MAP_FILE.name,
            RUNTIME_MAP_FILE.read_bytes(),
            player_setups(config),
            realtime=False,
        )
        await connection.join_game(
            RACE_VALUES[config.human.race],
            "Torrasque AI Production Verification",
            None,
        )

        data_request = sc_pb.Request()
        data_request.data.CopyFrom(sc_pb.RequestData(unit_type_id=True))
        game_data = (await connection.request(data_request)).data
        unit_id_by_name = {unit.name: unit.unit_id for unit in game_data.units}
        torrasque_id = unit_id_by_name["HotSTorrasque"]
        torrasque_data = next(unit for unit in game_data.units if unit.name == "HotSTorrasque")
        print(
            f"unit_id=native_torrasque:{torrasque_id} "
            f"available={torrasque_data.available} ability_id={torrasque_data.ability_id}"
        )

        last_report = -1
        while True:
            await connection.step(STEP_LOOPS)
            observation = await connection.observation(disable_fog=True)
            game_loop = observation.observation.game_loop
            counts = Counter(
                unit.unit_type
                for unit in observation.observation.raw_data.units
                if unit.owner == ZERG_AI_RUNTIME_PLAYER
            )
            seconds = game_loop / 22.4
            report_bucket = int(seconds // 100)
            if report_bucket != last_report:
                last_report = report_bucket
                print(
                    f"t={seconds:.0f}s hatchery={counts[86]} lair={counts[100]} "
                    f"hive={counts[101]} infestation_pit={counts[94]} "
                    f"ultralisk_cavern={counts[93]} "
                    f"torrasque={counts[torrasque_id]}"
                )
            if counts[torrasque_id] > 0:
                print("TORRASQUE_AI_PRODUCTION=PASS")
                return
            if observation.player_result:
                raise RuntimeError(
                    f"TORRASQUE_AI_PRODUCTION=FAIL: game ended at {seconds:.0f}s"
                )
            if game_loop >= MAX_GAME_LOOPS:
                raise RuntimeError(
                    "TORRASQUE_AI_PRODUCTION=FAIL: no Torrasque by 1,500 game seconds"
                )
    finally:
        if connection is not None:
            await connection.quit()
            await connection.close()
        stop_process(process)


if __name__ == "__main__":
    asyncio.run(main())
