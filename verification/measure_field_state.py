# 종합 전황 계측 하네스 (비실시간 스테핑 배속, §66 옵저버 모드).
#
# 한 판에서 다음을 함께 본다:
#   1. 맵이 정상 실행되는가 (조기 종료·크래시 없이 목표 시간까지)
#   2. P15 야생 저그가 발전하는가 (건물 테크, 병력, 확장) — 1시 알파 둥지 별도 추적
#   3. 테란이 애드온(기술실/반응로)을 실제로 다는가 (§82)
#   4. P8 등 프로토스 슬롯이 병력 없이 멈추지 않는가 (§60·§83 관측 항목)
#   5. AI가 자원을 적극적으로 쓰며 병력을 계속 뽑는가
#
# 왜 옵저버 모드인가: 참가자 모드로 돌리면 사람 슬롯이 무방비로 방치돼 본진이
# 밀리는 순간 게임이 끝난다(§83에서 14분에 조기 종료). 옵저버 모드는 전 슬롯을
# 진짜 컴퓨터로 만들어 12명이 끝까지 플레이하므로 AI 행동을 길게 볼 수 있다.
# 대가: 옵저버 연결은 유닛 명령을 못 내리므로 파이썬 전략 제어기(비콘 브리지)가
# 없다 — 공격은 멜레 AI 자체 공세로만 일어난다(§66). Galaxy 측 생산·구매·연구·
# 본진 수비·P15는 모두 그대로 동작한다.
#
# 한계: SC2 API는 **다른 플레이어의 자원 보유량을 노출하지 않는다**. 항목 5는
# 은행 잔고가 아니라 생산 결과(일꾼·병력·생산건물·확장 증가)로 판정한다.
#
# 사용: .venv\Scripts\python.exe verification\measure_field_state.py [게임분]
# (기본 20분. SC2/에디터를 먼저 종료할 것.)

from __future__ import annotations

import asyncio
import json
import math
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from s2clientprotocol import sc2api_pb2 as sc_pb

from sc2team.custom_config import CustomLauncherConfig
from sc2team.custom_runtime import build_runtime_map, player_setups, runtime_slots
from sc2team.process import discover_sc2_executable, launch_sc2, stop_process
from sc2team.protocol import Sc2Connection
from sc2team.strategy_controller import GAME_LOOPS_PER_SECOND, TOWN_HALL_TYPES

SETTINGS_FILE = PROJECT_ROOT / "runtime" / "custom_ai_settings.json"
BASE_MAP_FILE = (
    PROJECT_ROOT
    / "map"
    / "source"
    / "europe-melee-2-7v7-rich-50000-fixed-teams.SC2Map"
)
PROBE_MAP_FILE = PROJECT_ROOT / "runtime" / "maps" / "field-state-probe.SC2Map"
PORT = 14132
P15 = 15

WORKER_NAMES = ("SCV", "Probe", "Drone")
ADDON_NAMES = (
    "BarracksTechLab", "BarracksReactor",
    "FactoryTechLab", "FactoryReactor",
    "StarportTechLab", "StarportReactor",
)
PRODUCTION_NAMES = (
    "Barracks", "Factory", "Starport",
    "Gateway", "WarpGate", "RoboticsFacility", "Stargate",
)
# P15 발전 단계를 보여주는 건물/유닛. (§88: 알파 테크 진화 체인 추가)
WILD_STRUCTURE_NAMES = (
    "Hatchery", "Lair", "Hive", "SpawningPool", "RoachWarren",
    "HydraliskDen", "SpineCrawler", "Extractor",
    "InfestationPit", "UltraliskCavern",
)
# §87: 슬롯별 병종 생산 추적 — "탱크를 안 뽑는다" 같은 병종 단위 진단용.
# 태그 누적 방식(선배치/사망과 무관하게 신규 생산 총량)으로 센다.
LOBBY_ARMY_WATCH_NAMES = (
    "Marine", "Marauder", "Hellion", "SiegeTank", "SiegeTankSieged", "Thor",
    "SC2TeamGoliath", "SC2TeamPredator", "SC2TeamMedic",
    "Zealot", "Stalker", "Sentry", "HighTemplar", "Archon",
    "Immortal", "Colossus", "Disruptor",
    "Zergling", "Baneling", "Roach", "Ravager", "Hydralisk", "LurkerMP",
    "Ultralisk", "HotSTorrasque", "SC2TeamAberration",
    # §88: 보급 지원 관측 — 슬롯별 보급고/파일런 신규 건설량.
    "SupplyDepot", "SupplyDepotLowered", "Pylon",
)
WILD_ARMY_NAMES = ("Zergling", "Roach", "Hydralisk", "Ultralisk")
# 야생 저그가 둥지를 떠난 것으로 보는 거리. 순찰 반경은 28이므로 그보다 크게 잡는다.
RAID_DISTANCE = 34.0
# 침입 감지 반경(§76 방어 스캔과 같은 값).
INTRUSION_RADIUS = 24.0


