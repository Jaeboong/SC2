"""야생 저그(P15)가 V2에서 실제로 경제를 도는가.

사용자 관측: "드론도 안뽑고 병력들만 대충 움직인다."

CLAUDE.md 규칙대로 소스를 읽어 추론하지 않고 엔진이 뭘 하는지 센다.
§89.5~89.12 에서 코드만 보고 5연속 오진한 전례가 있다.

    python v2/verification/probe_wild_zerg.py [hold|nohold]

찍는 것
  - 드론 수 / **명령 없는 드론 수** (채취를 아예 안 하면 여기서 드러난다)
  - 알 수 (생산이 돌고 있으면 0 이 아니다)
  - 유충 수 (쌓이기만 하면 생산을 안 하는 것)
  - 해처리 계열 수, 병력 보급값
  - 선배치 전투 유닛이 처음 자리에서 얼마나 움직였는가 (고정 기능 검증)
"""

from __future__ import annotations

import asyncio
import math
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
for extra in (PROJECT_ROOT, PROJECT_ROOT / "v2"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from s2clientprotocol import sc2api_pb2 as sc_pb  # noqa: E402

from sc2team.custom_config import CustomLauncherConfig, SlotConfig  # noqa: E402
from sc2team.custom_runtime import player_setups  # noqa: E402
from sc2team.process import (  # noqa: E402
    discover_sc2_executable,
    launch_sc2,
    stop_process,
)
from sc2team.protocol import Sc2Connection  # noqa: E402
from sc2team_v2.config import V2Assist  # noqa: E402
from sc2team_v2.runtime import build_v2_map  # noqa: E402

BASE_MAP = (
    PROJECT_ROOT
    / "map"
    / "source"
    / "europe-melee-2-7v7-rich-50000-fixed-teams.SC2Map"
)
PORT = 14133
WILD = 15
ALPHA = (237.5, 240.5)   # 1시 본진(시작 지점)

# 경제 유닛은 고정 대상이 아니다. 나머지 비건물이 전투 유닛이다.
ECONOMY_TYPES = {"Drone", "Larva", "Egg", "Overlord", "OverlordTransport", "Overseer"}
HALL_TYPES = {"Hatchery", "Lair", "Hive"}


def make_config() -> CustomLauncherConfig:
    # P15 와 실제로 접촉이 나야 "적으로 보는가" 를 잴 수 있으므로 슬롯을 넉넉히
    # 채운다. 2명짜리로는 아무도 1시까지 안 온다.
    layout = {
        1: ("human", "Terran"),
        2: ("custom_ai", "Protoss"),
        3: ("custom_ai", "Zerg"),
        4: ("custom_ai", "Terran"),
        5: ("custom_ai", "Protoss"),
        8: ("custom_ai", "Terran"),
        9: ("custom_ai", "Protoss"),
        10: ("custom_ai", "Zerg"),
        11: ("custom_ai", "Terran"),
        12: ("custom_ai", "Protoss"),
    }
    slots = []
    for index in range(1, 15):
        controller, race = layout.get(index, ("empty", "Random"))
        slots.append(
            SlotConfig(
                slot=index,
                controller=controller,
                team=1 if index <= 7 else 2,
                race=race,
                build="random_ground",
            )
        )
    config = CustomLauncherConfig(version=1, slots=tuple(slots), wild_zerg=True)
    config.validate()
    return config


async def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "hold"
    assist = V2Assist(hold_wild_units=(mode == "hold"))
    config = make_config()
    probe_map = PROJECT_ROOT / "runtime" / "maps" / f"v2-wild-{mode}.SC2Map"

    print(f"=== 야생 저그 프로브 mode={mode} · {assist.summary()} ===")
    build_v2_map(
        PROJECT_ROOT, BASE_MAP, probe_map, config, assist,
        observer_mode=True, active_config_file=probe_map.with_suffix(".json"),
    )

    process = launch_sc2(discover_sc2_executable(), PORT, 0)
    connection: Sc2Connection | None = None
    try:
        connection = await Sc2Connection.open(PORT)
        await connection.create_game_with_setups(
            probe_map.name, probe_map.read_bytes(),
            player_setups(config, observer=True), realtime=False,
        )
        await connection.join_as_observer()

        request = sc_pb.Request()
        request.data.CopyFrom(sc_pb.RequestData(unit_type_id=True))
        udata = {u.unit_id: u for u in (await connection.request(request)).data.units}

        # **첫 관측 시점의 유닛만** 선배치 코호트로 고정한다. 이후 생산된 유닛을
        # 여기 넣으면 "움직였다"가 정상 동작까지 세어 계측이 무의미해진다
        # (첫 판에서 실제로 그렇게 158 이 나왔다 — 대부분 새로 뽑은 저글링).
        cohort: dict[int, tuple[float, float]] = {}
        cohort_locked = False
        elapsed = 0.0
        print()
        print(
            "  시각   드론 무명령 알 유충  해처리 병력보급  1시반경30 전투  "
            "움직인선배치/생존  적침입 P15피해"
        )
        # **게임 내 시계** 기준이다. SC2 "빠르게"에서 게임 시계는 16루프당 1초로
        # 흐르고(초당 22.4루프이므로 실시간의 1.4배), Galaxy 의 c_timeGame 과
        # AIGetTime() 도 이 기준을 쓴다. 루프/22.4 로 라벨을 붙이면 트리거 시각과
        # 1.4배 어긋나 "9분 해제"가 8분에 일어난 것처럼 보인다(실제로 겪었다).
        for minute in (0.5, 4, 8.5, 9.5, 12, 16, 20):
            await connection.step(max(1, int((minute * 60 - elapsed) * 16.0)))
            elapsed = minute * 60.0
            observation = await connection.observation(disable_fog=True)

            types: Counter[str] = Counter()
            drones = idle_drones = 0
            halls = larvae = eggs = 0
            army_supply = 0.0
            near_alpha_combat = 0
            moved = 0
            seen_tags: set[int] = set()
            # "다른 플레이어가 P15 를 적으로 보는가" 의 직접 증거 두 가지:
            #   침입 = P15 본진 반경 30 안에 들어온 P1~P14 유닛 수
            #   피해 = 체력이 깎인 P15 유닛 수 (누가 쐈다는 뜻)
            intruders = 0
            damaged = 0
            for unit in observation.observation.raw_data.units:
                if unit.owner != WILD:
                    if 1 <= unit.owner <= 14:
                        if math.dist((unit.pos.x, unit.pos.y), ALPHA) <= 30:
                            intruders += 1
                    continue
                if unit.health_max > 0 and unit.health < unit.health_max - 0.5:
                    damaged += 1
                seen_tags.add(unit.tag)
                info = udata.get(unit.unit_type)
                name = info.name if info else str(unit.unit_type)
                types[name] += 1
                if name == "Drone":
                    drones += 1
                    if not unit.orders:
                        idle_drones += 1
                elif name == "Larva":
                    larvae += 1
                elif name == "Egg":
                    eggs += 1
                if name in HALL_TYPES:
                    halls += 1
                is_structure = bool(info and info.food_provided == 0 and info.movement_speed == 0)
                if name not in ECONOMY_TYPES and not is_structure:
                    if info and info.food_required > 0:
                        army_supply += info.food_required
                    position = (unit.pos.x, unit.pos.y)
                    if math.dist(position, ALPHA) <= 30:
                        near_alpha_combat += 1
                    if not cohort_locked:
                        cohort[unit.tag] = position
                    elif unit.tag in cohort and math.dist(cohort[unit.tag], position) > 10.0:
                        moved += 1

            alive = sum(1 for tag in cohort if tag in seen_tags)
            print(
                f"  {minute:4.1f}분 {drones:5d} {idle_drones:6d} {eggs:3d} {larvae:5d} "
                f"{halls:7d} {army_supply:8.0f} {near_alpha_combat:12d} "
                f"{moved:8d}/{alive:<5d} {intruders:6d} {damaged:6d}"
            )
            cohort_locked = True
        print()
        print("  P15 유닛 구성:",
              ", ".join(f"{name} x{count}" for name, count in types.most_common(12)))
        return 0
    finally:
        if connection is not None:
            try:
                await connection.quit()
            except Exception:
                pass
        stop_process(process)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
