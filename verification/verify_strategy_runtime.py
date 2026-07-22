from __future__ import annotations

import asyncio
import json
import os
from collections import Counter
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from s2clientprotocol import sc2api_pb2 as sc_pb

from sc2team.custom_config import CustomLauncherConfig
from sc2team.custom_runtime import (
    RACE_VALUES,
    build_runtime_map,
    player_setups,
    runtime_player_id,
)
from sc2team.process import discover_sc2_executable, launch_sc2, stop_process
from sc2team.protocol import Sc2Connection
from sc2team.strategy_controller import StrategyController


BASE_MAP_FILE = PROJECT_ROOT / "maps" / "generated" / "europe-melee-2-7v7-rich-50000-fixed-teams.SC2Map"
RUNTIME_MAP_FILE = PROJECT_ROOT / "runtime" / "maps" / "strategy-runtime-probe.SC2Map"
SETTINGS_FILE = Path(
    os.environ.get(
        "SC2TEAM_SETTINGS_FILE",
        PROJECT_ROOT / "runtime" / "custom_ai_settings.json",
    )
)

MARAUDER_UNIT_TYPE = 51
TERRAN_PRODUCTION_TYPES = {19, 20, 21, 27, 28}  # Depot, Refinery, Barracks, Factory, Starport
TERRAN_TOWN_HALL_TYPES = {18, 130, 132}  # Command Center, Planetary, Orbital


def units(observation, owner: int, unit_types: set[int] | None = None):
    rows = [
        unit
        for unit in observation.observation.raw_data.units
        if unit.owner == owner
    ]
    if unit_types is not None:
        rows = [unit for unit in rows if unit.unit_type in unit_types]
    return rows


async def main() -> None:
    config = CustomLauncherConfig.from_dict(
        json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    )
    terran_ai = next(
        slot for slot in config.custom_ai_slots if slot.race == "Terran"
    )
    target_player = runtime_player_id(config, terran_ai.slot)
    build_runtime_map(
        PROJECT_ROOT,
        BASE_MAP_FILE,
        RUNTIME_MAP_FILE,
        config,
        strategy_bridge=True,
        campaign_units_pilot=True,
        active_config_file=RUNTIME_MAP_FILE.with_suffix(".json"),
    )

    process = launch_sc2(discover_sc2_executable(), 14112, 0)
    connection: Sc2Connection | None = None
    try:
        connection = await Sc2Connection.open(14112)
        await connection.create_game_with_setups(
            RUNTIME_MAP_FILE.name,
            RUNTIME_MAP_FILE.read_bytes(),
            player_setups(config),
            realtime=False,
        )
        await connection.join_game(
            RACE_VALUES[config.human.race],
            "Strategy Runtime Verification",
            None,
        )
        await connection.step(90)
        before = await connection.observation(disable_fog=True)
        data_request = sc_pb.Request()
        data_request.data.CopyFrom(sc_pb.RequestData(unit_type_id=True))
        game_data = (await connection.request(data_request)).data
        medic_type = next(
            unit.unit_id for unit in game_data.units
            if unit.name == "SC2TeamMedic"
        )
        controller = StrategyController(connection, config)
        controller.initialize(before)

        target_units = units(before, target_player)
        center_x = sum(unit.pos.x for unit in target_units) / len(target_units)
        center_y = sum(unit.pos.y for unit in target_units) / len(target_units)
        old_marauders = {unit.tag for unit in units(before, target_player, {MARAUDER_UNIT_TYPE})}
        old_medics = {unit.tag for unit in units(before, target_player, {medic_type})}
        await connection.debug_create_units(
            MARAUDER_UNIT_TYPE,
            target_player,
            center_x,
            center_y,
            1,
        )
        await connection.debug_create_units(
            medic_type,
            target_player,
            center_x + 2,
            center_y,
            1,
        )
        await connection.step(2)
        created = await connection.observation(disable_fog=True)
        marauder = next(
            unit
            for unit in units(created, target_player, {MARAUDER_UNIT_TYPE})
            if unit.tag not in old_marauders
        )
        medic = next(
            unit
            for unit in units(created, target_player, {medic_type})
            if unit.tag not in old_medics
        )
        start = (marauder.pos.x, marauder.pos.y)
        medic_start = (medic.pos.x, medic.pos.y)

        await controller.command_ground_attack(terran_ai.slot)
        await connection.step(224)
        movement_observation = await connection.observation(disable_fog=True)
        moved = next(
            (
                unit
                for unit in units(movement_observation, target_player)
                if unit.tag == marauder.tag
            ),
            None,
        )
        moved_medic = next(
            (
                unit
                for unit in units(movement_observation, target_player)
                if unit.tag == medic.tag
            ),
            None,
        )
        distance_sq = (
            (moved.pos.x - start[0]) ** 2 + (moved.pos.y - start[1]) ** 2
            if moved is not None
            else float("inf")
        )
        medic_distance_sq = (
            (moved_medic.pos.x - medic_start[0]) ** 2
            + (moved_medic.pos.y - medic_start[1]) ** 2
            if moved_medic is not None
            else float("inf")
        )
        await connection.step(2016)
        after = await connection.observation(disable_fog=True)
        production = units(after, target_player, TERRAN_PRODUCTION_TYPES)
        town_halls = units(after, target_player, TERRAN_TOWN_HALL_TYPES)
        type_counts = Counter(unit.unit_type for unit in units(after, target_player))

        end_text = (
            f"({moved.pos.x:.1f},{moved.pos.y:.1f})"
            if moved is not None
            else "removed/dead"
        )
        print(
            f"target=P{terran_ai.slot}->runtime P{target_player} "
            f"marauder_start={start} marauder_end={end_text}"
        )
        print(f"distance_sq={distance_sq:.1f}")
        print(f"medic_distance_sq={medic_distance_sq:.1f}")
        print(
            "production="
            f"{[(unit.unit_type, round(unit.build_progress, 2)) for unit in production]}"
        )
        print(
            "town_halls="
            f"{[(unit.unit_type, round(unit.build_progress, 2)) for unit in town_halls]}"
        )
        print(f"all_unit_type_counts={dict(sorted(type_counts.items()))}")
        print(f"game_loop={after.observation.game_loop}")
        if distance_sq <= 25.0:
            raise RuntimeError("STRATEGY_GROUND_ATTACK_TEST=FAIL")
        if medic_distance_sq <= 25.0:
            raise RuntimeError("STRATEGY_MEDIC_FOLLOW_TEST=FAIL")
        # The first expansion ignores production prerequisites but now waits
        # until the AI actually has 400 minerals before dispatching its worker.
        # At this checkpoint, either a production structure or the second town
        # hall proves that Blizzard's economy AI is running.
        if not production and len(town_halls) < 2:
            raise RuntimeError("BUILTIN_ECONOMY_AI_TEST=FAIL")
        print("STRATEGY_RUNTIME_TEST=PASS")
        print("STRATEGY_MEDIC_FOLLOW_TEST=PASS")
    finally:
        if connection is not None:
            await connection.quit()
            await connection.close()
        stop_process(process)


if __name__ == "__main__":
    asyncio.run(main())
