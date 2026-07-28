# 교전 빈도 프로브 (참가자 모드).
#
# 사용자 관측: "특정 AI는 10분에 교전 한두 번밖에 안 한다."
# 그 관측은 옵저버 모드에서 나온 것이고, 옵저버 게임은 전략 제어기가 아예
# 생성되지 않는다(app/play_custom_ai.py:200). 이 프로브는 **참가자 모드**로
# 붙어 전략 제어기를 실제로 돌린 뒤, 다음을 잰다.
#
#   1. 출격 지시가 실제로 몇 번 나가는가 (StrategyUpdate.attack_slots)
#   2. 지시를 받은 병력이 실제로 자기 기지에서 멀어지는가 (군집 중심 이동)
#   3. 교전이 실제로 일어나는가 (체력이 깎인 유닛 수 / 분당 교전 틱 수)
#
# 지시는 나가는데 (2)(3)이 안 오르면 명령이 멜레 AI에게 덮어써지는 것이고,
# 지시 자체가 안 나가면 출격 문턱 문제다. 둘은 완전히 다른 수정으로 이어진다.
#
# 사람 슬롯(P4)은 API 참가자라 아무 것도 안 한다. 집계에서 제외한다.
#
# 사용: .venv\Scripts\python.exe <이 파일> [게임분]

from __future__ import annotations

import asyncio
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(r"C:\Users\cbkjh\OneDrive\바탕 화면\M\Play\startcraft2")
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from s2clientprotocol import sc2api_pb2 as sc_pb

from sc2team.custom_config import CustomLauncherConfig
from sc2team.custom_runtime import (
    build_runtime_map,
    load_stock_targets,
    player_setups,
    runtime_player_id,
    runtime_slots,
)
from sc2team.process import discover_sc2_executable, launch_sc2, stop_process
from sc2team.protocol import Sc2Connection
from sc2team.strategy_controller import GAME_LOOPS_PER_SECOND, StrategyController

SETTINGS_FILE = PROJECT_ROOT / "runtime" / "custom_ai_settings.json"
BASE_MAP_FILE = (
    PROJECT_ROOT / "map" / "source"
    / "europe-melee-2-7v7-rich-50000-fixed-teams.SC2Map"
)
PROBE_MAP_FILE = PROJECT_ROOT / "runtime" / "maps" / "engagement-probe.SC2Map"
PORT = 14191

RACE_VALUES = {"Terran": 1, "Zerg": 2, "Protoss": 3, "Random": 4}
TOWN_HALLS = {18, 132, 130, 59, 86, 100, 101}  # CC/Orbital/PF, Nexus, Hatch/Lair/Hive

GROUND_ARMY = {
    # 테란
    "Marine", "Marauder", "Reaper", "Ghost", "Hellion", "HellionTank",
    "SiegeTank", "SiegeTankSieged", "Thor", "ThorAP", "Cyclone",
    "WidowMine", "SC2TeamGoliath", "SC2TeamPredator", "SC2TeamMedic",
    # 프로토스
    "Zealot", "Stalker", "Sentry", "Adept", "HighTemplar", "DarkTemplar",
    "Archon", "Immortal", "Colossus", "Disruptor",
}

# §92: P15 야생 저그의 인구 400 상한 확인용. API 는 다른 플레이어의 은행·인구를
# 노출하지 않으므로(§91 계측 함정) 유닛별 보급값을 직접 더해 추정한다. 상한은
# Galaxy 가 SuppliesUsed 로 재고, 이 표는 그 값이 400 근처에서 멈추는지를 본다.
# 대군주는 인구를 소비하지 않으므로 0 이다. **드론도 0 이다** — 이 맵은 일꾼
# 보급 비용을 0 으로 바꿔 놨다(HANDOFF "Worker supply cost is zero"). 처음에
# 1.0 으로 잡았더니 드론 80 기가 통째로 추정치에 얹혀 상한 도달 시점을 두
# 리포트나 앞당겨 읽었다.
P15_SUPPLY = {
    "Drone": 0.0, "Queen": 2.0, "Zergling": 0.5, "Baneling": 0.5,
    "Roach": 2.0, "Ravager": 3.0, "Hydralisk": 2.0, "Lurker": 3.0,
    "LurkerMP": 3.0, "Mutalisk": 2.0, "Corruptor": 2.0, "Infestor": 2.0,
    "SwarmHost": 3.0, "Ultralisk": 6.0, "HotSTorrasque": 6.0,
    "SC2TeamAberration": 3.0,
}
P15_ARMY = frozenset(P15_SUPPLY) - {"Drone", "Queen"}


