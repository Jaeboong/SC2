"""V2 실행용 맵 생성.

두 단계다.

1. V1 빌더를 `melee_only=True` 로 호출한다. 이 모드는 팀 동맹·전체 시야·
   인구 상한·프로토스 진영·야생 저그 승격은 유지하고, 우리 주기 트리거·명령
   브리지·생산 조정을 **전부** 뺀다. 즉 블리자드 멜레 AI 가 온전히 게임을
   맡는 상태다.
2. 그 맵에 V2 보조 트리거만 주입한다 (`v2/tools/patch_v2_assist.cjs`).

V1 코드는 읽기만 하고 고치지 않는다. V2 맵은 자기 파일 이름으로 굽고 V1
릴리스 맵과 설정 파일은 건드리지 않는다.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from sc2team.custom_config import CustomLauncherConfig
from sc2team.custom_runtime import build_runtime_map, runtime_slots

from .config import V2Assist


PATCHER = Path(__file__).resolve().parents[1] / "tools" / "patch_v2_assist.cjs"


def assist_players(
    config: CustomLauncherConfig, *, observer: bool
) -> list[dict[str, object]]:
    """보조를 받을 런타임 플레이어 목록.

    사람 슬롯은 참가자라 멜레 AI 가 붙지 않으므로 제외한다 — §66 에서 측정한
    대로 참가자에게 `AIStart` 계열을 걸면 엔진이 조용히 무시한다. 보조를 걸어도
    받을 주체가 없다.

    옵저버 모드에서는 사람 슬롯도 진짜 컴퓨터가 되므로 포함한다. V1 이 연구·
    생산 트리거에 두는 옵저버 예외와 같은 규칙이다.
    """

    players: list[dict[str, object]] = []
    for runtime_id, slot in enumerate(runtime_slots(config), start=1):
        is_ai = slot.controller == "custom_ai" or (
            observer and slot.controller == "human"
        )
        if not is_ai:
            continue
        players.append(
            {"runtime": runtime_id, "slot": slot.slot, "race": slot.race}
        )
    return players


def build_v2_map(
    project_root: Path,
    source_map: Path,
    output_map: Path,
    config: CustomLauncherConfig,
    assist: V2Assist,
    *,
    observer_mode: bool = False,
    active_config_file: Path | None = None,
) -> Path:
    config.validate()
    assist.validate()

    build_runtime_map(
        project_root,
        source_map,
        output_map,
        config,
        melee_only=True,
        # 캠페인 유닛은 `melee_only` 와 독립적인 플래그다. 이걸 켜면 V1 빌더가
        # 의존성(DocumentInfo + DocumentHeader) · 로스터 카탈로그 · **업그레이드
        # 연결**(roster/UpgradeData.xml) 을 한 묶음으로 넣는다. 셋 중 하나라도
        # 빠지면 조용히 깨진다 — 의존성이 없으면 테란 3종이 회색 구체가 되고,
        # 업그레이드 연결이 없으면 공방업이 새 유닛에 안 붙는다.
        #
        # 여기서 켜도 V1 의 주기 트리거(생산 규칙·구매·연구)는 안 들어온다.
        # 그것들은 `strategy_bridge` 쪽에 묶여 있고 `melee_only` 가 막는다.
        # 생산은 아래 V2 자체 훈련 명령이 맡는다.
        campaign_units_pilot=assist.campaign_units,
        observer_mode=observer_mode,
        active_config_file=active_config_file,
    )

    players = assist_players(config, observer=observer_mode)
    plan = {
        "expansion": {
            "enabled": bool(assist.expansion_assist and players),
            "cap": assist.expansion_cap,
            "period": assist.expansion_period,
        },
        "army": {
            "enabled": bool(assist.army_assist and players),
            "scale": assist.army_scale,
            "period": assist.army_period,
        },
        # 야생 저그가 꺼져 있으면 P15 는 로비 밖 중립 적대라 밀레 AI 가 굴리지
        # 않는다. 뺏을 제어권 자체가 없으므로 건너뛴다.
        "production": {
            "enabled": bool(assist.production_assist and players),
            "scale": assist.production_scale,
            "period": assist.production_period,
        },
        "hold_wild": {
            "enabled": bool(assist.hold_wild_units and config.wild_zerg),
            "release_seconds": assist.hold_wild_release_seconds,
        },
        "campaign": {
            "enabled": bool(
                assist.campaign_units and assist.campaign_production and players
            ),
            "period": assist.campaign_period,
        },
        "players": players,
    }
    plan_path = output_map.with_name(output_map.name + ".v2plan.json")
    plan_path.write_text(
        json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # node 는 스크립트 위치에서 위로 올라가며 node_modules 를 찾는다. 패처가
    # v2/tools/ 에 있어서 저장소의 tools/node_modules 에 닿지 못하므로
    # NODE_PATH 로 직접 알려준다. .cmd 가 아니라 여기서 하는 이유는 런처를
    # .py 로 직접 실행해도 동작해야 하기 때문이다.
    env = dict(os.environ)
    env["NODE_PATH"] = str(project_root / "tools" / "node_modules")
    completed = subprocess.run(
        ["node", str(PATCHER), str(output_map), str(plan_path)],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    if completed.returncode:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(f"V2 보조 주입 실패: {detail}")
    return output_map
