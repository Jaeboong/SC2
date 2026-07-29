from __future__ import annotations

import asyncio
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
    / "map"
    / "source"
    / "europe-melee-2-7v7-rich-50000-fixed-teams.SC2Map"
)
RUNTIME_MAP_FILE = PROJECT_ROOT / "runtime" / "maps" / "torrasque-pilot-probe.SC2Map"
PORT = 14114
HATCHERY = 86


def probe_config() -> CustomLauncherConfig:
    slots = []
    for slot_id in range(1, 15):
        if slot_id == 1:
            controller, race, build = "human", "Zerg", "ultra_ling_bane"
        elif slot_id == 8:
            controller, race, build = "custom_ai", "Terran", "bio"
        else:
            controller, race, build = "empty", "Random", "random_ground"
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


def owned_units(observation, owner: int = 1):
    return [
        unit
        for unit in observation.observation.raw_data.units
        if unit.owner == owner
    ]


def unit_summary(observation, owner: int = 1) -> list[tuple[int, int, float, float]]:
    return [
        (unit.unit_type, unit.tag, round(unit.health, 1), round(unit.build_progress, 2))
        for unit in owned_units(observation, owner)
    ]


async def main() -> None:
    config = probe_config()
    build_runtime_map(
        PROJECT_ROOT,
        BASE_MAP_FILE,
        RUNTIME_MAP_FILE,
        config,
        campaign_units_pilot=True,
        campaign_units_probe_damage=True,
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
            "Torrasque Pilot Verification",
            None,
        )
        data_request = sc_pb.Request()
        data_request.data.CopyFrom(
            sc_pb.RequestData(
                ability_id=True,
                unit_type_id=True,
                buff_id=True,
                effect_id=True,
            )
        )
        game_data = (await connection.request(data_request)).data
        print(
            "campaign_data="
            f"buffs={[item.name for item in game_data.buffs if 'Torrasque' in item.name]} "
            f"units={[item.name for item in game_data.units if 'Torrasque' in item.name]} "
            f"abilities={[(item.ability_id, item.link_name, item.button_name, item.friendly_name) for item in game_data.abilities if 'Torrasque' in item.link_name]}"
        )
        unit_id_by_name = {item.name: item.unit_id for item in game_data.units}
        transition_types = {
            unit_id_by_name["TorrasqueCorpse"],
            unit_id_by_name["TorrasqueChrysalis"],
        }
        print(
            "zerg_300_200_6="
            f"{[(item.unit_id, item.name, item.available, item.ability_id) for item in game_data.units if item.race == 2 and item.mineral_cost == 300 and item.vespene_cost == 200 and item.food_required == 6]}"
        )
        await connection.step(1)
        created = await connection.observation(disable_fog=True)
        torrasque_type = unit_id_by_name["HotSTorrasque"]
        torrasque_rows = [
            unit for unit in owned_units(created) if unit.unit_type == torrasque_type
        ]
        if len(torrasque_rows) != 1:
            raise RuntimeError(
                f"SC2TEAM_TORRASQUE_CREATE=FAIL candidates={unit_summary(created)}"
            )
        ultralisk = torrasque_rows[0]
        created_food = created.observation.player_common.food_used
        print(
            f"created tag={ultralisk.tag} health={ultralisk.health} "
            f"food_used={created_food} buffs={list(ultralisk.buff_ids)}"
        )

        await connection.debug_set_unit_life(ultralisk.tag, 1)

        transition_seen = False
        corpse = None
        transition_timeline = []
        for _ in range(10):
            await connection.step(8)
            checkpoint = await connection.observation(disable_fog=True)
            relevant = [
                unit
                for unit in owned_units(checkpoint)
                if unit.unit_type == torrasque_type or unit.unit_type in transition_types
            ]
            transition_timeline.append(
                (
                    checkpoint.observation.game_loop,
                    [(unit.unit_type, unit.tag, round(unit.health, 1)) for unit in relevant],
                    checkpoint.observation.player_common.food_used,
                )
            )
            if any(unit.unit_type in transition_types for unit in relevant):
                transition_seen = True
                corpse = checkpoint
                break
        if corpse is None:
            corpse = checkpoint
        corpse_units = [
            unit for unit in owned_units(corpse) if unit.unit_type in transition_types
        ]
        corpse_food = corpse.observation.player_common.food_used
        print(
            f"transition_timeline={transition_timeline}"
        )
        if not corpse_units:
            raise RuntimeError("TORRASQUE_REVIVE=FAIL unit was destroyed instead of morphing")
        if not transition_seen:
            raise RuntimeError("TORRASQUE_REVIVE=FAIL no corpse/chrysalis transition observed")

        await connection.step(260)
        revived = await connection.observation(disable_fog=True)
        revived_unit = next(
            (unit for unit in owned_units(revived) if unit.unit_type == torrasque_type),
            None,
        )
        revived_food = revived.observation.player_common.food_used
        print(
            f"after_revive loop={revived.observation.game_loop} food_used={revived_food} "
            f"units={unit_summary(revived)}"
        )
        if revived_unit is None or revived_unit.unit_type != torrasque_type:
            actual = None if revived_unit is None else revived_unit.unit_type
            raise RuntimeError(
                f"TORRASQUE_REVIVE=FAIL expected Torrasque type {torrasque_type}, got {actual}"
            )
        if created_food != 6 or corpse_food != 6 or revived_food != 6:
            raise RuntimeError(
                "TORRASQUE_SUPPLY_STABILITY=FAIL "
                f"created={created_food}, corpse={corpse_food}, revived={revived_food}"
            )
        if revived_unit.health < revived_unit.health_max * 0.95:
            raise RuntimeError(
                f"TORRASQUE_REVIVE_HEALTH=FAIL {revived_unit.health}/{revived_unit.health_max}"
            )
        print("TORRASQUE_REVIVE=PASS")
        print("TORRASQUE_SUPPLY_STABILITY=PASS")
    finally:
        if connection is not None:
            await connection.quit()
            await connection.close()
        stop_process(process)


if __name__ == "__main__":
    asyncio.run(main())
