from __future__ import annotations

import argparse
import asyncio
from math import hypot
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from s2clientprotocol import common_pb2 as common_pb
from s2clientprotocol import raw_pb2 as raw_pb
from s2clientprotocol import sc2api_pb2 as sc_pb

from sc2team.process import discover_sc2_executable, launch_sc2, stop_process
from sc2team.protocol import ComputerPlayer, Sc2Connection


P1_START = (10.5, 144.5)
P2_START = (200.5, 129.5)


async def verify_map(map_file: Path, seconds: float, api_port: int) -> None:
    executable = discover_sc2_executable()
    process = launch_sc2(executable, api_port, 0)
    connection: Sc2Connection | None = None

    try:
        connection = await Sc2Connection.open(api_port)
        version = await connection.ping()
        print(f"Connected: SC2 {version.game_version}")

        await connection.create_game(
            map_file.name,
            map_file.read_bytes(),
            participant_count=1,
            computer_players=(
                ComputerPlayer(
                    race=common_pb.Protoss,
                    difficulty=sc_pb.VeryHard,
                    ai_build=sc_pb.Macro,
                    player_name="Pro Bot vision verifier",
                ),
            ),
            realtime=True,
        )
        player_id = await connection.join_game(common_pb.Terran, "Local Human", None)
        if player_id != 1:
            raise AssertionError(f"Human joined an unexpected slot: P{player_id}")

        deadline = asyncio.get_running_loop().time() + seconds
        observation = None
        while asyncio.get_running_loop().time() < deadline:
            # Intentionally do not request disable_fog. Enemy units must be
            # visible because the map itself grants permanent vision to P1.
            observation = await connection.observation(disable_fog=False)
            await asyncio.sleep(0.25)

        if observation is None:
            raise RuntimeError("No observation was returned")

        units = observation.observation.raw_data.units
        p1_units = [unit for unit in units if unit.owner == 1]
        p2_units = [unit for unit in units if unit.owner == 2]
        p1_at_start = [
            unit
            for unit in p1_units
            if hypot(unit.pos.x - P1_START[0], unit.pos.y - P1_START[1]) <= 16.0
        ]
        p2_at_start = [
            unit
            for unit in p2_units
            if hypot(unit.pos.x - P2_START[0], unit.pos.y - P2_START[1]) <= 16.0
        ]

        if not p1_at_start:
            raise AssertionError("P1 starting units are missing from the west base")
        if not p2_at_start:
            raise AssertionError(
                "P2 units were not visible at the east base without disable_fog"
            )
        if not any(unit.alliance == raw_pb.Enemy for unit in p2_units):
            raise AssertionError("P2 is not classified as P1's enemy")

        food_used = observation.observation.player_common.food_used
        if food_used != 0:
            raise AssertionError(f"Worker supply override failed: food_used={food_used}")

        resources = [
            max(unit.mineral_contents, unit.vespene_contents)
            for unit in units
            if unit.mineral_contents > 0 or unit.vespene_contents > 0
        ]
        if not resources or max(resources) != 50000:
            raise AssertionError(
                f"Rich-resource amount check failed: max={max(resources, default=0)}"
            )

        print(f"Game loop: {observation.observation.game_loop}")
        print(f"P1 west start units: {len(p1_at_start)}")
        print(f"P2 east start units visible to P1: {len(p2_at_start)}")
        print("Human full-map vision: PASS (disable_fog=False)")
        print("1v1 fixed starts and enemy relation: PASS")
        print("Worker supply 0 and resources 50000: PASS")
    finally:
        if connection is not None:
            await connection.quit()
            await connection.close()
        stop_process(process)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify the Pro Bot 1v1 test map")
    parser.add_argument(
        "map",
        nargs="?",
        type=Path,
        default=PROJECT_ROOT / "map" / "source" / "europe-melee-2-Pro-Bot_test.SC2Map",
    )
    parser.add_argument("--seconds", type=float, default=5.0)
    parser.add_argument("--api-port", type=int, default=14100)
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    asyncio.run(
        verify_map(arguments.map.resolve(), arguments.seconds, arguments.api_port)
    )
