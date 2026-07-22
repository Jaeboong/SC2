"""V2 보조 설정.

V1의 `CustomLauncherConfig`(슬롯·종족·시야·야생저그·프로토스 진영)는 그대로
재사용한다. 여기 있는 것은 **V2에만 있는 손잡이**다.

확장·병력 두 개는 실측으로 골랐다:

- 확장 보조 `AIExpand` — 좌표를 안 준다. "네 본진에서부터 찾아서 확장해라"만
  요청한다. 12분 기준 기지 1.2 → 2.8, 일꾼 35 → 55 (재현 2회).
- 병력 보조 `AISetStockArmyDefaultScale` — 밀레 AI가 원하는 병력 목표에 배율만
  건다. 유닛 종류도 조합 비율도 빌드도 우리가 안 고른다. 홀짝 뒤집기 양방향
  통과 (20분 병력비 1.73 / 1.45).

탈락한 것도 남겨둔다: `AISetStockExtra`와 `AISetStockEx(c_stockForced)`로
생산건물 수를 올리는 길은 4판에서 재현에 실패했고, 병력배율과 조합해도 건물이
늘지 않았다. 다시 시도하려면 `v2/docs/` 기록부터 읽을 것.

보조가 아닌 **콘텐츠** 손잡이도 여기 둔다(`campaign_units`). V2에는 이것 말고
설정 그릇이 없고, 저장 파일도 같은 곳이라 나누면 오히려 흩어진다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


# 배율 선택지. 2.0은 양방향 뒤집기를 통과한 값이고, 나머지는 미검증이다.
ARMY_SCALE_CHOICES: tuple[float, ...] = (1.5, 2.0, 2.5, 3.0)

# 생산건물 배율 선택지. 아직 실측 전이다(아래 production_assist 주석 참고).
PRODUCTION_SCALE_CHOICES: tuple[float, ...] = (1.5, 2.0, 2.5, 3.0)

# 기지 상한. 사용자 지시: "확장은 4개까지 지원하자."
EXPANSION_CAP_CHOICES: tuple[int, ...] = (2, 3, 4, 5)

# 야생 저그 선배치 병력 고정을 푸는 시각(분). 9분이 사용자 지정값이다.
HOLD_RELEASE_CHOICES: tuple[int, ...] = (6, 9, 12, 15)


@dataclass(frozen=True)
class V2Assist:
    """밀레 AI에 얹는 보조 손잡이. 둘 다 독립적으로 껐다 켤 수 있다."""

    expansion_assist: bool = True
    expansion_cap: int = 4
    # 확장 요청 주기(초). 밀레 AI가 요청을 받아 자기 판단으로 실행하므로
    # 짧게 잡아도 확장이 그만큼 빨라지지는 않는다.
    expansion_period: float = 60.0

    army_assist: bool = True
    army_scale: float = 2.0
    # 배율 재인가 주기(초). 네이티브 주석이 "doesn't change current army"라
    # 이미 잡힌 목표에는 소급이 안 될 수 있어 주기적으로 다시 건다.
    army_period: float = 10.0

    # 생산건물 보조: 밀레 AI 가 **이미 1개 이상 완성한 종류만** 개수를 배율만큼
    # 올린다. 0개인 종류는 안 건드리므로 바이오닉 슬롯에 군수공장이 끼어들지
    # 않는다.
    #
    # 구현이 두 번 바뀌었다. AISetStock 계열(AISetStockExtra → c_stockForced
    # 덧셈 → c_stockForced 배율)은 셋 다 무효였고, V1 §71 이 이미 같은 결론을
    # 갖고 있었다. 지금은 `AIBuild` 직접 발주다 — 사용자 판단: "생산 자체는
    # 우리 명령을 따르는데 생산 건물을 안 따른다면 생산 건물만 강제하겠다."
    #
    # §83(전제조건 미충족 AIBuild 가 빌드 매니저를 영구 정지)은 재발하지
    # 않는다. 이미 **완성해서 갖고 있는** 종류만 발주하므로 전제조건 충족이
    # 구조적으로 보장된다.
    #
    # 아직 실측 전이라 기본값은 꺼짐이다.
    production_assist: bool = False
    production_scale: float = 2.0
    production_period: float = 15.0

    # 야생 저그(P15)의 **선배치** 전투 유닛을 밀레 AI 손에서 뺏어 제자리에
    # 두게 한다. V2 에서는 P15 를 밀레 AI 가 직접 굴리므로, 그냥 두면 맵 장식용
    # 무리 174기가 통째로 출격 편성에 들어간다. 이후 생산되는 유닛은 건드리지
    # 않는다. 야생 저그가 꺼져 있으면 의미가 없어 자동으로 건너뛴다.
    #
    # 실측(8분, 옵저버): 고정 ON 이면 선배치 122기 중 4기만 움직였고, OFF 면
    # 1분 만에 86기가 출격했다. 경제는 양쪽 다 정상(드론 20기 전원 채취).
    hold_wild_units: bool = True
    # 이 시각(게임 초)에 고정을 푼다. 사용자 지시: "9분 이후에는 선배치 유닛도
    # 고정을 푼다." 초반에는 야생 저그가 자기 자리를 지키는 지형 위험 요소로
    # 남고, 중반부터는 밀레 AI 가 그 병력까지 마음대로 쓴다.
    hold_wild_release_seconds: float = 540.0

    # 캠페인 유닛(골리앗·프레데터·의무병·애버레이션·토라스크·랩터 진화).
    #
    # 켜면 V1 빌더에 `campaign_units_pilot=True` 로 전달되어 **세 가지가 한
    # 묶음으로** 들어간다. 사용자 지시(2026-07-23): "유닛만 가져오는 것이 아닌
    # 업그레이드 연결 여부도 같이 가져와야 한다."
    #
    #   1. 의존성 — Liberty 캠페인 에셋 의존성 + DocumentHeader 패치. 실행 중인
    #      게임은 DocumentInfo 가 아니라 **DocumentHeader** 에서 의존성 목록을
    #      읽으므로 둘 다 패치해야 한다. 빠지면 테란 3종(골리앗·프레데터·의무병)
    #      모델이 조용히 회색 구체가 된다.
    #   2. 로스터 카탈로그 — Abil/Unit/Weapon/Effect/Actor/Model/Button/Upgrade.
    #   3. **업그레이드 연결** — `roster/UpgradeData.xml` 이 멜레 CUpgrade 레코드에
    #      새 유닛의 참조(Effect Amount, Weapon Level+아이콘, Unit LifeArmor/
    #      LifeArmorLevel)를 덧붙인다. 이게 없으면 골리앗·애버레이션이 기존
    #      공격/방어 업그레이드를 **전혀 못 받고** 정보창 +N 표시도 안 뜬다.
    #      로스터 카탈로그와 같은 패치 함수에 묶여 있어 따로 끌 수 없다.
    #
    # 생산은 별개다. 밀레 AI 는 모르는 유닛 ID 를 자기 생산 대기열에 넣지 않으므로
    # V2 가 직접 훈련 명령을 낸다(`campaign_production`).
    campaign_units: bool = True

    # 캠페인 유닛 훈련 명령. `campaign_units` 가 꺼져 있으면 의미가 없다.
    #
    # V1 은 이걸 `UnitCreate` **구매**로 했다. V2 는 로스터가 실제로 갖고 있는
    # CAbilTrain 슬롯에 **진짜 훈련 명령**을 낸다. 이유는 §91.11 이다 — 구매는
    # 유닛을 그 자리에서 만들어 내므로 보급을 우회했고, 보급고 3개짜리 슬롯이
    # 인구 700 에 병력 266기(그중 250기가 골리앗·프레데터)를 굴린 것이 실측됐다.
    # 훈련 명령은 비용·보급·선행조건을 전부 엔진이 검사하므로 그 우회가 구조적으로
    # 불가능하고, 알 낳는 시간·건설 시간도 정상이다(§89.14 "생산이 아니라 치환"
    # 지적도 해당 없음).
    campaign_production: bool = True
    campaign_period: float = 15.0

    def validate(self) -> None:
        if self.expansion_cap < 1 or self.expansion_cap > 8:
            raise ValueError(f"기지 상한이 범위를 벗어났습니다: {self.expansion_cap}")
        if self.expansion_period <= 0:
            raise ValueError("확장 요청 주기는 0보다 커야 합니다.")
        if self.army_scale <= 0 or self.army_scale > 10:
            raise ValueError(f"병력 배율이 범위를 벗어났습니다: {self.army_scale}")
        if self.army_period <= 0:
            raise ValueError("병력 배율 주기는 0보다 커야 합니다.")
        if self.production_scale < 1 or self.production_scale > 10:
            raise ValueError(
                f"생산건물 배율이 범위를 벗어났습니다: {self.production_scale}"
            )
        if self.production_period <= 0:
            raise ValueError("생산건물 배율 주기는 0보다 커야 합니다.")
        if self.hold_wild_release_seconds < 0:
            raise ValueError("야생 저그 고정 해제 시각은 음수일 수 없습니다.")
        if self.campaign_period <= 0:
            raise ValueError("캠페인 유닛 생산 주기는 0보다 커야 합니다.")
        if self.campaign_production and not self.campaign_units:
            raise ValueError(
                "캠페인 유닛이 꺼져 있으면 캠페인 생산도 켤 수 없습니다."
            )

    @property
    def any_enabled(self) -> bool:
        return self.expansion_assist or self.army_assist

    def to_dict(self) -> dict[str, Any]:
        return {
            "expansion_assist": self.expansion_assist,
            "expansion_cap": self.expansion_cap,
            "expansion_period": self.expansion_period,
            "army_assist": self.army_assist,
            "army_scale": self.army_scale,
            "army_period": self.army_period,
            "production_assist": self.production_assist,
            "production_scale": self.production_scale,
            "production_period": self.production_period,
            "hold_wild_units": self.hold_wild_units,
            "hold_wild_release_seconds": self.hold_wild_release_seconds,
            "campaign_units": self.campaign_units,
            "campaign_production": self.campaign_production,
            "campaign_period": self.campaign_period,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "V2Assist":
        assist = cls(
            expansion_assist=bool(data.get("expansion_assist", True)),
            expansion_cap=int(data.get("expansion_cap", 4)),
            expansion_period=float(data.get("expansion_period", 60.0)),
            army_assist=bool(data.get("army_assist", True)),
            army_scale=float(data.get("army_scale", 2.0)),
            army_period=float(data.get("army_period", 10.0)),
            production_assist=bool(data.get("production_assist", False)),
            production_scale=float(data.get("production_scale", 2.0)),
            production_period=float(data.get("production_period", 15.0)),
            hold_wild_units=bool(data.get("hold_wild_units", True)),
            hold_wild_release_seconds=float(
                data.get("hold_wild_release_seconds", 540.0)
            ),
            campaign_units=bool(data.get("campaign_units", True)),
            campaign_production=bool(data.get("campaign_production", True)),
            campaign_period=float(data.get("campaign_period", 15.0)),
        )
        assist.validate()
        return assist

    def summary(self) -> str:
        parts = []
        if self.expansion_assist:
            parts.append(f"확장 보조(상한 {self.expansion_cap}기지)")
        if self.army_assist:
            parts.append(f"병력 보조({self.army_scale:g}배)")
        if self.production_assist:
            parts.append(f"생산건물 보조({self.production_scale:g}배)")
        if self.hold_wild_units:
            minutes = self.hold_wild_release_seconds / 60
            parts.append(f"야생 저그 선배치 병력 고정({minutes:g}분에 해제)")
        if self.campaign_units:
            parts.append(
                "캠페인 유닛" + ("(생산 포함)" if self.campaign_production else "(로스터만)")
            )
        return " + ".join(parts) if parts else "보조 없음 (순수 밀레 AI)"
