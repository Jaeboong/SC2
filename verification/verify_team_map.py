from __future__ import annotations

import argparse
import asyncio
from collections import Counter, defaultdict
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


EXPECTED_STARTS = {
    1: (28.5, 11.5),
    2: (27.5, 47.5),
    3: (13.5, 90.5),
    4: (10.5, 144.5),
    5: (61.5, 181.5),
    6: (47.5, 221.5),
    7: (8.5, 245.5),
    8: (199.5, 14.5),
    9: (246.5, 32.5),
    10: (186.5, 60.5),
    11: (200.5, 129.5),
    12: (231.5, 159.5),
    13: (161.5, 188.5),
    14: (237.5, 240.5),
}


async def verify_map(map_file: Path, seconds: float, api_port: int) -> None:
    executable = discover_sc2_executable()
    process = launch_sc2(executable, api_port, 0)
    connection: Sc2Connection | None = None

    try:
        connection = await Sc2Connection.open(api_port)
        version = await connection.ping()
        print(f"Connected: SC2 {version.game_version}")

        computer_players = tuple(
            ComputerPlayer(
                race=common_pb.Terran if slot <= 7 else common_pb.Protoss,
                difficulty=sc_pb.VeryHard,
                ai_build=sc_pb.Macro,
                player_name=f"P{slot} team-slot verifier",
            )
            for slot in range(2, 15)
        )
        await connection.create_game(
            map_file.name,
            map_file.read_bytes(),
            participant_count=1,
            computer_players=computer_players,
            realtime=True,
        )
        player_id = await connection.join_game(common_pb.Terran, "Local Human", None)
        print(f"Joined as player {player_id}; waiting for map initialization...")

        deadline = asyncio.get_running_loop().time() + seconds
        observation = None
        while asyncio.get_running_loop().time() < deadline:
            observation = await connection.observation(disable_fog=True)
            await asyncio.sleep(0.25)

        if observation is None:
            raise RuntimeError("No observation was returned")

        raw_units = observation.observation.raw_data.units
        resource_units = [
            unit
            for unit in raw_units
            if unit.mineral_contents > 0 or unit.vespene_contents > 0
        ]
        resource_amounts = [
            max(unit.mineral_contents, unit.vespene_contents)
            for unit in resource_units
        ]
        # Workers may have completed a mining trip by the time the observation
        # is sampled, so active fields can be a few resources below 50000.
        if not resource_amounts or max(resource_amounts) != 50000:
            raise AssertionError(
                f"Resource amount check failed: "
                f"range={min(resource_amounts, default=0)}..{max(resource_amounts, default=0)}"
            )
        positions: dict[int, list[tuple[float, float]]] = defaultdict(list)
        start_positions: dict[int, list[tuple[float, float]]] = defaultdict(list)
        town_halls: dict[int, list[object]] = defaultdict(list)
        alliances: dict[int, Counter[int]] = defaultdict(Counter)
        for unit in raw_units:
            if 1 <= unit.owner <= 14:
                position = (unit.pos.x, unit.pos.y)
                positions[unit.owner].append(position)
                expected = EXPECTED_STARTS[unit.owner]
                if hypot(position[0] - expected[0], position[1] - expected[1]) <= 16.0:
                    start_positions[unit.owner].append(position)
                if unit.ideal_harvesters >= 10:
                    town_halls[unit.owner].append(unit)
                alliances[unit.owner][unit.alliance] += 1

        missing = [player for player in range(1, 15) if not start_positions[player]]
        if missing:
            raise AssertionError(f"No starting units observed at assigned bases: {missing}")

        # The verification game mirrors the reported Battle.net setup:
        # west/team 1 is Terran and east/team 2 is Protoss. Town halls are
        # stable race markers even after workers start moving.
        expected_town_hall_type = {
            player: 18 if player <= 7 else 59 for player in range(1, 15)
        }
        race_mismatches = [
            player
            for player in range(1, 15)
            if expected_town_hall_type[player]
            not in {
                unit.unit_type
                for unit in raw_units
                if unit.owner == player
                and hypot(
                    unit.pos.x - EXPECTED_STARTS[player][0],
                    unit.pos.y - EXPECTED_STARTS[player][1],
                )
                <= 16.0
            }
        ]
        if race_mismatches:
            raise AssertionError(
                "Terran-west/Protoss-east race check failed for players: "
                f"{race_mismatches}"
            )

        # Detailed harvester/rally metadata is only exposed for the joined
        # participant's own structures, even with disable_fog enabled.
        if not town_halls[1]:
            raise AssertionError("No town hall observed for player 1")

        rally_distances: dict[int, list[float]] = {}
        for player in range(1, 15):
            expected = EXPECTED_STARTS[player]
            distances = [
                hypot(target.point.x - expected[0], target.point.y - expected[1])
                for town_hall in town_halls[player]
                for target in town_hall.rally_targets
                if target.HasField("point")
            ]
            rally_distances[player] = distances
            if distances and min(distances) > 20.0:
                raise AssertionError(
                    f"P{player} town-hall rally is still tied to the old start: "
                    f"nearest distance={min(distances):.1f}"
                )

        center_x = {
            player: sum(x for x, _ in points) / len(points)
            for player, points in start_positions.items()
        }
        west_max = max(center_x[player] for player in range(1, 8))
        east_min = min(center_x[player] for player in range(8, 15))
        if not west_max < east_min:
            raise AssertionError(
                f"East/west separation failed: west max={west_max:.1f}, "
                f"east min={east_min:.1f}"
            )

        for player in range(2, 8):
            if alliances[player][raw_pb.Ally] == 0:
                raise AssertionError(f"Player {player} is not allied with player 1")
        for player in range(8, 15):
            if alliances[player][raw_pb.Enemy] == 0:
                raise AssertionError(f"Player {player} is not an enemy of player 1")

        food_used = observation.observation.player_common.food_used
        if food_used != 0:
            raise AssertionError(f"Worker supply override failed: food_used={food_used}")

        print(f"Game loop: {observation.observation.game_loop}")
        print("Player centers and alliance as seen by player 1:")
        for player in range(1, 15):
            alliance_names = {
                raw_pb.Self: "Self",
                raw_pb.Ally: "Ally",
                raw_pb.Neutral: "Neutral",
                raw_pb.Enemy: "Enemy",
            }
            primary_alliance = alliances[player].most_common(1)[0][0]
            rally_text = (
                f"{min(rally_distances[player]):4.1f}"
                if rally_distances[player]
                else " n/a"
            )
            print(
                f"  P{player}: x={center_x[player]:6.1f}, "
                f"start units={len(start_positions[player]):2d}, "
                f"all owned={len(positions[player]):3d}, "
                f"rally distance={rally_text}, "
                f"alliance={alliance_names.get(primary_alliance, primary_alliance)}"
            )
        print("Worker supply check: PASS (player 1 food_used=0)")
        print("Race/team slot check: PASS (P1-P7 Terran, P8-P14 Protoss)")
        print(
            f"Resource amount check: PASS ({len(resource_units)} fields/geysers, "
            f"observed {min(resource_amounts)}..{max(resource_amounts)} after mining began)"
        )
        print("East/west 7v7 alliance and placement check: PASS")
    finally:
        if connection is not None:
            await connection.quit()
            await connection.close()
        stop_process(process)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify the custom local SC2 7v7 map")
    parser.add_argument("map", type=Path)
    parser.add_argument("--seconds", type=float, default=5.0)
    parser.add_argument("--api-port", type=int, default=14100)
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    asyncio.run(
        verify_map(arguments.map.resolve(), arguments.seconds, arguments.api_port)
    )
