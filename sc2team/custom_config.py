from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


CONTROLLERS: dict[str, str] = {
    "empty": "비어 있음",
    "human": "사람",
    "custom_ai": "커스텀 AI",
}

RACES: dict[str, str] = {
    "Random": "무작위",
    "Terran": "테란",
    "Zerg": "저그",
    "Protoss": "프로토스",
}

PROTOSS_FACTIONS: dict[str, str] = {
    "Standard": "기본 프로토스",
    "Aiur": "아이어",
    "Nerazim": "네라짐",
    "Purifier": "정화자",
    "Taldarim": "탈다림",
}

# These are controller strategy identifiers, not Blizzard's coarse AIBuild enum.
# Combat air production is intentionally absent. Transport/detection support is
# allowed by the strategy controller when a build needs it.
GROUND_BUILDS: dict[str, dict[str, str]] = {
    "Random": {
        "random_ground": "무작위 지상 전략",
    },
    "Terran": {
        "bio": "해병·불곰 중심",
        "bio_tank": "해병·불곰·공성전차",
        "hellion_tank": "화염차·공성전차",
        "thor_tank": "토르·공성전차",
        "mech_macro": "메카닉 자원 확장",
        "random_ground": "무작위 지상 전략",
    },
    "Protoss": {
        "gateway": "관문 병력 중심",
        "stalker_immortal": "추적자·불멸자",
        "zealot_archon": "광전사·집정관",
        "immortal_colossus": "불멸자·거신",
        "disruptor_ground": "분열기 지상군",
        "random_ground": "무작위 지상 전략",
    },
    "Zerg": {
        "ling_bane": "저글링·맹독충",
        "roach_ravager": "바퀴·궤멸충",
        "roach_hydra": "바퀴·히드라",
        "hydra_lurker": "히드라·가시지옥",
        "ultra_ling_bane": "토라스크·저글링·맹독충",
        "random_ground": "무작위 지상 전략",
    },
}

DEFAULT_BUILD_BY_RACE: dict[str, str] = {
    "Random": "random_ground",
    "Terran": "bio_tank",
    "Protoss": "stalker_immortal",
    "Zerg": "roach_hydra",
}

# 블리자드 멜레 AI가 원래 갖고 있는 빌드 분류(`AIBuild` enum). 로비에서 슬롯마다
# 하나를 넘기면 밀레 AI가 자기 종족별 세부 빌드 풀에서 하나를 고른다 — 예컨대
# "타이밍 공격"을 넘기면 프로토스는 4관문/추적자로보/점멸추적자 중에서 고른다.
# 우리가 방향만 주고 세부는 AI가 정하는 구조라, 강제(AIBuild 네이티브)와는 다르다.
#
# 세부 빌드를 직접 찍는 길(`c_specificLobbyBuild`, 사용자 정수 130)은 프로브로
# 막혔다: MeleeInitAI 안의 AIMeleeSharedInit이 그 값을 Invalid로 지우고 자기가
# 고른다(실측 — 초기화 전에 110을 심어도 20초 시점에 0). 초기화 뒤에 쓰면 값은
# 남지만 오프닝은 이미 선택된 뒤다. 그래서 지금은 이 6개만 노출한다.
#
# "" (빈 문자열)이면 기존 빌드 이름 → 분류 매핑을 그대로 쓴다(AI_BUILD_BY_STRATEGY).
MELEE_BUILDS: dict[str, str] = {
    "": "자동 (빌드에 맞춰)",
    "RandomBuild": "무작위",
    "Rush": "전면 러시",
    "Timing": "타이밍 공격",
    "Power": "지속 압박",
    "Macro": "경제 중심",
    "Air": "공중 직행",
}


@dataclass(frozen=True)
class SlotConfig:
    slot: int
    controller: str = "empty"
    team: int = 1
    race: str = "Random"
    build: str = "random_ground"
    # 밀레 AI 빌드 분류 직접 지정. ""이면 build 이름에서 자동 매핑.
    melee_build: str = ""

    @property
    def side(self) -> str:
        return "west" if self.slot <= 7 else "east"

    @property
    def active(self) -> bool:
        return self.controller != "empty"


