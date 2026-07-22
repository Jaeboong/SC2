from __future__ import annotations

import json
import subprocess
from pathlib import Path

from s2clientprotocol import common_pb2 as common_pb
from s2clientprotocol import sc2api_pb2 as sc_pb

from .custom_config import CustomLauncherConfig, SlotConfig
from .protocol import GamePlayerSetup


RACE_VALUES: dict[str, int] = {
    "Random": common_pb.Random,
    "Terran": common_pb.Terran,
    "Zerg": common_pb.Zerg,
    "Protoss": common_pb.Protoss,
}

AI_BUILD_BY_STRATEGY: dict[str, int] = {
    "bio": sc_pb.Rush,
    "gateway": sc_pb.Rush,
    "ling_bane": sc_pb.Rush,
    "bio_tank": sc_pb.Timing,
    "hellion_tank": sc_pb.Timing,
    "stalker_immortal": sc_pb.Timing,
    "zealot_archon": sc_pb.Timing,
    "roach_ravager": sc_pb.Timing,
    "roach_hydra": sc_pb.Timing,
    "thor_tank": sc_pb.Power,
    "immortal_colossus": sc_pb.Power,
    "disruptor_ground": sc_pb.Power,
    "hydra_lurker": sc_pb.Power,
    "ultra_ling_bane": sc_pb.Power,
    "mech_macro": sc_pb.Macro,
    "random_ground": sc_pb.Macro,
}

# 런처에서 슬롯마다 직접 고른 멜레 빌드 분류 → AIBuild enum.
# 세부 빌드(4관문 타이밍 등 62종)는 로비 속성이라 API 로 못 넘긴다. 넘길 수 있는
# 것은 이 6개 분류까지이고, 그 안에서 무엇이 나올지는 밀레 AI 가 정한다.
MELEE_BUILD_VALUES: dict[str, int] = {
    "RandomBuild": sc_pb.RandomBuild,
    "Rush": sc_pb.Rush,
    "Timing": sc_pb.Timing,
    "Power": sc_pb.Power,
    "Macro": sc_pb.Macro,
    "Air": sc_pb.Air,
}


def ai_build_for(slot) -> int:
    """슬롯이 로비에 넘길 AIBuild 값. 직접 지정이 있으면 그것이 우선한다."""

    chosen = getattr(slot, "melee_build", "")
    if chosen:
        return MELEE_BUILD_VALUES[chosen]
    return AI_BUILD_BY_STRATEGY[slot.build]


def runtime_slots(config: CustomLauncherConfig) -> tuple[SlotConfig, ...]:
    """SC2 promotes the sole Participant to runtime P1, then places Computers."""

    config.validate()
    return (config.human,) + tuple(
        slot for slot in config.active_slots if slot.controller == "custom_ai"
    )


def player_setups(
    config: CustomLauncherConfig, *, observer: bool = False
) -> tuple[GamePlayerSetup, ...]:
    """Return the engine's Participant-first runtime player order.

    §66 옵저버 모드(observer=True): 사람 슬롯도 진짜 컴퓨터로 만들고 맨 끝에
    Observer 항목을 붙인다. Participant가 없어도 컴퓨터들은 지금과 같은 순서
    (사람 슬롯 먼저 = 런타임 P1)로 배정된다(엔진 실측). 참가자에게 AIStart로
    멜레 AI를 붙이는 방법은 엔진이 무시하므로(§66) 이 길이 유일하다.
    """

    config.validate()
    setups = []
    for slot in runtime_slots(config):
        if slot.controller == "human" and observer:
            setups.append(
                GamePlayerSetup(
                    player_type=sc_pb.Computer,
                    race=RACE_VALUES[slot.race],
                    difficulty=sc_pb.VeryHard,
                    ai_build=ai_build_for(slot),
                    player_name=f"P{slot.slot} Custom AI",
                )
            )
        elif slot.controller == "human":
            setups.append(
                GamePlayerSetup(
                    player_type=sc_pb.Participant,
                    player_name=f"P{slot.slot} Local Human",
                )
            )
        else:
            # Blizzard's elite melee AI supplies economy, production, and local
            # tactics. Our external strategy controller overrides army-level
            # decisions through the map command bridge.
            setups.append(
                GamePlayerSetup(
                    player_type=sc_pb.Computer,
                    race=RACE_VALUES[slot.race],
                    difficulty=sc_pb.VeryHard,
                    ai_build=ai_build_for(slot),
                    player_name=f"P{slot.slot} Custom AI",
                )
            )
    # §90 야생 저그: 맵 플레이어 15는 중립 적대(Hostile)가 아니라 진짜 로비
    # 컴퓨터 슬롯이다. 빌더가 MapInfo에서 control을 1로 올리고 1시 본진 자리의
    # 시작 지점을 배정하므로, CreateGame 설정에도 대응하는 항목이 있어야 한다
    # (설정은 플레이 가능한 맵 슬롯 순서대로 배정되고, 15번이 마지막이다).
    #
    # 중립 적대로는 전투 유닛을 어떤 경로로도 생산할 수 없다 — 프로브 12판으로
    # 확정했다. 승격 후 같은 구성에서 6게임분에 바퀴 +28·히드라 +11·저글링 +7이
    # 나왔고, 승격 전에는 같은 시간 동안 1기도 늘지 않았다.
    #
    # §93: 야생 저그를 끄면 이 항목을 빼야 한다. 빌더도 같은 플래그로 MapInfo
    # 승격과 시작 지점 배정을 건너뛰므로 P15는 다시 로비 밖 중립 적대가 되고,
    # 여기에 Computer 항목이 남아 있으면 슬롯 수가 맞지 않는다. 승격을 되돌리는
    # 것이 "생산 금지"의 핵심이다 — P15가 로비 컴퓨터로 남아 있으면 우리가 맵
    # 트리거를 비워도 블리자드 멜레 AI가 대신 생산한다.
    if config.wild_zerg:
        setups.append(
            GamePlayerSetup(
                player_type=sc_pb.Computer,
                race=RACE_VALUES["Zerg"],
                difficulty=sc_pb.VeryHard,
                player_name="P15 야생 저그",
            )
        )
    if observer:
        setups.append(
            GamePlayerSetup(player_type=sc_pb.Observer, player_name="관전자")
        )
    return tuple(setups)


