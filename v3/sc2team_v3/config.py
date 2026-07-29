"""V3 빌드에만 필요한 작은 설정 표면.

슬롯/팀/종족/진영은 검증된 :mod:`sc2team.custom_config`를 그대로 쓴다. 이
모듈은 그 공통 설정을 복제하지 않고, V3 MapScript 빌드가 알아야 하는
작은 선택지만 소유한다.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


AI_MODE_BOOTSTRAP = "bootstrap"
"""격리 진단: 기본 밀레 AI를 끄고 최소 V3 부팅만 실행한다."""

AI_MODE_UPSTREAM_EQUIVALENT = "upstream_equivalent"
"""고정된 V3 custom-AI TriggerLib snapshot을 사용한다."""

AI_MODE_CUSTOM_POLICY = AI_MODE_UPSTREAM_EQUIVALENT
AI_MODES = frozenset({AI_MODE_BOOTSTRAP, AI_MODE_UPSTREAM_EQUIVALENT})


V3_GROUND_BUILDS: dict[str, dict[str, str]] = {
    "Terran": {
        "terran_bionic": "바이오닉 — 해병·불곰·의무병·공성전차",
        "terran_mechanic": "메카닉 — 골리앗·사이클론·공성전차·토르",
    },
    "Protoss": {
        "protoss_gateway": "관문 중심 — 광전사·집정관·고위 기사·파수기",
        "protoss_gateway_robo": "관문+로보 — 광전사·용기병·파수기·불멸자·거신",
    },
    "Zerg": {
        "zerg_roach_hydra_ultra": "바퀴·히드라·울트라리스크",
        "zerg_ling_bane_ultra": "저글링·맹독충·울트라리스크",
    },
}

V3_BUILD_IDS: dict[str, int] = {
    "terran_bionic": 101,
    "terran_mechanic": 102,
    "protoss_gateway": 201,
    "protoss_gateway_robo": 202,
    "zerg_roach_hydra_ultra": 301,
    "zerg_ling_bane_ultra": 302,
}

V3_DEFAULT_BUILD_BY_RACE: dict[str, str] = {
    race: next(iter(builds)) for race, builds in V3_GROUND_BUILDS.items()
}


BOOTSTRAP_MARKER_ONLY = "marker_only"
"""T2 컴파일/주입 진단: V3 부팅 표식만 남긴다."""

BOOTSTRAP_START_ONLY = "start_only"
"""T2 진단: AIStart까지만 실행하고 타운·채집은 실행하지 않는다."""

BOOTSTRAP_START_TOWN_HARVEST = "start_town_harvest"
"""기본 V3 부팅: AIStart, 타운 선언, 채집을 실행한다."""

BOOTSTRAP_MODES = frozenset(
    {
        BOOTSTRAP_MARKER_ONLY,
        BOOTSTRAP_START_ONLY,
        BOOTSTRAP_START_TOWN_HARVEST,
    }
)


@dataclass(frozen=True)
class V3BuildConfig:
    """공통 맵 패치 위에 얹는 V3 전용 빌드 선택지."""

    version: int = 1
    ai_mode: str = AI_MODE_UPSTREAM_EQUIVALENT
    bootstrap_mode: str = BOOTSTRAP_START_TOWN_HARVEST
    # True면 공통 V1 빌더가 의존성·로스터·업그레이드 연결을 한 묶음으로 넣는다.
    # 이것은 V3 생산 정책을 켜는 스위치가 아니다.
    campaign_units: bool = False
    # (논리 슬롯, V3 빌드 키).
    player_builds: tuple[tuple[int, str], ...] = ()

    def validate(self) -> None:
        if self.version != 1:
            raise ValueError(f"지원하지 않는 V3 설정 버전입니다: {self.version}")
        if self.ai_mode not in AI_MODES:
            raise ValueError(
                "지원하지 않는 V3 AI 모드: "
                f"{self.ai_mode!r} (허용: {', '.join(sorted(AI_MODES))})"
            )
        if self.bootstrap_mode not in BOOTSTRAP_MODES:
            raise ValueError(
                "지원하지 않는 V3 부팅 모드: "
                f"{self.bootstrap_mode!r} (허용: {', '.join(sorted(BOOTSTRAP_MODES))})"
            )
        if not isinstance(self.campaign_units, bool):
            raise ValueError("campaign_units는 bool 이어야 합니다.")
        seen_slots: set[int] = set()
        for slot, build in self.player_builds:
            if not isinstance(slot, int) or slot < 1 or slot > 14:
                raise ValueError(f"V3 빌드 슬롯은 1~14여야 합니다: {slot!r}")
            if slot in seen_slots:
                raise ValueError(f"V3 빌드 슬롯이 중복되었습니다: P{slot}")
            seen_slots.add(slot)
            if build not in V3_BUILD_IDS:
                raise ValueError(f"알 수 없는 V3 지상 빌드: {build!r}")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "V3BuildConfig":
        raw_builds = data.get("player_builds", ())
        ai_mode = str(data.get("ai_mode", AI_MODE_UPSTREAM_EQUIVALENT))
        if ai_mode == "custom_policy":
            ai_mode = AI_MODE_UPSTREAM_EQUIVALENT
        config = cls(
            version=int(data.get("version", 1)),
            ai_mode=ai_mode,
            bootstrap_mode=str(
                data.get("bootstrap_mode", BOOTSTRAP_START_TOWN_HARVEST)
            ),
            campaign_units=bool(data.get("campaign_units", False)),
            player_builds=tuple(
                (int(item[0]), str(item[1])) for item in raw_builds
            ),
        )
        config.validate()
        return config


# 짧은 이름을 선호하는 초기 V3 호출부와, 설정의 역할을 드러내는 이름 모두를
# 제공한다. 두 이름은 같은 불변 설정 타입이다.
V3Config = V3BuildConfig
