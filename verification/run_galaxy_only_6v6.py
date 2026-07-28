"""§101 후속 대조군: 커스텀 Galaxy는 켜고 관측/전략만 끈 6v6 관전 실행.

§101 의 순수 밀리 대조군(`run_melee_only_6v6.py`)에서 끊김이 사라졌으므로 원인은
(a) 커스텀 주기 Galaxy 런타임 또는 (b) 전체 raw observation 생성/직렬화 중 하나다.
이 스크립트는 **오직 그 하나만** 바꾼다: 맵을 릴리스와 동일한 플래그
(`strategy_bridge` + `campaign_units_pilot`)로 빌드해 커스텀 생산·경제·확장·연구·
유지보수 트리거를 전부 살리고, 참가 이후에는 §101 과 똑같이 SC2 API 요청을 한 번도
보내지 않는다(관측·계측·step·debug·리플레이·전략 갱신 없음).

  끊김이 돌아오면  -> 원인은 커스텀 Galaxy 주기 로직
  계속 매끄러우면  -> 원인은 전체 raw observation 경로

나머지 조건은 §101 과 동일하게 고정한다: 저장 설정의 P1~P6 대 P8~P13, 야생 저그
OFF, 전체 시야 OFF, 전체화면, realtime 15분. 수치 계측은 의도적으로 하지 않는다 —
관측을 보내는 순간 이 대조군의 의미가 사라진다. 판정은 사용자 육안 관찰이다.
"""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import replace
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sc2team.custom_config import CustomLauncherConfig, SlotConfig
from sc2team.custom_runtime import build_runtime_map, player_setups
from sc2team.process import discover_sc2_executable, launch_sc2, stop_process
from sc2team.protocol import Sc2Connection


SETTINGS_FILE = PROJECT_ROOT / "runtime" / "custom_ai_settings.json"
BASE_MAP_FILE = (
    PROJECT_ROOT
    / "map"
    / "source"
    / "europe-melee-2-7v7-rich-50000-fixed-teams.SC2Map"
)
OUTPUT_MAP = PROJECT_ROOT / "runtime" / "maps" / "diagnostic-galaxy-only-6v6.SC2Map"
ACTIVE_CONFIG = PROJECT_ROOT / "runtime" / "diagnostic-galaxy-only-6v6.json"
RUN_SECONDS = 15 * 60


def diagnostic_config() -> CustomLauncherConfig:
    """§101 과 같은 슬롯 구성. 바뀌는 것은 맵 빌드 플래그뿐이다."""

    saved = CustomLauncherConfig.from_dict(
        json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    )
    slots: list[SlotConfig] = []
    for slot in saved.slots:
        active = slot.slot in {*range(1, 7), *range(8, 14)}
        controller = "human" if slot.slot == 1 else "custom_ai" if active else "empty"
        slots.append(replace(slot, controller=controller))
    return replace(
        saved,
        slots=tuple(slots),
        wild_zerg=False,
        full_vision=False,
        fullscreen=True,
    )


async def run() -> None:
    config = diagnostic_config()
    build_runtime_map(
        PROJECT_ROOT,
        BASE_MAP_FILE,
        OUTPUT_MAP,
        config,
        strategy_bridge=True,
        campaign_units_pilot=True,
        observer_mode=True,
        active_config_file=ACTIVE_CONFIG,
    )
    process = launch_sc2(discover_sc2_executable(), 14121, 0, fullscreen=True)
    connection: Sc2Connection | None = None
    try:
        connection = await Sc2Connection.open(14121)
        await connection.ping()
        await connection.create_game_with_setups(
            OUTPUT_MAP.name,
            OUTPUT_MAP.read_bytes(),
            player_setups(config, observer=True),
            realtime=True,
        )
        await connection.join_as_observer("6v6 Galaxy-only Observer")
        print(
            "GALAXY_ONLY_6V6_STARTED: 900 seconds, custom Galaxy runtime ON, "
            "no observations or strategy after join",
            flush=True,
        )
        deadline = asyncio.get_running_loop().time() + RUN_SECONDS
        while process.poll() is None and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(1.0)
        print("GALAXY_ONLY_6V6_FINISHED", flush=True)
        if process.poll() is None:
            await connection.quit()
    finally:
        stop_process(process)


if __name__ == "__main__":
    asyncio.run(run())
