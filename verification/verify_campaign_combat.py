from __future__ import annotations

import asyncio
from math import hypot
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


BASE_MAP_FILE = PROJECT_ROOT / "maps" / "generated" / "europe-melee-2-7v7-rich-50000-fixed-teams.SC2Map"
RUNTIME_MAP_FILE = PROJECT_ROOT / "runtime" / "maps" / "campaign-combat-probe.SC2Map"
PORT = 14125
ATTACK_ABILITY_ID = 23


def config() -> CustomLauncherConfig:
    slots = []
    for slot_id in range(1, 15):
        if slot_id == 1:
            values = ("human", "Terran", "bio_tank")
        elif slot_id == 8:
            values = ("custom_ai", "Terran", "mech_macro")
        else:
            values = ("empty", "Random", "random_ground")
        slots.append(SlotConfig(slot_id, values[0], 1 if slot_id <= 7 else 2, values[1], values[2]))
    result = CustomLauncherConfig(1, tuple(slots))
    result.validate()
    return result


def nearest(units, unit_type: int, owner: int, position: tuple[float, float]):
    candidates = [unit for unit in units if unit.unit_type == unit_type and unit.owner == owner]
    return min(candidates, key=lambda unit: hypot(unit.pos.x - position[0], unit.pos.y - position[1]))


async def main() -> None:
    probe = config()
    build_runtime_map(
        PROJECT_ROOT,
        BASE_MAP_FILE,
        RUNTIME_MAP_FILE,
        probe,
        strategy_bridge=False,
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
            player_setups(probe),
            realtime=False,
        )
        await connection.join_game(RACE_VALUES[probe.human.race], "Campaign Combat Verification", None)
        request = sc_pb.Request()
        request.data.CopyFrom(sc_pb.RequestData(unit_type_id=True))
        data = (await connection.request(request)).data
        ids = {unit.name: unit.unit_id for unit in data.units}
        await connection.step(90)
        initial = await connection.observation(disable_fog=True)
        workers = [unit for unit in initial.observation.raw_data.units if unit.owner == 1 and unit.unit_type == 45]
        center = (
            sum(unit.pos.x for unit in workers) / len(workers),
            sum(unit.pos.y for unit in workers) / len(workers),
        )

        attackers = (
            "HotSTorrasque",
            "SC2TeamAberration",
            "SC2TeamGoliath",
            "SC2TeamPredator",
        )
        attacker_offsets = ((10, 8), (10, -8), (22, 8), (22, -8))
        for index, name in enumerate(attackers):
            offset_x, offset_y = attacker_offsets[index]
            point = (center[0] + offset_x, center[1] + offset_y)
            await connection.debug_create_units(ids[name], 1, point[0], point[1], 1)
            await connection.debug_create_units(ids["Marauder"], 2, point[0] + 3, point[1], 1)
            await connection.step(2)
            before = await connection.observation(disable_fog=True)
            attacker = nearest(before.observation.raw_data.units, ids[name], 1, point)
            target = nearest(before.observation.raw_data.units, ids["Marauder"], 2, (point[0] + 3, point[1]))
            life_before = target.health
            result = await connection.raw_unit_command(
                [attacker.tag], ATTACK_ABILITY_ID, target_unit_tag=target.tag
            )
            if result != (1,):
                raise RuntimeError(f"{name}: attack command rejected: {result}")
            await connection.step(224)
            after = await connection.observation(disable_fog=True)
            remaining = next((unit for unit in after.observation.raw_data.units if unit.tag == target.tag), None)
            life_after = 0.0 if remaining is None else remaining.health
            if life_after >= life_before:
                raise RuntimeError(f"{name}: no damage ({life_before}->{life_after})")
            print(f"CAMPAIGN_COMBAT_{name.upper()}=PASS damage={life_before - life_after:g}")

        air_point = (center[0] + 46, center[1] - 2)
        await connection.debug_create_units(ids["SC2TeamGoliath"], 1, air_point[0], air_point[1], 1)
        await connection.debug_create_units(ids["VikingFighter"], 2, air_point[0] + 3, air_point[1], 1)
        await connection.step(2)
        before_air = await connection.observation(disable_fog=True)
        goliath = nearest(before_air.observation.raw_data.units, ids["SC2TeamGoliath"], 1, air_point)
        air_target = nearest(before_air.observation.raw_data.units, ids["VikingFighter"], 2, (air_point[0] + 3, air_point[1]))
        air_life_before = air_target.health
        result = await connection.raw_unit_command(
            [goliath.tag], ATTACK_ABILITY_ID, target_unit_tag=air_target.tag
        )
        if result != (1,):
            raise RuntimeError(f"SC2TeamGoliath: anti-air command rejected: {result}")
        await connection.step(224)
        after_air = await connection.observation(disable_fog=True)
        air_remaining = next((unit for unit in after_air.observation.raw_data.units if unit.tag == air_target.tag), None)
        air_life_after = 0.0 if air_remaining is None else air_remaining.health
        if air_life_after >= air_life_before:
            raise RuntimeError("SC2TeamGoliath: no anti-air damage")
        print(f"CAMPAIGN_COMBAT_GOLIATH_AIR=PASS damage={air_life_before - air_life_after:g}")

        medic_point = (center[0] + 10, center[1] - 12)
        await connection.debug_create_units(ids["SC2TeamMedic"], 1, medic_point[0], medic_point[1], 1)
        await connection.debug_create_units(ids["Marine"], 1, medic_point[0] + 1, medic_point[1], 1)
        await connection.step(2)
        before = await connection.observation(disable_fog=True)
        medic = nearest(before.observation.raw_data.units, ids["SC2TeamMedic"], 1, medic_point)
        marine = nearest(before.observation.raw_data.units, ids["Marine"], 1, (medic_point[0] + 1, medic_point[1]))
        await connection.debug_set_unit_life(marine.tag, 10)
        await connection.step(2)

        query = sc_pb.Request()
        query.query.ignore_resource_requirements = True
        query.query.abilities.add(unit_tag=medic.tag)
        abilities = (await connection.request(query)).query.abilities[0].abilities
        heal_ids = [ability.ability_id for ability in abilities if ability.ability_id != 0]
        # SC2TeamMedic parents from campaign Medic and uses its own autocast heal,
        # so this no longer exercises the Medivac graft the Marine parent needed.
        # Give it enough stepped time to acquire the adjacent biological target.
        await connection.step(224)
        healed = await connection.observation(disable_fog=True)
        healed_marine = next(unit for unit in healed.observation.raw_data.units if unit.tag == marine.tag)
        if healed_marine.health <= 10:
            raise RuntimeError(f"SC2TeamMedic: autocast heal failed; abilities={heal_ids}")
        print(f"CAMPAIGN_COMBAT_MEDIC=PASS life=10->{healed_marine.health:g}")
        print("CAMPAIGN_COMBAT=PASS")
    finally:
        if connection is not None:
            await connection.quit()
            await connection.close()
        stop_process(process)


if __name__ == "__main__":
    asyncio.run(main())
