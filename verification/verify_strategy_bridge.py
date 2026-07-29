from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sc2team.custom_config import CustomLauncherConfig
from sc2team.custom_runtime import (
    RACE_VALUES,
    build_runtime_map,
    player_setups,
    runtime_player_id,
)
from sc2team.process import discover_sc2_executable, launch_sc2, stop_process
from sc2team.protocol import Sc2Connection


BASE_MAP_FILE = (
    PROJECT_ROOT
    / "map"
    / "source"
    / "europe-melee-2-7v7-rich-50000-fixed-teams.SC2Map"
)
RUNTIME_MAP_FILE = PROJECT_ROOT / "runtime" / "maps" / "bridge-probe.SC2Map"
SETTINGS_FILE = Path(
    os.environ.get(
        "SC2TEAM_SETTINGS_FILE",
        PROJECT_ROOT / "runtime" / "custom_ai_settings.json",
    )
)

MOVE_ABILITY_ID = 16
MARINE_UNIT_TYPE = 48
MARAUDER_UNIT_TYPE = 51
WORKER_UNIT_TYPES = {45, 84, 104}  # SCV, Probe, Drone
TOWN_HALL_TYPES = {18, 130, 132, 59, 86, 100, 101}  # 종족 불문 타운홀 합집합


def unit_rows(observation, owner: int, unit_types: set[int]):
    return [
        unit
        for unit in observation.observation.raw_data.units
        if unit.owner == owner and unit.unit_type in unit_types
    ]


def order_rows(units):
    return {
        unit.tag: tuple(order.ability_id for order in unit.orders)
        for unit in units
    }