async def main() -> None:
    minutes = float(sys.argv[1]) if len(sys.argv) > 1 else 20.0
    # 사용자 요청 구성: 테란 참가자 1 + 테란 AI 6 vs 프로토스 AI 6.
    # 저장된 설정은 P6이 비어 있으므로 여기서만 채운다. 사용자 설정 파일은
    # 건드리지 않는다(메모리 상에서만 수정).
    raw = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    for entry in raw.get("slots", []):
        if entry.get("slot") == 6:
            entry["controller"] = "custom_ai"
            entry["race"] = "Terran"
            entry["build"] = "bio"
    config = CustomLauncherConfig.from_dict(raw)
    config.validate()

    slots = list(runtime_slots(config))
    label = {}
    for runtime_id, slot in enumerate(slots, start=1):
        tag = "사람(무행동)" if slot.controller == "human" else slot.build
        label[runtime_id] = (f"P{slot.slot}", slot.race[:1], tag, slot.team)

    process = None
    connection = None
    try:
        print("맵 빌드 중...", flush=True)
        runtime_map = build_runtime_map(
            PROJECT_ROOT, BASE_MAP_FILE, PROBE_MAP_FILE, config,
            strategy_bridge=True,
            campaign_units_pilot=True,
            observer_mode=False,
            active_config_file=PROBE_MAP_FILE.with_suffix(".json"),
        )
        process = launch_sc2(discover_sc2_executable(), PORT, 0)
        connection = await Sc2Connection.open(PORT, timeout=180.0)
        await connection.create_game_with_setups(
            PROBE_MAP_FILE.name, PROBE_MAP_FILE.read_bytes(),
            player_setups(config, observer=False), realtime=False,
        )
        player_id = await connection.join_game(
            RACE_VALUES[config.human.race], f"P{config.human.slot} Probe", None
        )
        expected = runtime_player_id(config, config.human.slot)
        if player_id != expected:
            raise RuntimeError(f"슬롯 매핑 실패: {player_id} != {expected}")

        first = await connection.observation(disable_fog=True)
        strategy = StrategyController(connection, config)
        request = sc_pb.Request()
        request.data.CopyFrom(sc_pb.RequestData(unit_type_id=True))
        game_data = (await connection.request(request)).data
        by_name = {u.name: u for u in game_data.units}
        name_of = {u.unit_id: u.name for u in game_data.units}
        for unit_name, supply in {
            "HotSTorrasque": 6.0, "SC2TeamAberration": 3.0,
            "SC2TeamGoliath": 2.0, "SC2TeamMedic": 1.0, "SC2TeamPredator": 3.0,
        }.items():
            unit = by_name.get(unit_name)
            if unit is None or not unit.available or unit.ability_id == 0:
                raise RuntimeError(f"캠페인 유닛 데이터 없음: {unit_name}")
            strategy.register_ground_combat_unit(unit.unit_id, supply)
        for entry in load_stock_targets(runtime_map):
            stock_by_id = {}
            for unit_name, spec in entry["stock"].items():
                unit = by_name.get(unit_name)
                if unit is None:
                    raise RuntimeError(f"목표 재고 유닛 없음: {unit_name}")
                stock_by_id[unit.unit_id] = (
                    float(spec["count"]), float(spec["perExpansion"])
                )
            if stock_by_id:
                strategy.set_stock_targets(entry["logical_slot"], stock_by_id)
        strategy.initialize(first)

        # 각 슬롯의 본진 좌표: 첫 관측의 타운홀 위치.
        home: dict[int, tuple[float, float]] = {}
        for u in first.observation.raw_data.units:
            if u.unit_type in TOWN_HALLS and u.owner not in home:
                home[u.owner] = (u.pos.x, u.pos.y)

        attacks = defaultdict(int)      # 누적 출격 지시 횟수
        supports = defaultdict(int)     # 누적 지원 파견 횟수
        fight_ticks = defaultdict(int)  # 누적 "피해를 입은 틱" 수
        prev_hp: dict[int, float] = {}

        limit = int(minutes * 60 * GAME_LOOPS_PER_SECOND)
        next_report = 120.0
        while True:
            await connection.step(336)  # 15초
            obs = await connection.observation(disable_fog=True)
            if obs.player_result:
                print("게임 종료", flush=True)
                break
            elapsed = obs.observation.game_loop / GAME_LOOPS_PER_SECOND

            update = await strategy.update(obs)
            # StrategyUpdate 는 **논리** 슬롯 번호를 돌려준다(`slot.slot`,
            # `helper.slot`). 아래 출력 루프는 런타임 id 로 도는데, 예전에는
            # 여기서 논리 번호를 그대로 런타임 키에 더해 두 열이 서로 다른
            # 슬롯의 값으로 어긋나 있었다. 사람 슬롯이 P4 라 런타임 순서가
            # (P4, P1, P2, P3, P5…) 로 밀리는 이 설정에서는 특히 눈에 띈다 —
            # 문턱을 넘어 "쿨"이 뜬 P3 의 출격이 P2 행에 찍혔다. 여기서 런타임
            # id 로 변환해 둔다.
            for logical in update.attack_slots:
                attacks[runtime_player_id(config, logical)] += 1
            for helper, _victim in update.supports:
                supports[runtime_player_id(config, helper)] += 1

            # 이번 틱에 체력이 깎인 유닛이 있는 플레이어 = 교전 중.
            cur_hp: dict[int, float] = {}
            hurt = defaultdict(int)
            for u in obs.observation.raw_data.units:
                cur_hp[u.tag] = u.health
                before = prev_hp.get(u.tag)
                if before is not None and u.health < before - 0.5:
                    hurt[u.owner] += 1
            prev_hp = cur_hp
            for owner, count in hurt.items():
                if count:
                    fight_ticks[owner] += 1

            if elapsed >= next_report:
                next_report += 120.0
                print(f"===== {elapsed:.0f}s =====", flush=True)
                for rid in sorted(label):
                    slot_tag, race, build, team = label[rid]
                    # 지상 전투 유닛만 센다. 구조물/일꾼/공중을 이름으로
                    # 거르면 목록 관리가 되므로 명시 집합을 쓴다.
                    army = [
                        u for u in obs.observation.raw_data.units
                        if u.owner == rid
                        and u.build_progress >= 0.99
                        and name_of.get(u.unit_type, "") in GROUND_ARMY
                    ]
                    # 출격 문턱 실측: 지시가 0인 슬롯이 문턱 미달인지, 아니면
                    # 문턱은 넘었는데 다른 이유로 안 나가는지 가른다.
                    slot_cfg = next(
                        (s for s in strategy.commanded_slots
                         if f"P{s.slot}" == slot_tag), None
                    )
                    if slot_cfg is not None:
                        power, need, _prod = strategy.army_readiness(
                            obs, slot_cfg.slot
                        )
                        ready = f"전투력 {power:5.0f}/{need:3.0f}"
                        cd = strategy._attack_cooldown_until.get(slot_cfg.slot, 0.0)
                        ready += " 쿨" if elapsed < cd else "    "
                    else:
                        ready = "전투력   -/  -    "
                    hx, hy = home.get(rid, (0.0, 0.0))
                    if army:
                        cx = sum(u.pos.x for u in army) / len(army)
                        cy = sum(u.pos.y for u in army) / len(army)
                        dist = math.hypot(cx - hx, cy - hy)
                    else:
                        dist = 0.0
                    mins = elapsed / 60.0
                    print(
                        f"  {slot_tag:>3} {race} T{team} {build:<17}"
                        f" 병력 {len(army):3d}"
                        f" | 출격지시 {attacks[rid]:3d}"
                        f" 지원 {supports[rid]:2d}"
                        f" | 교전틱 {fight_ticks[rid]:3d}"
                        f"({fight_ticks[rid]/max(mins,1)*10:.1f}/10분)"
                        f" | {ready} | 본진거리 {dist:5.1f}",
                        flush=True,
                    )
                # §92: P15 인구 400 상한 확인. 상한은 병력만 막으므로 드론은
                # 계속 늘 수 있다 — 그래서 병력/일꾼/총합을 나눠 찍는다.
                p15_army = 0
                p15_supply = 0.0
                p15_workers = 0
                for u in obs.observation.raw_data.units:
                    if u.owner != 15 or u.build_progress < 0.99:
                        continue
                    name = name_of.get(u.unit_type, "")
                    p15_supply += P15_SUPPLY.get(name, 0.0)
                    if name in P15_ARMY:
                        p15_army += 1
                    elif name == "Drone":
                        p15_workers += 1
                print(
                    f"  P15 야생저그  병력 {p15_army:3d} 드론 {p15_workers:3d}"
                    f" | 추정인구 {p15_supply:5.1f}/400"
                    f"{'  ← 상한' if p15_supply >= 400 else ''}",
                    flush=True,
                )
            if obs.observation.game_loop >= limit:
                break
        print("ENGAGEMENT_PROBE=DONE", flush=True)
    finally:
        if connection is not None:
            try:
                await connection.quit()
                await connection.close()
            except Exception:
                pass
        if process is not None:
            stop_process(process)


if __name__ == "__main__":
    asyncio.run(main())
