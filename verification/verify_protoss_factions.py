from __future__ import annotations

import asyncio
from collections import Counter
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
FACTIONS = ("Aiur", "Nerazim", "Purifier", "Taldarim")


def nearest(units, unit_type: int, owner: int, position: tuple[float, float]):
    candidates = [unit for unit in units if unit.unit_type == unit_type and unit.owner == owner]
    return min(candidates, key=lambda unit: hypot(unit.pos.x - position[0], unit.pos.y - position[1]))


def config(faction: str) -> CustomLauncherConfig:
    slots = []
    for slot_id in range(1, 15):
        if slot_id == 1:
            values = ("human", "Protoss", "gateway")
        elif slot_id == 8:
            values = ("custom_ai", "Terran", "mech_macro")
        else:
            values = ("empty", "Random", "random_ground")
        slots.append(
            SlotConfig(
                slot_id,
                values[0],
                1 if slot_id <= 7 else 2,
                values[1],
                values[2],
            )
        )
    result = CustomLauncherConfig(1, tuple(slots), protoss_faction=faction)
    result.validate()
    return result


async def verify_faction(faction: str, offset: int) -> None:
    probe = config(faction)
    runtime_map = PROJECT_ROOT / "runtime" / "maps" / f"protoss-{faction.lower()}-probe.SC2Map"
    build_runtime_map(
        PROJECT_ROOT,
        BASE_MAP_FILE,
        runtime_map,
        probe,
        strategy_bridge=True,
        campaign_units_pilot=True,
        active_config_file=runtime_map.with_suffix(".json"),
    )
    process = launch_sc2(discover_sc2_executable(), 14120 + offset, 0)
    connection: Sc2Connection | None = None
    try:
        connection = await Sc2Connection.open(14120 + offset)
        await connection.create_game_with_setups(
            runtime_map.name,
            runtime_map.read_bytes(),
            player_setups(probe),
            realtime=False,
        )
        joined = await connection.join_game(
            RACE_VALUES[probe.human.race],
            f"{faction} Faction Verification",
            None,
        )
        if joined != 1:
            raise RuntimeError(f"{faction}: participant mapped to P{joined}")
        await connection.step(90)
        observation = await connection.observation(disable_fog=True)
        counts = Counter(
            unit.unit_type
            for unit in observation.observation.raw_data.units
            if unit.owner == 1
        )
        if counts[59] != 1 or counts[84] < 8:
            raise RuntimeError(
                f"{faction}: normal Protoss start missing, nexus={counts[59]} probes={counts[84]}"
            )
        print(f"PROTOSS_FACTION_{faction.upper()}=PASS nexus={counts[59]} probes={counts[84]}")
        if faction == "Aiur":
            request = sc_pb.Request()
            request.data.CopyFrom(sc_pb.RequestData(unit_type_id=True, ability_id=True))
            data = (await connection.request(request)).data
            ids = {unit.name: unit.unit_id for unit in data.units}
            workers = [
                unit
                for unit in observation.observation.raw_data.units
                if unit.owner == 1 and unit.unit_type == ids["Probe"]
            ]
            center = (
                sum(unit.pos.x for unit in workers) / len(workers),
                sum(unit.pos.y for unit in workers) / len(workers),
            )
            dragoon_point = (center[0] + 12, center[1] + 8)
            await connection.debug_create_units(
                ids["Stalker"], 1, dragoon_point[0], dragoon_point[1], 1
            )
            await connection.step(2)
            created = await connection.observation(disable_fog=True)
            dragoon = nearest(
                created.observation.raw_data.units,
                ids["Stalker"],
                1,
                dragoon_point,
            )
            if dragoon.health_max != 120 or dragoon.shield_max != 80:
                raise RuntimeError(
                    "Aiur Dragoon replacement stats missing: "
                    f"life={dragoon.health_max} shields={dragoon.shield_max}"
                )
            print(
                "PROTOSS_AIUR_DRAGOON=PASS "
                f"life={dragoon.health_max:g} shields={dragoon.shield_max:g}"
            )
            move_ability = next(
                ability.ability_id
                for ability in data.abilities
                if ability.link_name.lower() == "move"
                and ability.button_name == "Move"
            )
            attack_ability = next(
                ability.ability_id
                for ability in data.abilities
                if ability.link_name.lower() == "attack"
                and ability.button_name == "Attack"
            )
            move_target = (dragoon_point[0] + 4, dragoon_point[1])
            move_result = await connection.raw_unit_command(
                [dragoon.tag], move_ability, target_position=move_target
            )
            if move_result and any(code != 1 for code in move_result):
                raise RuntimeError(f"Aiur Dragoon move command rejected: {move_result}")
            await connection.step(40)
            moved_observation = await connection.observation(disable_fog=True)
            moved_dragoon = next(
                unit
                for unit in moved_observation.observation.raw_data.units
                if unit.tag == dragoon.tag
            )
            moved_distance = hypot(
                moved_dragoon.pos.x - dragoon.pos.x,
                moved_dragoon.pos.y - dragoon.pos.y,
            )
            if moved_distance < 1.5:
                raise RuntimeError(
                    f"Aiur Dragoon mover failed: distance={moved_distance:g}"
                )
            attack_target_point = (moved_dragoon.pos.x + 5, moved_dragoon.pos.y)
            await connection.debug_create_units(
                ids["Marauder"], 2, attack_target_point[0], attack_target_point[1], 1
            )
            await connection.step(2)
            attack_before = await connection.observation(disable_fog=True)
            attack_target = nearest(
                attack_before.observation.raw_data.units,
                ids["Marauder"],
                2,
                attack_target_point,
            )
            ability_query = sc_pb.Request()
            ability_query.query.abilities.add(unit_tag=moved_dragoon.tag)
            available = (await connection.request(ability_query)).query.abilities[0].abilities
            available_ids = {item.ability_id for item in available}
            if attack_ability not in available_ids:
                raise RuntimeError("Aiur Dragoon attack command is unavailable")
            attack_result = await connection.raw_unit_command(
                [moved_dragoon.tag],
                attack_ability,
                target_position=attack_target_point,
            )
            if attack_result and any(code != 1 for code in attack_result):
                raise RuntimeError(f"Aiur Dragoon attack command rejected: {attack_result}")
            await connection.step(120)
            attack_after = await connection.observation(disable_fog=True)
            remaining_target = next(
                (
                    unit
                    for unit in attack_after.observation.raw_data.units
                    if unit.tag == attack_target.tag
                ),
                None,
            )
            remaining_life = 0 if remaining_target is None else remaining_target.health
            attack_damage = attack_target.health - remaining_life
            if attack_damage <= 0:
                raise RuntimeError("Aiur Dragoon weapon did not damage its target")
            print(
                "PROTOSS_AIUR_DRAGOON_MOVE_ATTACK=PASS "
                f"distance={moved_distance:g} damage={attack_damage:g}"
            )

            zealot_point = (center[0] + 24, center[1] + 8)
            await connection.debug_create_units(
                ids["Zealot"], 1, zealot_point[0], zealot_point[1], 1
            )
            target_points = (
                (zealot_point[0] + 0.7, zealot_point[1]),
                (zealot_point[0] - 0.7, zealot_point[1]),
                (zealot_point[0], zealot_point[1] + 0.7),
            )
            for point in target_points:
                await connection.debug_create_units(ids["Marauder"], 2, point[0], point[1], 1)
            await connection.step(2)
            before = await connection.observation(disable_fog=True)
            targets = [
                nearest(before.observation.raw_data.units, ids["Marauder"], 2, point)
                for point in target_points
            ]
            before_life = {unit.tag: unit.health for unit in targets}
            await connection.step(112)
            after = await connection.observation(disable_fog=True)
            after_by_tag = {unit.tag: unit for unit in after.observation.raw_data.units}
            damaged = 0
            total_damage = 0.0
            for tag, life in before_life.items():
                remaining = after_by_tag.get(tag)
                current = 0.0 if remaining is None else remaining.health
                if current < life:
                    damaged += 1
                    total_damage += life - current
            if damaged < 2:
                raise RuntimeError(
                    "Aiur Zealot Whirlwind did not autocast against the cluster: "
                    f"damaged={damaged}, total_damage={total_damage:g}"
                )
            print(
                "PROTOSS_AIUR_WHIRLWIND_AUTOCAST=PASS "
                f"damaged_targets={damaged} total_damage={total_damage:g}"
            )
        if faction in {"Nerazim", "Purifier"}:
            request = sc_pb.Request()
            request.data.CopyFrom(
                sc_pb.RequestData(unit_type_id=True, ability_id=True, buff_id=True)
            )
            data = (await connection.request(request)).data
            ids = {unit.name: unit.unit_id for unit in data.units}
            buffs = {buff.name: buff.buff_id for buff in data.buffs}
            blink_link = "BlinkShieldRestore" if faction == "Nerazim" else "BlinkMultiple"
            blink = next(
                ability.ability_id
                for ability in data.abilities
                if ability.link_name == blink_link
            )
            workers = [
                unit
                for unit in observation.observation.raw_data.units
                if unit.owner == 1 and unit.unit_type == ids["Probe"]
            ]
            center = (
                sum(unit.pos.x for unit in workers) / len(workers),
                sum(unit.pos.y for unit in workers) / len(workers),
            )
            point = (center[0] + 12, center[1] - 8)
            await connection.debug_create_units(ids["Stalker"], 1, point[0], point[1], 1)
            await connection.step(2)
            created = await connection.observation(disable_fog=True)
            stalker = nearest(created.observation.raw_data.units, ids["Stalker"], 1, point)
            if faction == "Nerazim":
                await connection.debug_set_unit_shields(stalker.tag, 1)
                await connection.step(2)
                result = await connection.raw_unit_command(
                    [stalker.tag], blink, target_position=(point[0] + 5, point[1])
                )
                if result != (1,):
                    raise RuntimeError(f"Nerazim Blink command rejected: {result}")
                await connection.step(45)
                after = await connection.observation(disable_fog=True)
                restored = next(unit for unit in after.observation.raw_data.units if unit.tag == stalker.tag)
                if restored.shield <= 1:
                    raise RuntimeError(
                        f"Nerazim Blink shield restoration failed: shield={restored.shield}"
                    )
                print(
                    "PROTOSS_NERAZIM_BLINK_RESTORE=PASS "
                    f"shield=1->{restored.shield:g}"
                )
                charge_point = (center[0] + 24, center[1] - 8)
                await connection.debug_create_units(
                    ids["Zealot"], 1, charge_point[0], charge_point[1], 1
                )
                await connection.debug_create_units(
                    ids["Marauder"], 2, charge_point[0] + 6, charge_point[1], 1
                )
                await connection.step(2)
                charge_before = await connection.observation(disable_fog=True)
                centurion = nearest(
                    charge_before.observation.raw_data.units,
                    ids["Zealot"],
                    1,
                    charge_point,
                )
                charge_target = nearest(
                    charge_before.observation.raw_data.units,
                    ids["Marauder"],
                    2,
                    (charge_point[0] + 6, charge_point[1]),
                )
                result = await connection.raw_unit_command(
                    [centurion.tag], 23, target_unit_tag=charge_target.tag
                )
                if result != (1,):
                    raise RuntimeError(f"Nerazim Centurion attack rejected: {result}")
                await connection.step(12)
                charge_after = await connection.observation(disable_fog=True)
                moved_centurion = next(
                    unit
                    for unit in charge_after.observation.raw_data.units
                    if unit.tag == centurion.tag
                )
                charge_distance = hypot(
                    moved_centurion.pos.x - centurion.pos.x,
                    moved_centurion.pos.y - centurion.pos.y,
                )
                if charge_distance < 2.5:
                    raise RuntimeError(
                        f"Nerazim Shadow Charge did not autocast: distance={charge_distance:g}"
                    )
                print(
                    "PROTOSS_NERAZIM_SHADOW_CHARGE_AUTOCAST=PASS "
                    f"distance={charge_distance:g}"
                )
                cannon_point = (center[0] + 36, center[1] - 8)
                await connection.debug_create_units(
                    ids["Immortal"], 1, cannon_point[0], cannon_point[1], 1
                )
                await connection.debug_create_units(
                    ids["Archon"], 1, cannon_point[0] + 4, cannon_point[1], 1
                )
                await connection.step(2)
                cannon_before = await connection.observation(disable_fog=True)
                immortal = nearest(
                    cannon_before.observation.raw_data.units,
                    ids["Immortal"], 1, cannon_point,
                )
                dark_archon = nearest(
                    cannon_before.observation.raw_data.units,
                    ids["Archon"], 1, (cannon_point[0] + 4, cannon_point[1]),
                )
                required_by_tag = {
                    immortal.tag: {"ImmortalShakurasShadowCannon"},
                    dark_archon.tag: {"DarkArchonMindControl", "DarkArchonConfusion"},
                }
                for unit_tag, required in required_by_tag.items():
                    query = sc_pb.Request()
                    query.query.ignore_resource_requirements = True
                    query.query.abilities.add(unit_tag=unit_tag)
                    available = (await connection.request(query)).query.abilities[0].abilities
                    available_ids = {item.ability_id for item in available}
                    available_links = {
                        ability.link_name
                        for ability in data.abilities
                        if ability.ability_id in available_ids
                    }
                    if not required <= available_links:
                        raise RuntimeError(
                            f"Nerazim pure abilities missing: required={required} "
                            f"available={available_links}"
                        )
                print("PROTOSS_NERAZIM_PURE_MANUAL_ABILITIES=PASS shadow_cannon mind_control confusion")
            else:
                current = point
                for cast in range(3):
                    destination = (current[0] + 2, current[1])
                    result = await connection.raw_unit_command(
                        [stalker.tag], blink, target_position=destination
                    )
                    if result != (1,):
                        raise RuntimeError(
                            f"Purifier Blink charge {cast + 1} rejected: {result}"
                        )
                    await connection.step(2)
                    current = destination
                after = await connection.observation(disable_fog=True)
                moved = next(unit for unit in after.observation.raw_data.units if unit.tag == stalker.tag)
                distance = hypot(moved.pos.x - point[0], moved.pos.y - point[1])
                if distance < 5:
                    raise RuntimeError(
                        f"Purifier multi-Blink movement too small: {distance:g}"
                    )
                print(
                    "PROTOSS_PURIFIER_MULTI_BLINK=PASS "
                    f"casts=3 distance={distance:g}"
                )
                sentinel_point = (center[0] + 24, center[1] - 8)
                await connection.debug_create_units(
                    ids["Zealot"], 1, sentinel_point[0], sentinel_point[1], 1
                )
                await connection.debug_create_units(
                    ids["Sentry"], 1, sentinel_point[0] + 3, sentinel_point[1], 1
                )
                await connection.step(2)
                revive_before = await connection.observation(disable_fog=True)
                sentinel = nearest(
                    revive_before.observation.raw_data.units,
                    ids["Zealot"],
                    1,
                    sentinel_point,
                )
                energizer = nearest(
                    revive_before.observation.raw_data.units,
                    ids["Sentry"],
                    1,
                    (sentinel_point[0] + 3, sentinel_point[1]),
                )
                revive_buff = buffs["ZealotPurifierRevive"]
                if revive_buff not in sentinel.buff_ids:
                    raise RuntimeError("Purifier original Reconstruction behavior is missing")
                query = sc_pb.Request()
                query.query.ignore_resource_requirements = True
                query.query.abilities.add(unit_tag=energizer.tag)
                available = (await connection.request(query)).query.abilities[0].abilities
                available_ids = {item.ability_id for item in available}
                available_links = {
                    ability.link_name
                    for ability in data.abilities
                    if ability.ability_id in available_ids
                }
                required = {"VoidSentryChronoBeam", "VoidSentryPhasingMode"}
                if not required <= available_links:
                    raise RuntimeError(
                        f"Purifier original Energizer abilities missing: {available_links}"
                    )
                print("PROTOSS_PURIFIER_PURE_ABILITIES=PASS reconstruction chrono_beam phasing_mode")
        if faction == "Taldarim":
            request = sc_pb.Request()
            request.data.CopyFrom(
                sc_pb.RequestData(unit_type_id=True, ability_id=True, buff_id=True)
            )
            data = (await connection.request(request)).data
            ids = {unit.name: unit.unit_id for unit in data.units}
            abilities = {ability.link_name: ability.ability_id for ability in data.abilities}
            blink_candidates = [
                ability.ability_id
                for ability in data.abilities
                if ability.link_name == "BlinkSlayer"
            ]
            buffs = {buff.name: buff.buff_id for buff in data.buffs}
            workers = [
                unit
                for unit in observation.observation.raw_data.units
                if unit.owner == 1 and unit.unit_type == ids["Probe"]
            ]
            center = (
                sum(unit.pos.x for unit in workers) / len(workers),
                sum(unit.pos.y for unit in workers) / len(workers),
            )
            caster_point = (center[0] + 30, center[1] - 8)
            await connection.debug_create_units(
                ids["Sentry"], 1, caster_point[0], caster_point[1], 1
            )
            await connection.debug_create_units(
                ids["HighTemplar"], 1, caster_point[0] + 3, caster_point[1], 1
            )
            await connection.step(2)
            caster_observation = await connection.observation(disable_fog=True)
            havoc = nearest(
                caster_observation.observation.raw_data.units,
                ids["Sentry"], 1, caster_point,
            )
            ascendant = nearest(
                caster_observation.observation.raw_data.units,
                ids["HighTemplar"], 1, (caster_point[0] + 3, caster_point[1]),
            )
            required_by_tag = {
                havoc.tag: {"ObserverTargetLock", "ForceFieldMonitor"},
                ascendant.tag: {
                    "VoidHighTemplarMindBlast",
                    "VoidHighTemplarPsiOrb",
                    "AscendantSacrifice",
                },
            }
            for unit_tag, required in required_by_tag.items():
                query = sc_pb.Request()
                query.query.ignore_resource_requirements = True
                query.query.abilities.add(unit_tag=unit_tag)
                available = (await connection.request(query)).query.abilities[0].abilities
                available_ids = {item.ability_id for item in available}
                available_links = {
                    ability.link_name
                    for ability in data.abilities
                    if ability.ability_id in available_ids
                }
                if not required <= available_links:
                    raise RuntimeError(
                        f"Taldarim original caster abilities missing: "
                        f"required={required} available={available_links}"
                    )
            print("PROTOSS_TALDARIM_PURE_CASTER_ABILITIES=PASS target_lock force_field mind_blast psi_orb sacrifice")
            slayer_point = (center[0] + 12, center[1] - 8)
            await connection.debug_create_units(
                ids["Stalker"], 1, slayer_point[0], slayer_point[1], 1
            )
            await connection.step(2)
            created = await connection.observation(disable_fog=True)
            slayer = nearest(
                created.observation.raw_data.units,
                ids["Stalker"],
                1,
                slayer_point,
            )
            query = sc_pb.Request()
            query.query.ignore_resource_requirements = True
            query.query.abilities.add(unit_tag=slayer.tag)
            available = (await connection.request(query)).query.abilities[0].abilities
            available_ids = [item.ability_id for item in available]
            blink_command = next(
                (candidate for candidate in blink_candidates if candidate in available_ids),
                abilities["BlinkSlayer"],
            )
            result = await connection.raw_unit_command(
                [slayer.tag],
                blink_command,
                target_position=(slayer_point[0] + 5, slayer_point[1]),
            )
            if result != (1,):
                raise RuntimeError(
                    "Taldarim Slayer Blink rejected: "
                    f"{result}, blink={blink_command}, available={available_ids}"
                )
            await connection.step(2)
            after_blink = await connection.observation(disable_fog=True)
            blinked = next(
                unit for unit in after_blink.observation.raw_data.units if unit.tag == slayer.tag
            )
            if buffs["PhaseBlinkDamage"] not in blinked.buff_ids:
                raise RuntimeError(
                    f"Taldarim Slayer damage buff missing: buffs={list(blinked.buff_ids)}"
                )
            print("PROTOSS_TALDARIM_SLAYER_BLINK=PASS damage_buff=8s")

            supplicant_point = (center[0] + 24, center[1] + 8)
            await connection.debug_create_units(
                ids["Zealot"], 1, supplicant_point[0], supplicant_point[1], 1
            )
            await connection.debug_create_units(
                ids["Marauder"], 2, supplicant_point[0] + 1, supplicant_point[1], 1
            )
            await connection.step(2)
            before_attack = await connection.observation(disable_fog=True)
            supplicant = nearest(
                before_attack.observation.raw_data.units,
                ids["Zealot"],
                1,
                supplicant_point,
            )
            target = nearest(
                before_attack.observation.raw_data.units,
                ids["Marauder"],
                2,
                (supplicant_point[0] + 1, supplicant_point[1]),
            )
            result = await connection.raw_unit_command(
                [supplicant.tag], 23, target_unit_tag=target.tag
            )
            if result != (1,):
                raise RuntimeError(f"Taldarim Supplicant attack rejected: {result}")
            overload_seen = False
            for _ in range(30):
                await connection.step(4)
                sample = await connection.observation(disable_fog=True)
                current = next(
                    (
                        unit
                        for unit in sample.observation.raw_data.units
                        if unit.tag == supplicant.tag
                    ),
                    None,
                )
                if current is not None and buffs["AlarakZealotFrenziedOverload"] in current.buff_ids:
                    overload_seen = True
                    break
            if not overload_seen:
                raise RuntimeError("Taldarim Frenzied Overload did not autocast after combat")
            print("PROTOSS_TALDARIM_FRENZIED_OVERLOAD_AUTOCAST=PASS")
    finally:
        if connection is not None:
            await connection.quit()
            await connection.close()
        stop_process(process)


async def main() -> None:
    for offset, faction in enumerate(FACTIONS):
        await verify_faction(faction, offset)
    print("PROTOSS_FACTIONS=PASS")


if __name__ == "__main__":
    asyncio.run(main())