@dataclass(frozen=True)
class CustomLauncherConfig:
    version: int
    slots: tuple[SlotConfig, ...]
    full_vision: bool = False
    allow_support_air: bool = True
    protoss_faction: str = "Standard"
    # §93 야생 저그(맵 플레이어 15) 활성화. 끄면 P15는 §90 이전의 중립 적대로
    # 남고, 맵 컨트롤러는 선배치 드론에게 채취 명령만 내린다 — 훈련·건설·확장·
    # 습격이 전부 없다. 켜기가 기본값이다(지금까지의 동작).
    wild_zerg: bool = True
    # §105 유닛 제어 모듈(비컨 브리지·공격 브로드캐스트·지원 파견·본진 방어·
    # 파이썬 출격 제어기). 끄면 병력 지휘는 전부 밀레 AI 자율이고, 우리 레이어는
    # 생산·보급·확장 보조만 한다 — "보조가 주가 될 수 없다"(§104 사용자 지시).
    # 끄기가 기본값이다. 감사(2026-07-22) A1~A4 수리 전까지는 켜지 않는 것을
    # 권장한다: 45초 통제/45초 재출격이 겹쳐 병력이 밀레 AI에게 돌아가지 않는다.
    unit_control: bool = False
    fullscreen: bool = True

    def validate(self) -> None:
        if self.version != 1:
            raise ValueError(f"지원하지 않는 설정 버전입니다: {self.version}")
        if tuple(slot.slot for slot in self.slots) != tuple(range(1, 15)):
            raise ValueError("슬롯은 P1부터 P14까지 순서대로 모두 있어야 합니다.")
        if self.protoss_faction not in PROTOSS_FACTIONS:
            raise ValueError(f"알 수 없는 프로토스 진영: {self.protoss_faction}")

        humans = [slot for slot in self.slots if slot.controller == "human"]
        if len(humans) != 1:
            raise ValueError("사람 플레이어는 정확히 한 명이어야 합니다.")

        active_teams: set[int] = set()
        for slot in self.slots:
            expected_team = 1 if slot.slot <= 7 else 2
            if slot.controller not in CONTROLLERS:
                raise ValueError(f"P{slot.slot}: 알 수 없는 플레이어 종류")
            if slot.team != expected_team:
                raise ValueError(
                    f"P{slot.slot}: 현재 버전은 서쪽 P1~P7=1팀, "
                    "동쪽 P8~P14=2팀으로 고정됩니다."
                )
            if slot.race not in RACES:
                raise ValueError(f"P{slot.slot}: 알 수 없는 종족 {slot.race}")
            if slot.melee_build not in MELEE_BUILDS:
                raise ValueError(
                    f"P{slot.slot}: 알 수 없는 멜레 빌드 {slot.melee_build}"
                )
            if slot.controller == "custom_ai":
                if slot.build not in GROUND_BUILDS[slot.race]:
                    raise ValueError(
                        f"P{slot.slot}: {RACES[slot.race]}에서 사용할 수 없는 빌드"
                    )
            if slot.active:
                active_teams.add(slot.team)

        if active_teams != {1, 2}:
            raise ValueError("1팀과 2팀에 각각 최소 한 명이 있어야 합니다.")

    @property
    def human(self) -> SlotConfig:
        return next(slot for slot in self.slots if slot.controller == "human")

    @property
    def active_slots(self) -> tuple[SlotConfig, ...]:
        return tuple(slot for slot in self.slots if slot.active)

    @property
    def custom_ai_slots(self) -> tuple[SlotConfig, ...]:
        return tuple(slot for slot in self.slots if slot.controller == "custom_ai")

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "full_vision": self.full_vision,
            "allow_support_air": self.allow_support_air,
            "protoss_faction": self.protoss_faction,
            "wild_zerg": self.wild_zerg,
            "unit_control": self.unit_control,
            "fullscreen": self.fullscreen,
            "slots": [asdict(slot) for slot in self.slots],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CustomLauncherConfig":
        config = cls(
            version=int(data.get("version", 1)),
            full_vision=bool(data.get("full_vision", False)),
            allow_support_air=bool(data.get("allow_support_air", True)),
            protoss_faction=str(data.get("protoss_faction", "Standard")),
            wild_zerg=bool(data.get("wild_zerg", True)),
            unit_control=bool(data.get("unit_control", False)),
            fullscreen=bool(data.get("fullscreen", True)),
            slots=tuple(SlotConfig(**item) for item in data["slots"]),
        )
        config.validate()
        return config


def default_custom_config() -> CustomLauncherConfig:
    # Default 4v4: P1 human + P2-P4 custom AI versus P8-P11 custom AI.
    active_ai = {2, 3, 4, 8, 9, 10, 11}
    slots = []
    for slot_id in range(1, 15):
        controller = (
            "human" if slot_id == 1 else "custom_ai" if slot_id in active_ai else "empty"
        )
        slots.append(
            SlotConfig(
                slot=slot_id,
                controller=controller,
                team=1 if slot_id <= 7 else 2,
                race="Random",
                build="random_ground",
            )
        )
    config = CustomLauncherConfig(version=1, slots=tuple(slots))
    config.validate()
    return config


def build_labels(race: str) -> tuple[str, ...]:
    return tuple(GROUND_BUILDS[race].values())


def build_key(race: str, label: str) -> str:
    return next(key for key, value in GROUND_BUILDS[race].items() if value == label)