async def main() -> None:
    config = CustomLauncherConfig.from_dict(
        json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    )
    enemy_slots = [
        slot
        for slot in config.custom_ai_slots
        if slot.team != config.human.team
    ]
    if not enemy_slots:
        raise RuntimeError("전략 브리지를 시험할 적 AI 슬롯이 없습니다.")

    target_slot = enemy_slots[0]
    target_player = runtime_player_id(config, target_slot.slot)
    build_runtime_map(
        PROJECT_ROOT,
        BASE_MAP_FILE,
        RUNTIME_MAP_FILE,
        config,
        bridge_probe=True,
        active_config_file=RUNTIME_MAP_FILE.with_suffix(".json"),
    )

    process = launch_sc2(discover_sc2_executable(), 14111, 0)
    connection: Sc2Connection | None = None
    try:
        connection = await Sc2Connection.open(14111)
        await connection.create_game_with_setups(
            RUNTIME_MAP_FILE.name,
            RUNTIME_MAP_FILE.read_bytes(),
            player_setups(config),
            realtime=True,
        )
        joined_player = await connection.join_game(
            RACE_VALUES[config.human.race],
            "Strategy Bridge Verification",
            None,
        )
        if joined_player != 1:
            raise RuntimeError(f"검증 참가자가 runtime P{joined_player}로 배치됐습니다.")

        # Let the initially overlapping melee units finish collision separation
        # before measuring an idle baseline and the bridge-issued movement.
        await asyncio.sleep(4.0)
        before = await connection.observation(disable_fog=True)
        beacons = unit_rows(before, 1, {MARINE_UNIT_TYPE})
        if len(beacons) != 1:
            positions = [(unit.pos.x, unit.pos.y) for unit in beacons]
            raise RuntimeError(
                f"명령 비컨을 하나만 찾아야 하지만 {len(beacons)}개입니다: {positions}"
            )

        workers_before = unit_rows(before, target_player, WORKER_UNIT_TYPES)
        if not workers_before:
            raise RuntimeError(f"대상 runtime P{target_player}의 일꾼이 없습니다.")
        before_by_tag = {unit.tag: (unit.pos.x, unit.pos.y) for unit in workers_before}
        orders_before = order_rows(workers_before)
        human_units = [
            unit
            for unit in before.observation.raw_data.units
            if unit.owner == 1 and unit.tag != beacons[0].tag
        ]
        if not human_units:
            raise RuntimeError("사람 플레이어의 시작 유닛을 찾지 못했습니다.")
        human_center = (
            sum(unit.pos.x for unit in human_units) / len(human_units),
            sum(unit.pos.y for unit in human_units) / len(human_units),
        )

        await asyncio.sleep(2.0)
        baseline = await connection.observation(disable_fog=True)
        baseline_workers = unit_rows(baseline, target_player, WORKER_UNIT_TYPES)
        baseline_by_tag = {
            unit.tag: (unit.pos.x, unit.pos.y) for unit in baseline_workers
        }

        # Map-side bridge encoding: X=100+opcode, Y=100+runtime player ID.
        action_result = await connection.raw_unit_command(
            [beacons[0].tag],
            MOVE_ABILITY_ID,
            target_position=(102.0, 100.0 + target_player),
        )
        await asyncio.sleep(0.1)
        immediate = await connection.observation(disable_fog=True)
        workers_immediate = unit_rows(immediate, target_player, WORKER_UNIT_TYPES)
        await asyncio.sleep(12.0)
        after = await connection.observation(disable_fog=True)
        workers_after = unit_rows(after, target_player, WORKER_UNIT_TYPES)

        moved_to_command = 0
        baseline_movement = []
        movement = []
        for tag, (old_x, old_y) in before_by_tag.items():
            if tag in baseline_by_tag:
                new_x, new_y = baseline_by_tag[tag]
                baseline_movement.append((tag, new_x - old_x, new_y - old_y))
        for unit in workers_after:
            if unit.tag not in baseline_by_tag:
                continue
            old_x, old_y = baseline_by_tag[unit.tag]
            dx = unit.pos.x - old_x
            dy = unit.pos.y - old_y
            movement.append((unit.tag, dx, dy))
            if dx * dx + dy * dy > 25.0:
                moved_to_command += 1

        print(
            f"target=P{target_slot.slot}->runtime P{target_player} "
            f"race={target_slot.race} workers={len(before_by_tag)}"
        )
        print(f"beacon_action={action_result}")
        print(f"worker_positions_before={before_by_tag}")
        print(f"human_center={human_center}")
        print(f"orders_before={orders_before}")
        print(f"orders_immediate={order_rows(workers_immediate)}")
        print(f"baseline_movement={baseline_movement}")
        print(f"worker_movement={movement}")
        print(f"moved_to_command={moved_to_command}/{len(before_by_tag)}")
        if action_result and moved_to_command == len(before_by_tag):
            print("GALAXY_AI_WORKER_ORDER_TEST=PASS")
        else:
            raise RuntimeError("GALAXY_AI_WORKER_ORDER_TEST=FAIL")

        # opcode 11(대상 지정 공격): X=111은 이번이 첫 엔진 사격이므로 X 대역과
        # Y 소수부 복호, 동적 목적지 해석을 한 번에 검증한다. 공격자는 적 AI,
        # 동적 대상은 인간 팀의 아군 AI — 정적 폴백(첫 번째 적 = 인간 시작 위치)과
        # 목적지가 다르므로 폴백과 구별된다.
        #
        # raw 관측의 orders는 자기 소유 유닛에만 채워지므로(기존 두 프로브가 모두
        # 이동 거리로 검증하는 이유) 여기서도 이동으로 판정한다. 마준더를 동적
        # 목적지에서 12유닛 떨어진 지점에 소환하면: 명령이 맞으면 타운홀로 접근,
        # 정적 폴백이면 멀어지고, 분기 미작동이면 제자리라 셋이 구별된다.
        ally_slots = [
            slot
            for slot in config.custom_ai_slots
            if slot.team == config.human.team
        ]
        if not ally_slots:
            raise RuntimeError("대상 지정 공격을 시험할 아군 AI 슬롯이 없습니다.")
        dynamic_slot = ally_slots[0]
        dynamic_player = runtime_player_id(config, dynamic_slot.slot)

        dynamic_halls = [
            unit
            for unit in after.observation.raw_data.units
            if unit.owner == dynamic_player and unit.unit_type in TOWN_HALL_TYPES
        ]
        if not dynamic_halls:
            raise RuntimeError(f"동적 대상 runtime P{dynamic_player}의 타운홀이 없습니다.")
        expected = (dynamic_halls[0].pos.x, dynamic_halls[0].pos.y)
        away = (human_center[0] - expected[0], human_center[1] - expected[1])
        away_len = (away[0] ** 2 + away[1] ** 2) ** 0.5
        if away_len < 1.0:
            away, away_len = (1.0, 0.0), 1.0
        spawn_point = (
            expected[0] + away[0] / away_len * 12.0,
            expected[1] + away[1] / away_len * 12.0,
        )
        old_marauders = {
            unit.tag for unit in unit_rows(after, target_player, {MARAUDER_UNIT_TYPE})
        }
        await connection.debug_create_units(
            MARAUDER_UNIT_TYPE,
            target_player,
            spawn_point[0],
            spawn_point[1],
            1,
        )
        await asyncio.sleep(1.0)
        spawned = await connection.observation(disable_fog=True)
        marauder = next(
            unit
            for unit in unit_rows(spawned, target_player, {MARAUDER_UNIT_TYPE})
            if unit.tag not in old_marauders
        )
        start_to_hall_sq = (
            (marauder.pos.x - expected[0]) ** 2 + (marauder.pos.y - expected[1]) ** 2
        )

        targeted_result = await connection.raw_unit_command(
            [beacons[0].tag],
            MOVE_ABILITY_ID,
            target_position=(111.0, 100.0 + target_player + dynamic_player / 100.0),
        )
        print(
            f"targeted_attack: attacker=runtime P{target_player} "
            f"dynamic_target=runtime P{dynamic_player} beacon_action={targeted_result}"
        )
        await asyncio.sleep(6.0)
        ordered = await connection.observation(disable_fog=True)
        ordered_marauder = next(
            (
                unit
                for unit in unit_rows(ordered, target_player, {MARAUDER_UNIT_TYPE})
                if unit.tag == marauder.tag
            ),
            None,
        )
        if ordered_marauder is None:
            raise RuntimeError("GALAXY_TARGETED_ATTACK_TEST=FAIL (마준더 소실)")
        moved_sq = (
            (ordered_marauder.pos.x - marauder.pos.x) ** 2
            + (ordered_marauder.pos.y - marauder.pos.y) ** 2
        )
        end_to_hall_sq = (
            (ordered_marauder.pos.x - expected[0]) ** 2
            + (ordered_marauder.pos.y - expected[1]) ** 2
        )
        print(
            f"expected_hall={expected} spawn=({marauder.pos.x:.1f},{marauder.pos.y:.1f}) "
            f"end=({ordered_marauder.pos.x:.1f},{ordered_marauder.pos.y:.1f})"
        )
        approach = start_to_hall_sq ** 0.5 - end_to_hall_sq ** 0.5
        print(
            f"moved_sq={moved_sq:.1f} approach={approach:.2f} "
            f"to_hall_sq {start_to_hall_sq:.1f} -> {end_to_hall_sq:.1f}"
        )
        # 접근량 판정: 공격 이동은 도중에 교전을 시작해 이동량 자체는 작을 수 있다
        # (실측: 6초에 2.8 이동, 접근 2.2 후 사거리에서 정지). 대상 타운홀로
        # 접근하면 동적 목적지, 멀어지면 정적 폴백(인간 시작 위치), 0이면 미작동
        # 이라 접근량 부호만으로 셋이 구별된다.
        if moved_sq >= 1.0 and approach >= 1.5:
            print("GALAXY_TARGETED_ATTACK_TEST=PASS")
        else:
            raise RuntimeError("GALAXY_TARGETED_ATTACK_TEST=FAIL")
    finally:
        if connection is not None:
            await connection.quit()
            await connection.close()
        stop_process(process)


if __name__ == "__main__":
    asyncio.run(main())
