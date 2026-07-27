"""V3 전용 맵과 고정 custom-AI TriggerLib mod 빌드 조정자.

V1 공통 빌더는 맵/MapInfo/캠페인 데이터 계층만 담당한다. 이 모듈은 그 결과를
V3 임시 경로에서 받아 최소 부팅 실험 또는 커스텀 AI 모드로 마무리하고,
성공한 V3 산출물만 최종 경로로 승격한다.

V1/V2의 설정·출력 맵을 입력 또는 출력으로 사용하지 않는다.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from sc2team.custom_config import CustomLauncherConfig
from sc2team.custom_runtime import build_runtime_map, runtime_slots

from .config import (
    V3_BUILD_IDS,
    V3_GROUND_BUILDS,
    V3BuildConfig,
)


PATCHER = Path(__file__).resolve().parents[1] / "tools" / "patch_v3_ai.cjs"
MOD_BUILDER = Path(__file__).resolve().parents[1] / "tools" / "build_v3_ai_mod.cjs"
AI_MOD_NAME = "SC2TeamV3AI.SC2Mod"
AI_MOD_DEPENDENCY = f"file:Mods/{AI_MOD_NAME}"
PLAN_VERSION = 3


def v3_players(
    config: CustomLauncherConfig, *, observer_mode: bool
) -> list[dict[str, object]]:
    """Return the compact runtime IDs that V3 may bootstrap.

    ``runtime_slots`` is the single source of truth for SC2's participant-first
    compaction: the logical human slot is runtime P1 and custom-AI slots follow
    consecutively. In a normal game the human is a Participant, so only
    ``custom_ai`` entries are V3 targets. In observer mode the launcher turns
    that same human slot into a Computer; it therefore becomes a valid V3
    target at runtime P1. P15 is intentionally absent from this ordinary-player
    list. When wild Zerg is enabled it is represented by the plan's separate
    ``wild_zerg`` flag and may be the only Computer AI in a Participant game.
    """

    config.validate()
    players: list[dict[str, object]] = []
    for runtime_id, slot in enumerate(runtime_slots(config), start=1):
        is_computer = slot.controller == "custom_ai" or (
            observer_mode and slot.controller == "human"
        )
        if is_computer:
            players.append(
                {"slot": slot.slot, "runtime": runtime_id, "race": slot.race}
            )
    return players


def make_v3_plan(
    config: CustomLauncherConfig,
    v3_config: V3BuildConfig,
    *,
    observer_mode: bool = False,
) -> dict[str, object]:
    """Make the small, stable contract consumed by ``patch_v3_ai.cjs``."""

    config.validate()
    v3_config.validate()
    players = v3_players(config, observer_mode=observer_mode)
    if not players and not config.wild_zerg:
        raise ValueError("V3를 부팅할 Computer 슬롯이 없습니다.")
    selected = dict(v3_config.player_builds)
    player_by_slot = {int(player["slot"]): player for player in players}
    for slot, build in selected.items():
        player = player_by_slot.get(slot)
        if player is None:
            raise ValueError(f"P{slot}: Computer 슬롯이 아니므로 V3 빌드를 적용할 수 없습니다.")
        race = str(player["race"])
        if race == "Random":
            raise ValueError(f"P{slot}: V3 세부 빌드는 무작위 종족에 적용할 수 없습니다.")
        if build not in V3_GROUND_BUILDS.get(race, {}):
            raise ValueError(f"P{slot}: {race}에서 사용할 수 없는 V3 빌드 {build!r}")
        player["build"] = build
        player["build_id"] = V3_BUILD_IDS[build]
    return {
        "version": PLAN_VERSION,
        "ai_mode": v3_config.ai_mode,
        "bootstrap_mode": v3_config.bootstrap_mode,
        "campaign_units": v3_config.campaign_units,
        "wild_zerg": config.wild_zerg,
        "players": players,
        "mod_dependency": AI_MOD_DEPENDENCY,
    }


def v3_plan_path(output_map: Path) -> Path:
    """Return the V3-only plan sidecar path for an already-final map path."""

    return output_map.with_name(output_map.name + ".v3plan.json")


def _write_json(path: Path, data: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _run_patcher(project_root: Path, map_path: Path, plan_path: Path) -> None:
    if not PATCHER.is_file():
        raise FileNotFoundError(f"V3 Galaxy 패처를 찾을 수 없습니다: {PATCHER}")

    completed = subprocess.run(
        ["node", str(PATCHER), str(map_path), str(plan_path)],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=_node_environment(project_root),
    )
    if completed.returncode:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(f"V3 맵 패치 실패: {detail}")


def _node_environment(project_root: Path) -> dict[str, str]:
    """Return the shared Node dependency path used by all V3 tools."""

    env = dict(os.environ)
    shared_node_path = str(project_root / "tools" / "node_modules")
    if env.get("NODE_PATH"):
        env["NODE_PATH"] = shared_node_path + os.pathsep + env["NODE_PATH"]
    else:
        env["NODE_PATH"] = shared_node_path
    return env


def _run_mod_builder(project_root: Path, output_mod: Path, plan_path: Path) -> None:
    if not MOD_BUILDER.is_file():
        raise FileNotFoundError(f"V3 AI mod 빌더를 찾을 수 없습니다: {MOD_BUILDER}")
    completed = subprocess.run(
        ["node", str(MOD_BUILDER), str(output_mod), str(plan_path)],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=_node_environment(project_root),
    )
    if completed.returncode:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(f"V3 AI mod 빌드 실패: {detail}")


def v3_mod_path(project_root: Path) -> Path:
    return project_root.resolve() / "runtime" / "mods" / AI_MOD_NAME


def install_v3_mod(project_root: Path, sc2_data_directory: Path) -> Path:
    source = v3_mod_path(project_root)
    if not source.is_file():
        raise FileNotFoundError(f"빌드된 V3 AI mod를 찾을 수 없습니다: {source}")
    destination_directory = sc2_data_directory.resolve() / "Mods"
    destination_directory.mkdir(parents=True, exist_ok=True)
    destination = destination_directory / AI_MOD_NAME
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{AI_MOD_NAME}.", suffix=".tmp", dir=destination_directory
    )
    os.close(handle)
    temporary = Path(temporary_name)
    try:
        shutil.copy2(source, temporary)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def build_v3_map(
    project_root: Path,
    source_map: Path,
    output_map: Path,
    config: CustomLauncherConfig,
    v3_config: V3BuildConfig,
    *,
    observer_mode: bool = False,
    active_config_file: Path | None = None,
    output_mod: Path | None = None,
) -> Path:
    """Build a V3-only map and atomically publish the final map when possible.

    The common builder always writes a V1-format active-config and targets
    sidecar. Both are confined to a V3 temporary directory during this build.
    ``active_config_file`` is optional V3 caller state; when supplied, it is
    written only after a successful map build and never used as the common
    builder's scratch path.
    """

    config.validate()
    v3_config.validate()
    if not source_map.is_file():
        raise FileNotFoundError(f"기준 맵을 찾을 수 없습니다: {source_map}")
    if source_map.resolve() == output_map.resolve():
        raise ValueError("V3 기준 맵과 출력 맵은 서로 달라야 합니다.")

    plan = make_v3_plan(config, v3_config, observer_mode=observer_mode)
    output_map.parent.mkdir(parents=True, exist_ok=True)
    work_dir = Path(
        tempfile.mkdtemp(prefix="sc2-v3-build-", dir=str(output_map.parent))
    )
    staged_map = work_dir / output_map.name
    staged_plan = v3_plan_path(staged_map)
    staged_common_config = work_dir / "common-builder-config.json"
    final_plan = v3_plan_path(output_map)
    final_mod = output_mod or v3_mod_path(project_root)
    staged_mod = work_dir / AI_MOD_NAME
    try:
        # V1's builder remains read-only as source code. melee_only leaves the
        # sole MeleeInitAI call in place for the V3 patcher while retaining its
        # MapInfo, faction, supply, campaign-data, and team-map layers.
        build_runtime_map(
            project_root,
            source_map,
            staged_map,
            config,
            melee_only=True,
            campaign_units_pilot=v3_config.campaign_units,
            observer_mode=observer_mode,
            active_config_file=staged_common_config,
        )
        _write_json(staged_plan, plan)
        _run_mod_builder(project_root, staged_mod, staged_plan)
        _run_patcher(project_root, staged_map, staged_plan)
        if not staged_map.is_file():
            raise RuntimeError("V3 패처가 성공했지만 스테이징 맵이 없습니다.")
        if not staged_mod.is_file():
            raise RuntimeError("V3 AI mod 빌더가 성공했지만 스테이징 mod가 없습니다.")

        # os.replace is atomic for these same-volume paths. The plan is a
        # diagnostic/reproducibility sidecar; the map itself remains usable if
        # an OS error occurs while publishing the sidecar.
        final_mod.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staged_mod, final_mod)
        os.replace(staged_map, output_map)
        os.replace(staged_plan, final_plan)
        if active_config_file is not None:
            _write_json(
                active_config_file,
                {
                    "version": PLAN_VERSION,
                    "launcher": config.to_dict(),
                    "v3": v3_config.to_dict(),
                    "observer_mode": observer_mode,
                },
            )
        return output_map
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


__all__ = [
    "AI_MOD_DEPENDENCY",
    "AI_MOD_NAME",
    "MOD_BUILDER",
    "PATCHER",
    "PLAN_VERSION",
    "build_v3_map",
    "install_v3_mod",
    "make_v3_plan",
    "v3_plan_path",
    "v3_mod_path",
    "v3_players",
]
