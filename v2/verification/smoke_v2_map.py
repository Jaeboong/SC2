"""V2 맵 T2 스모크: 스크립트가 실제로 컴파일되는가.

증상 판정은 `v2/docs/harness.md` 그대로다 — Galaxy 가 컴파일에 실패하면
`MeleeInitUnits()` 를 포함한 맵 초기화가 통째로 안 돌아서 **5초 시점에 모든
플레이어의 유닛이 0** 이 된다. 유닛이 정상이면 통과다.

    python v2/verification/smoke_v2_map.py

성공하면 exit 0, 실패하면 1.
"""

from __future__ import annotations

import asyncio
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(PROJECT_ROOT / "v2") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "v2"))

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
    / "maps"
    / "generated"
    / "europe-melee-2-7v7-rich-50000-fixed-teams.SC2Map"
)
PROBE_MAP = PROJECT_ROOT / "runtime" / "maps" / "v2-smoke.SC2Map"
PORT = 14131

# 무작위 종족을 일부러 섞는다 — 기본 프리셋이 전부 무작위라, 확장 보조의
# PlayerRace 분기가 실제로 도는 조건이 이쪽이다.
LAYOUT = {
    1: ("human", "Random"),
    2: ("custom_ai", "Terran"),
    3: ("custom_ai", "Random"),
    9: ("custom_ai", "Protoss"),
    10: ("custom_ai", "Zerg"),
    11: ("custom_ai", "Random"),
}


def make_config() -> CustomLauncherConfig:
    slots = []
    for index in range(1, 15):
        if index in LAYOUT:
            controller, race = LAYOUT[index]
        else:
            controller, race = "empty", "Random"
        slots.append(
            SlotConfig(
                slot=index,
                controller=controller,
                team=1 if index <= 7 else 2,
                race=race,
                build="random_ground",
            )
        )
    config = CustomLauncherConfig(version=1, slots=tuple(slots))
    config.validate()
    return config


async def main() -> int:
    config = make_config()
    # 미검증 경로를 **전부** 켜서 굽는다. T2 는 "컴파일되는가"만 보므로 가장
    # 위험한 조합을 태우는 것이 이득이다. 캠페인 유닛/생산은 기본값이 켜짐이라
    # 자동으로 포함된다(`AITechCount`·`TechTreeUnitAllow`·`SpawningPoolResearch`
    # 같은 새 식별자가 여기서 걸린다).
    assist = V2Assist(production_assist=True)
    assert assist.campaign_units and assist.campaign_production
    print(f"보조 설정: {assist.summary()}")

    build_v2_map(
        PROJECT_ROOT,
        BASE_MAP,
        PROBE_MAP,
        config,
        assist,
        observer_mode=True,
        active_config_file=PROBE_MAP.with_suffix(".json"),
    )

    process = launch_sc2(discover_sc2_executable(), PORT, 0)
    connection: Sc2Connection | None = None
    try:
        connection = await Sc2Connection.open(PORT)
        await connection.create_game_with_setups(
            PROBE_MAP.name,
            PROBE_MAP.read_bytes(),
            player_setups(config, observer=True),
            realtime=False,
        )
        await connection.join_as_observer()

        failures: list[str] = []
        for seconds in (5, 60):
            await connection.step(int(seconds * 22.4) if seconds == 5 else int(55 * 22.4))
            observation = await connection.observation(disable_fog=True)
            owners: Counter[int] = Counter()
            for unit in observation.observation.raw_data.units:
                owners[unit.owner] += 1
            playable = {owner: count for owner, count in owners.items() if owner <= 14}
            print(f"[{seconds}초] 플레이어별 유닛 = {dict(sorted(playable.items()))}")
            missing = [p for p in range(1, 6) if playable.get(p, 0) == 0]
            if missing:
                failures.append(
                    f"{seconds}초 시점에 유닛이 0인 런타임 플레이어: {missing}"
                )
        if failures:
            print("\n실패 — Galaxy 컴파일이 죽었을 때의 증상입니다:")
            for line in failures:
                print(f"  - {line}")
            return 1
        print("\n통과 — 맵 스크립트가 컴파일되고 초기화가 돌았습니다.")
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
