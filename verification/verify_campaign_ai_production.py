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


BASE_MAP_FILE = PROJECT_ROOT / "map" / "source" / "europe-melee-2-7v7-rich-50000-fixed-teams.SC2Map"
RUNTIME_MAP_FILE = PROJECT_ROOT / "runtime" / "maps" / "campaign-ai-production-probe.SC2Map"
PORT = 14117
STEP = 448
MAX_LOOPS = 33_600


def config() -> CustomLauncherConfig:
    players = {
        1: ("human", "Terran", "bio_tank"),
        2: ("custom_ai", "Zerg", "ultra_ling_bane"),
        8: ("custom_ai", "Terran", "mech_macro"),
        9: ("custom_ai", "Terran", "bio"),
    }
    slots = []
    for slot_id in range(1, 15):
        controller, race, build = players.get(slot_id, ("empty", "Random", "random_ground"))
        slots.append(SlotConfig(slot_id, controller, 1 if slot_id <= 7 else 2, race, build))
    result = CustomLauncherConfig(1, tuple(slots))
    result.validate()
    return result


async def main() -> None:
    probe = config()
    build_runtime_map(
        PROJECT_ROOT, BASE_MAP_FILE, RUNTIME_MAP_FILE, probe,
        strategy_bridge=True, campaign_units_pilot=True,
        active_config_file=RUNTIME_MAP_FILE.with_suffix(".json"),
    )
    process = launch_sc2(discover_sc2_executable(), PORT, 0)
    connection: Sc2Connection | None = None
    try:
        connection = await Sc2Connection.open(PORT)
        await connection.create_game_with_setups(
            RUNTIME_MAP_FILE.name, RUNTIME_MAP_FILE.read_bytes(), player_setups(probe), realtime=False,
        )
        joined = await connection.join_game(RACE_VALUES[probe.human.race], "Campaign AI Production", None)
        print(f"joined_player={joined}")
        info_request = sc_pb.Request()
        info_request.game_info.CopyFrom(sc_pb.RequestGameInfo())
        info = (await connection.request(info_request)).game_info
        print(
            "players="
            + repr([
                (item.player_id, item.type, item.race_requested, item.race_actual)
                for item in info.player_info
            ])
        )
        request = sc_pb.Request()
        request.data.CopyFrom(sc_pb.RequestData(unit_type_id=True))
        data = (await connection.request(request)).data
        ids = {unit.name: unit.unit_id for unit in data.units}
        names = {unit.unit_id: unit.name for unit in data.units}
        expected = {
            "aberration": (2, ids["SC2TeamAberration"]),
            "goliath": (3, ids["SC2TeamGoliath"]),
            "predator": (3, ids["SC2TeamPredator"]),
            "medic": (4, ids["SC2TeamMedic"]),
        }
        seen = {name: False for name in expected}
        seen["raptor"] = False
        last_bucket = -1
        while True:
            await connection.step(STEP)
            observation = await connection.observation(disable_fog=True)
            loop = observation.observation.game_loop
            rows = observation.observation.raw_data.units
            counts = Counter((unit.owner, unit.unit_type) for unit in rows)
            for name, (owner, unit_type) in expected.items():
                if counts[(owner, unit_type)] > 0:
                    seen[name] = True
            if any(
                unit.owner == 2 and unit.unit_type == 105 and unit.health_max >= 44.5
                for unit in rows
            ):
                seen["raptor"] = True
            seconds = loop / 22.4
            bucket = int(seconds // 100)
            if bucket != last_bucket:
                last_bucket = bucket
                print(
                    f"t={seconds:.0f}s "
                    + " ".join(
                        f"{name}={counts[(owner, unit_type)]}"
                        for name, (owner, unit_type) in expected.items()
                    )
                    + f" raptor={seen['raptor']}"
                )
            if all(seen.values()):
                print("CAMPAIGN_AI_PRODUCTION=PASS")
                return
            if observation.player_result:
                raise RuntimeError(f"CAMPAIGN_AI_PRODUCTION=FAIL game ended; seen={seen}")
            if loop >= MAX_LOOPS:
                for owner in (2, 3, 4):
                    summary = Counter(
                        names.get(unit.unit_type, str(unit.unit_type))
                        for unit in rows if unit.owner == owner
                    )
                    useful = {
                        name: count for name, count in summary.items()
                        if name in {
                            "Larva", "SpawningPool", "Lair", "Hive", "InfestationPit",
                            "Factory", "FactoryTechLab", "Armory", "Barracks",
                            "BarracksTechLab", "SC2TeamAberration", "SC2TeamGoliath",
                            "SC2TeamPredator", "SC2TeamMedic",
                        }
                    }
                    print(f"owner={owner} infrastructure={useful} top={summary.most_common(25)}")
                producers = [
                    unit for unit in rows
                    if unit.owner in (2, 3, 4)
                    and names.get(unit.unit_type) in {"Larva", "SpawningPool", "Factory", "Barracks"}
                ][:20]
                if producers:
                    query = sc_pb.Request()
                    query.query.ignore_resource_requirements = True
                    for producer in producers:
                        query.query.abilities.add(unit_tag=producer.tag)
                    available = (await connection.request(query)).query.abilities
                    for producer, result in zip(producers, available, strict=True):
                        print(
                            f"available owner={producer.owner} type={names.get(producer.unit_type)} "
                            f"abilities={[ability.ability_id for ability in result.abilities]}"
                        )
                raise RuntimeError(f"CAMPAIGN_AI_PRODUCTION=FAIL timeout; seen={seen}")
    finally:
        if connection is not None:
            await connection.quit()
            await connection.close()
        stop_process(process)


if __name__ == "__main__":
    asyncio.run(main())
