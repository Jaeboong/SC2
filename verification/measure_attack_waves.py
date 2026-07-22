# 출격 규모 실측 하네스 (비실시간 스테핑 배속).
#
# §51과 같은 방식: 저장된 사용자 설정으로 릴리스 맵을 열고, 실제
# StrategyController를 1게임초 간격으로 구동하면서 출격/지원 이벤트와
# 플레이어별 병력 규모를 기록한다. 치트(fast_build 등)는 생산을 왜곡하므로
# 쓰지 않고, realtime=False 스테핑으로만 시간을 빨리 감는다.
#
# 사용: .venv\Scripts\python.exe verification\measure_attack_waves.py [게임분]
# (기본 16분. SC2/에디터를 먼저 종료할 것.)

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from s2clientprotocol import sc2api_pb2 as sc_pb

from sc2team.custom_config import CustomLauncherConfig
from sc2team.custom_runtime import (
    RACE_VALUES,
    load_stock_targets,
    player_setups,
    runtime_player_id,
    runtime_slots,
)
from sc2team.process import discover_sc2_executable, launch_sc2, stop_process
from sc2team.protocol import Sc2Connection
from sc2team.strategy_controller import (
    GAME_LOOPS_PER_SECOND,
    GROUND_COMBAT_SUPPLY,
    StrategyController,
    TOWN_HALL_TYPES,
)

SETTINGS_FILE = PROJECT_ROOT / "runtime" / "custom_ai_settings.json"
RELEASE_MAP_FILE = (
    PROJECT_ROOT / "runtime" / "maps" / "europe-melee-custom-ai-v1.25.0.SC2Map"
)
PORT = 14131

# 런처와 같은 캠페인 유닛 전투력 등록 표.
CUSTOM_COMBAT_SUPPLY = {
    "HotSTorrasque": 6.0,
    "SC2TeamAberration": 3.0,
    "SC2TeamGoliath": 2.0,
    "SC2TeamMedic": 1.0,
    "SC2TeamPredator": 3.0,
}


def army_snapshot(observation, runtime_player, weights):
    """지상 전투 유닛의 (마릿수, 전투력 합, 완성 타운홀 수)."""

    bodies = 0
    power = 0.0
    halls = 0
    for unit in observation.observation.raw_data.units:
        if unit.owner != runtime_player or unit.build_progress < 0.99:
            continue
        if unit.unit_type in TOWN_HALL_TYPES:
            halls += 1
        if unit.is_flying:
            continue
        weight = weights.get(unit.unit_type, 0.0)
        if weight > 0.0:
            bodies += 1
            power += weight
    return bodies, power, halls


async def main() -> None:
    minutes = float(sys.argv[1]) if len(sys.argv) > 1 else 16.0
    config = CustomLauncherConfig.from_dict(
        json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    )
    if not RELEASE_MAP_FILE.is_file():
        raise FileNotFoundError(f"릴리스 맵이 없습니다: {RELEASE_MAP_FILE}")

    process = launch_sc2(discover_sc2_executable(), PORT, 0)
    connection: Sc2Connection | None = None
    try:
        connection = await Sc2Connection.open(PORT)
        await connection.create_game_with_setups(
            RELEASE_MAP_FILE.name,
            RELEASE_MAP_FILE.read_bytes(),
            player_setups(config),
            realtime=False,
        )
        await connection.join_game(
            RACE_VALUES[config.human.race], "Attack Wave Measurement", None
        )

        data_request = sc_pb.Request()
        data_request.data.CopyFrom(sc_pb.RequestData(unit_type_id=True))
        game_data = (await connection.request(data_request)).data
        units_by_name = {unit.name: unit for unit in game_data.units}

        strategy = StrategyController(connection, config)
        weights = dict(GROUND_COMBAT_SUPPLY)
        for unit_name, supply in CUSTOM_COMBAT_SUPPLY.items():
            unit = units_by_name.get(unit_name)
            if unit is None:
                raise RuntimeError(f"캠페인 유닛을 찾지 못했습니다: {unit_name}")
            strategy.register_ground_combat_unit(unit.unit_id, supply)
            weights[unit.unit_id] = supply
        for entry in load_stock_targets(RELEASE_MAP_FILE):
            stock_by_id = {}
            for unit_name, spec in entry["stock"].items():
                unit = units_by_name.get(unit_name)
                if unit is None:
                    raise RuntimeError(f"목표 재고 유닛을 찾지 못했습니다: {unit_name}")
                stock_by_id[unit.unit_id] = (
                    float(spec["count"]),
                    float(spec["perExpansion"]),
                )
            if stock_by_id:
                strategy.set_stock_targets(entry["logical_slot"], stock_by_id)

        await connection.step(22)
        first = await connection.observation(disable_fog=True)
        strategy.initialize(first)

        slot_names = {
            slot.slot: f"P{slot.slot}({slot.build})"
            for slot in config.custom_ai_slots
        }
        runtime_of = {
            slot.slot: runtime_player_id(config, slot.slot)
            for slot in config.custom_ai_slots
        }
        limit_loops = int(minutes * 60 * GAME_LOOPS_PER_SECOND)
        attack_counts: dict[int, int] = {}
        support_count = 0
        next_report = 0.0

        print(f"측정 시작: {minutes:g}게임분, 맵={RELEASE_MAP_FILE.name}")
        while True:
            await connection.step(22)
            observation = await connection.observation(disable_fog=True)
            if observation.player_result:
                print("게임 종료 판정으로 측정을 마칩니다.")
                break
            loop = observation.observation.game_loop
            elapsed = loop / GAME_LOOPS_PER_SECOND
            update = await strategy.update(observation)
            statuses = strategy._player_statuses(observation)
            for helper, victim in update.supports:
                support_count += 1
                print(f"[{elapsed:6.0f}s] 지원: P{helper} -> P{victim}")
            for slot in update.attack_slots:
                attack_counts[slot] = attack_counts.get(slot, 0) + 1
                power, required, producers = strategy.army_readiness(
                    observation, slot
                )
                bodies, _power, _halls = army_snapshot(
                    observation, runtime_of[slot], weights
                )
                team = next(
                    item.team
                    for item in config.custom_ai_slots
                    if item.slot == slot
                )
                target = strategy._select_attack_target(team, statuses)
                target_slot = (
                    runtime_slots(config)[target - 1].slot
                    if target is not None
                    else None
                )
                target_text = f"P{target_slot}" if target_slot else "정적 폴백"
                print(
                    f"[{elapsed:6.0f}s] 출격: {slot_names[slot]} "
                    f"{bodies}기 전투력 {power:g}/{required:g} "
                    f"생산 {producers} -> {target_text}"
                )
            if elapsed >= next_report:
                rows = []
                for slot in config.custom_ai_slots:
                    bodies, power, halls = army_snapshot(
                        observation, runtime_of[slot.slot], weights
                    )
                    rows.append(f"P{slot.slot}:{bodies}기/{power:g}파워/{halls}홀")
                print(f"[{elapsed:6.0f}s] 현황 {' '.join(rows)}", flush=True)
                next_report = elapsed + 120.0
            if loop >= limit_loops:
                break

        print("--- 요약 ---")
        for slot in config.custom_ai_slots:
            print(
                f"{slot_names[slot.slot]}: 출격 {attack_counts.get(slot.slot, 0)}회"
            )
        print(f"지원 발동 합계: {support_count}회")
        print("MEASURE_ATTACK_WAVES=DONE")
    finally:
        if connection is not None:
            await connection.quit()
            await connection.close()
        stop_process(process)


if __name__ == "__main__":
    asyncio.run(main())