def _dist(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def load_config() -> CustomLauncherConfig:
    config = CustomLauncherConfig.from_dict(
        json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    )
    config.validate()
    return config


class Sampler:
    """이름 기반 유닛 타입 집합으로 한 관측을 요약한다."""

    def __init__(self, game_data):
        self.id_of = {unit.name: unit.unit_id for unit in game_data.units}
        self.name_of = {unit.unit_id: unit.name for unit in game_data.units}
        self.worker_ids = self._ids(WORKER_NAMES)
        self.addon_ids = self._ids(ADDON_NAMES)
        self.production_ids = self._ids(PRODUCTION_NAMES)
        self.wild_army_ids = self._ids(WILD_ARMY_NAMES)
        self.nest_ids = self._ids(("Hatchery", "Lair", "Hive"))

    def _ids(self, names) -> set[int]:
        return {self.id_of[name] for name in names if name in self.id_of}


def summarize_lobby(units, sampler, army_ids):
    rows = {}
    for unit in units:
        owner = unit.owner
        if not 1 <= owner <= 14 or unit.build_progress < 0.99:
            continue
        row = rows.setdefault(
            owner, dict(workers=0, army=0, halls=0, production=0, addons=0)
        )
        unit_type = unit.unit_type
        if unit_type in sampler.worker_ids:
            row["workers"] += 1
        elif unit_type in TOWN_HALL_TYPES:
            row["halls"] += 1
        elif unit_type in sampler.addon_ids:
            row["addons"] += 1
        elif unit_type in sampler.production_ids:
            row["production"] += 1
        elif unit_type in army_ids:
            row["army"] += 1
    return rows


async def main() -> None:
    minutes = float(sys.argv[1]) if len(sys.argv) > 1 else 20.0
    config = load_config()

    print("탐사용 맵 빌드 중(옵저버 모드)...", flush=True)
    build_runtime_map(
        PROJECT_ROOT,
        BASE_MAP_FILE,
        PROBE_MAP_FILE,
        config,
        strategy_bridge=True,
        campaign_units_pilot=True,
        observer_mode=True,
        active_config_file=PROBE_MAP_FILE.with_suffix(".json"),
    )

    slots = runtime_slots(config)
    slot_of_runtime = {index + 1: slot for index, slot in enumerate(slots)}
    label = {
        index + 1: f"P{slot.slot}({slot.race[:4]}/{slot.build})"
        for index, slot in enumerate(slots)
    }

    process = launch_sc2(discover_sc2_executable(), PORT, 0)
    print(f"SC2 launch pid={process.pid}", flush=True)
    connection: Sc2Connection | None = None
    try:
        connection = await Sc2Connection.open(PORT, timeout=120.0)
        await connection.create_game_with_setups(
            PROBE_MAP_FILE.name,
            PROBE_MAP_FILE.read_bytes(),
            player_setups(config, observer=True),
            realtime=False,
        )
        await connection.join_as_observer("Field State Probe")

        data_request = sc_pb.Request()
        data_request.data.CopyFrom(sc_pb.RequestData(unit_type_id=True))
        game_data = (await connection.request(data_request)).data
        sampler = Sampler(game_data)

        # 전투 몸통 집합: 일꾼/건물/애드온이 아닌 것 중 실제 군사 유닛만.
        army_ids = {
            unit.unit_id
            for unit in game_data.units
            if unit.food_required > 0
            and unit.unit_id not in sampler.worker_ids
            and not unit.has_minerals
        }
        wild_names = {
            name: sampler.id_of[name]
            for name in WILD_STRUCTURE_NAMES + WILD_ARMY_NAMES + ("Drone", "Overlord")
            if name in sampler.id_of
        }

        await connection.step(22)
        first = await connection.observation(disable_fog=True)

        # 1시 알파 둥지: 원본 맵의 유일한 P15 레어(§80).
        alpha_pos = None
        lair_id = sampler.id_of.get("Lair")
        for unit in first.observation.raw_data.units:
            if unit.owner == P15 and unit.unit_type == lair_id:
                alpha_pos = (unit.pos.x, unit.pos.y)
                break
        base_nests = sum(
            1
            for unit in first.observation.raw_data.units
            if unit.owner == P15 and unit.unit_type in sampler.nest_ids
        )
        base_wild_army = {
            unit.tag
            for unit in first.observation.raw_data.units
            if unit.owner == P15 and unit.unit_type in sampler.wild_army_ids
        }
        # 선배치 기준선. 이걸 안 잡으면 구간 최대값을 "발전했다"로 잘못 읽는다 —
        # 이 맵은 P15에 279기(바퀴 55, 히드라 21, 산란못·바퀴소굴·히드라굴 각 1 등)를
        # 선배치해 두었으므로, 최대값만 보면 아무것도 안 지어도 통과한다.
        base_wild_tags = {
            unit.tag for unit in first.observation.raw_data.units if unit.owner == P15
        }
        # §87: 슬롯별 병종 신규 생산 태그 누적(시즈 모드 등 타입 변형은 이름으로 합산).
        merged_watch_name = {
            "SiegeTankSieged": "SiegeTank",
            "SupplyDepotLowered": "SupplyDepot",
        }
        lobby_watch_ids = {
            sampler.id_of[name]: merged_watch_name.get(name, name)
            for name in LOBBY_ARMY_WATCH_NAMES
            if name in sampler.id_of
        }
        base_lobby_tags = {
            unit.tag
            for unit in first.observation.raw_data.units
            if 1 <= unit.owner <= 14
        }
        lobby_new: dict[int, dict[str, set[int]]] = {}
        base_wild_counts = Counter(
            unit.unit_type
            for unit in first.observation.raw_data.units
            if unit.owner == P15
        )
        print("기준선(선배치) P15:")
        for name, unit_id in sorted(
            (n, i) for n, i in sampler.id_of.items()
            if base_wild_counts.get(i)
        )[:40]:
            print(f"    {name:20s} {base_wild_counts[unit_id]}")
        print(
            f"기준선: P15 둥지 {base_nests}개, 야생 병력 {len(base_wild_army)}기, "
            f"알파 둥지 {'발견 ' + str(tuple(round(v) for v in alpha_pos)) if alpha_pos else '없음'}"
        )

        limit_loops = int(minutes * 60 * GAME_LOOPS_PER_SECOND)
        step_loops = 672  # 30 게임초
        peak = {}
        wild_peak = Counter()
        new_wild_tags: dict[str, set[int]] = {}
        max_raiders = 0
        max_alpha_army = 0
        intrusion_samples = 0
        defense_samples = 0
        ended_early = False

        print(f"측정 시작: {minutes:g}게임분 (옵저버, 전략 브리지 없음)\n", flush=True)
        while True:
            await connection.step(step_loops)
            observation = await connection.observation(disable_fog=True)
            units = observation.observation.raw_data.units
            loop = observation.observation.game_loop
            elapsed = loop / GAME_LOOPS_PER_SECOND

            rows = summarize_lobby(units, sampler, army_ids)
            for runtime, row in rows.items():
                best = peak.setdefault(runtime, dict(row))
                for key, value in row.items():
                    best[key] = max(best[key], value)

            for unit in units:
                if (
                    1 <= unit.owner <= 14
                    and unit.unit_type in lobby_watch_ids
                    and unit.tag not in base_lobby_tags
                ):
                    lobby_new.setdefault(unit.owner, {}).setdefault(
                        lobby_watch_ids[unit.unit_type], set()
                    ).add(unit.tag)

            wild = [unit for unit in units if unit.owner == P15]
            wild_counts = Counter(unit.unit_type for unit in wild)
            for name, unit_id in wild_names.items():
                wild_peak[name] = max(wild_peak[name], wild_counts[unit_id])
            # 신규 생산분: t=0 이후 처음 본 태그만 센다(선배치와 분리).
            for unit in wild:
                if unit.tag in base_wild_tags:
                    continue
                name = sampler.name_of.get(unit.unit_type)
                if name in wild_names:
                    new_wild_tags.setdefault(name, set()).add(unit.tag)

            nests = [unit for unit in wild if unit.unit_type in sampler.nest_ids]
            nest_pos = [(unit.pos.x, unit.pos.y) for unit in nests]
            wild_army = [
                unit for unit in wild if unit.unit_type in sampler.wild_army_ids
            ]
            raiders = 0
            for unit in wild_army:
                pos = (unit.pos.x, unit.pos.y)
                if nest_pos and min(_dist(pos, n) for n in nest_pos) > RAID_DISTANCE:
                    raiders += 1
            max_raiders = max(max_raiders, raiders)

            alpha_army = 0
            if alpha_pos is not None:
                alpha_army = sum(
                    1
                    for unit in wild_army
                    if _dist((unit.pos.x, unit.pos.y), alpha_pos) <= 28.0
                )
                max_alpha_army = max(max_alpha_army, alpha_army)

            # 침입/방어: 로비 플레이어 유닛이 둥지 반경 안에 있는가, 그때 야생
            # 병력도 같은 반경에 있는가.
            intruders = 0
            for unit in units:
                if not 1 <= unit.owner <= 14 or unit.is_flying:
                    continue
                if unit.unit_type in sampler.worker_ids:
                    continue
                pos = (unit.pos.x, unit.pos.y)
                if nest_pos and min(_dist(pos, n) for n in nest_pos) <= INTRUSION_RADIUS:
                    intruders += 1
            if intruders:
                intrusion_samples += 1
                defenders = sum(
                    1
                    for unit in wild_army
                    if nest_pos
                    and min(_dist((unit.pos.x, unit.pos.y), n) for n in nest_pos)
                    <= INTRUSION_RADIUS
                )
                if defenders:
                    defense_samples += 1

            terran_addons = {
                label[r]: rows.get(r, {}).get("addons", 0)
                for r, s in slot_of_runtime.items()
                if s.race == "Terran"
            }
            body = " ".join(
                f"{label[r].split('(')[0]}:{rows.get(r,{}).get('army',0)}/"
                f"{rows.get(r,{}).get('workers',0)}w/{rows.get(r,{}).get('halls',0)}h"
                for r in sorted(rows)
            )
            print(
                f"[{elapsed:5.0f}s] {body}\n"
                f"         P15 둥지{len(nests)} 병력{len(wild_army)} "
                f"원정{raiders} 알파{alpha_army} 드론{wild_counts[sampler.id_of.get('Drone',-1)]} "
                f"| 테란애드온 {sum(terran_addons.values())}",
                flush=True,
            )

            if observation.player_result:
                print(f"\n게임 종료 판정 (t={elapsed:.0f}s)")
                ended_early = elapsed < minutes * 60 * 0.95
                break
            if loop >= limit_loops:
                break

        # ---------------------------------------------------------- 요약
        print("\n=== 요약 (구간 최대값) ===")
        print(f"{'슬롯':28s} {'병력':>5s} {'일꾼':>5s} {'기지':>4s} {'생산':>4s} {'애드온':>6s}")
        for runtime in sorted(peak):
            best = peak[runtime]
            print(
                f"{label[runtime]:28s} {best['army']:5d} {best['workers']:5d} "
                f"{best['halls']:4d} {best['production']:4d} {best['addons']:6d}"
            )

        print("\n=== 슬롯별 병종 신규 생산 (태그 누적 — 사망 포함 총 생산량) ===")
        for runtime in sorted(peak):
            per_type = lobby_new.get(runtime, {})
            body = " ".join(
                f"{name}:{len(tags)}"
                for name, tags in sorted(per_type.items(), key=lambda kv: -len(kv[1]))
            )
            print(f"  {label[runtime]:28s} {body if body else '(신규 병력 없음)'}")

        print("\n=== P15 야생 저그 ===")
        print(f"  {'유형':16s} {'선배치':>6s} {'최대':>5s} {'신규생산':>8s}")
        for name in WILD_STRUCTURE_NAMES + ("Drone", "Overlord") + WILD_ARMY_NAMES:
            unit_id = sampler.id_of.get(name)
            if unit_id is None:
                continue
            base = base_wild_counts.get(unit_id, 0)
            fresh = len(new_wild_tags.get(name, ()))
            if base or wild_peak[name] or fresh:
                print(f"  {name:16s} {base:6d} {wild_peak[name]:5d} {fresh:8d}")
        print("  (신규생산 = t=0 이후 새로 나타난 태그. 선배치와 무관하게 실제로 만든 수)")
        print(f"  둥지 최초 {base_nests}개")
        print(f"  둥지 밖 원정 최대 {max_raiders}기 (공격 활동)")
        print(f"  알파 둥지 병력 최대 {max_alpha_army}기")
        print(f"  침입 관측 {intrusion_samples}회 중 방어 병력 존재 {defense_samples}회")

        print(f"\n조기 종료: {'예' if ended_early else '아니오'}")
        print("MEASURE_FIELD_STATE=DONE")
    finally:
        if connection is not None:
            await connection.quit()
            await connection.close()
        stop_process(process)
        print(f"SC2 exit_code={process.poll()}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
