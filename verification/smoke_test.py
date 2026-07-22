from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sc2team.process import discover_sc2_executable, launch_sc2, stop_process
from sc2team.protocol import (
    Sc2Connection,
    make_multiplayer_ports,
    races_for_players,
)


async def run_test(
    map_file: Path,
    seconds: float,
    participant_count: int,
    computer_count: int,
) -> None:
    executable = discover_sc2_executable()
    api_ports = tuple(14100 + index for index in range(participant_count))
    game_ports = (
        make_multiplayer_ports(14200, len(api_ports))
        if len(api_ports) > 1
        else None
    )
    processes = []
    connections: list[Sc2Connection] = []

    print(f"SC2 executable: {executable}")
    print(f"Map: {map_file}")
    try:
        for index, api_port in enumerate(api_ports):
            processes.append(launch_sc2(executable, api_port, index))
        print(
            f"Launched {participant_count} SC2 processes; waiting for API ports..."
        )

        connections = list(
            await asyncio.gather(*(Sc2Connection.open(port) for port in api_ports))
        )
        versions = await asyncio.gather(*(connection.ping() for connection in connections))
        print("Connected:", ", ".join(version.game_version for version in versions))

        await connections[0].create_game(
            map_file.name,
            map_file.read_bytes(),
            len(connections),
            computer_count=computer_count,
            realtime=True,
        )
        print(
            "Created game with "
            f"{participant_count} participants and {computer_count} computers; "
            "joining API clients..."
        )

        player_ids = await asyncio.gather(
            *(
                connection.join_game(race, f"Local Player {index + 1}", game_ports)
                for index, (connection, race) in enumerate(
                    zip(connections, races_for_players(len(connections)))
                )
            )
        )
        print(f"SUCCESS: participants joined with player IDs {player_ids}")
        print(f"Keeping the game open for {seconds:g} seconds...")

        deadline = asyncio.get_running_loop().time() + seconds
        while asyncio.get_running_loop().time() < deadline:
            observations = await asyncio.gather(
                *(connection.observation() for connection in connections)
            )
            loops = [observation.observation.game_loop for observation in observations]
            print(f"game loops: {loops}")
            await asyncio.sleep(1)
    except Exception:
        print(
            "SC2 process states at failure:",
            [process.poll() for process in processes],
        )
        for process in processes:
            temp_directory = getattr(process, "sc2_temp_directory", None)
            print(f"SC2 temp directory: {temp_directory}")
            if temp_directory is not None and temp_directory.is_dir():
                for path in sorted(temp_directory.rglob("*")):
                    if path.is_file():
                        print(f"  {path.relative_to(temp_directory)} ({path.stat().st_size} bytes)")
        raise
    finally:
        await asyncio.gather(
            *(connection.quit() for connection in connections),
            return_exceptions=True,
        )
        await asyncio.gather(
            *(connection.close() for connection in connections),
            return_exceptions=True,
        )
        for process in processes:
            stop_process(process)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify four-player SC2 API connectivity")
    parser.add_argument(
        "--map",
        type=Path,
        default=PROJECT_ROOT / "maps" / "Melee" / "Flat128.SC2Map",
        help="Local SC2Map file used for the connectivity test",
    )
    parser.add_argument("--seconds", type=float, default=10.0)
    parser.add_argument("--participants", type=int, default=4)
    parser.add_argument("--computers", type=int, default=0)
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    asyncio.run(
        run_test(
            arguments.map.resolve(),
            arguments.seconds,
            arguments.participants,
            arguments.computers,
        )
    )