def runtime_player_id(config: CustomLauncherConfig, logical_slot: int) -> int:
    """Translate a GUI location slot to SC2's compact consecutive player ID."""

    config.validate()
    for runtime_id, slot in enumerate(runtime_slots(config), start=1):
        if slot.slot == logical_slot:
            return runtime_id
    raise ValueError(f"P{logical_slot} is not active")


def stock_targets_path(output_map: Path) -> Path:
    """빌더가 출력 맵 옆에 남기는 목표 재고 사이드카 경로."""

    return output_map.with_name(output_map.name + ".targets.json")


def load_stock_targets(output_map: Path) -> list[dict]:
    """사이드카에서 슬롯별 목표 재고(해석 완료 값)를 읽는다.

    각 항목은 {runtime_player, logical_slot, build, race,
    stock: {유닛이름: {count, perExpansion}}} 형태다. perExpansion은 빌더가
    경제 규칙과 같은 공식으로 미리 계산한 값이라 파이썬에 공식 미러가 없다.
    """

    path = stock_targets_path(output_map)
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") != 1:
        raise RuntimeError(
            f"목표 재고 사이드카 버전을 해석할 수 없습니다: {data.get('version')!r}"
        )
    return list(data["slots"])


def build_runtime_map(
    project_root: Path,
    source_map: Path,
    output_map: Path,
    config: CustomLauncherConfig,
    *,
    strategy_bridge: bool = False,
    bridge_probe: bool = False,
    campaign_units_pilot: bool = False,
    campaign_units_probe_damage: bool = False,
    research_probe: bool = False,
    observer_mode: bool = False,
    melee_only: bool = False,
    active_config_file: Path | None = None,
) -> Path:
    config.validate()
    runtime_dir = project_root / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    config_path = active_config_file or (runtime_dir / "custom_ai_active.json")
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_data = config.to_dict()
    if strategy_bridge:
        config_data["strategy_bridge"] = True
    if bridge_probe:
        config_data["bridge_probe"] = True
    if campaign_units_pilot:
        config_data["campaign_units_pilot"] = True
    if campaign_units_probe_damage:
        config_data["campaign_units_probe_damage"] = True
    if research_probe:
        # §63 연구 프로브: 사람 슬롯에도 연구 트리거를 적용하는 검증 전용 플래그.
        config_data["research_probe"] = True
    if observer_mode:
        # §66 옵저버 모드: 사람 슬롯을 멜레 AI(AIStart)와 커스텀 AI 규칙이
        # 대신 플레이한다. 참가자·비콘 브리지·런타임 매핑은 그대로다.
        config_data["observer_mode"] = True
    if melee_only:
        # 성능 대조군: 팀 동맹과 Blizzard MeleeInitAI만 남기고 커스텀
        # 주기 트리거·명령 브리지·생산 조정을 전부 제외한다.
        config_data["melee_only"] = True
    config_path.write_text(
        json.dumps(config_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tool = project_root / "tools" / "build_custom_runtime_map.cjs"
    completed = subprocess.run(
        ["node", str(tool), str(source_map), str(output_map), str(config_path)],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(f"실행용 맵 생성 실패: {detail}")
    if not output_map.is_file():
        raise RuntimeError("맵 생성기는 성공했지만 출력 파일이 없습니다.")
    if not stock_targets_path(output_map).is_file():
        raise RuntimeError("맵 생성기가 목표 재고 사이드카를 남기지 않았습니다.")
    return output_map
