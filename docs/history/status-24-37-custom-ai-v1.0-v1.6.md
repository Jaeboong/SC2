# 과거 상태 기록 §24–37 — Custom AI v1.0~v1.6.0

`docs/latest_status.md`에서 분리한 원문이다. 절 번호는 원본 그대로 보존한다.
14슬롯 Custom AI 구조 확립, 전략 명령 브리지, 지원/출격/경제 순환, 인구 600
상한까지의 기록이다.

## 24. 14슬롯 Custom AI v1 런처 1단계

새 실행 진입점:

```text
start_custom_ai.cmd
app/play_custom_ai.py
```

기존 `start_7v7.cmd`는 내장 AI용 안정 버전으로 그대로 보존했다. 새 런처에는 다음
기능을 구현했다.

- P1~P14 각 슬롯의 `비어 있음 / 사람 / 커스텀 AI` 선택
- 사람은 정확히 한 명이며 P1~P14 어디로든 이동 가능
- 각 커스텀 AI의 독립 추가와 제거
- P1~P7 서쪽 1팀, P8~P14 동쪽 2팀 고정
- 종족 `무작위 / 테란 / 저그 / 프로토스`
- 종족에 따라 동적으로 바뀌는 자체 지상군 빌드 목록
- 수송·탐지 지원 공중 유닛 허용 옵션
- 사람 전체 지도 시야 테스트 옵션
- 마지막 설정 자동 저장과 JSON 프리셋 저장/불러오기
- 기본 P1~P4 대 P8~P11 4대4 구성

설정 및 런타임 모듈:

```text
sc2team/custom_config.py
sc2team/custom_runtime.py
tools/build_custom_runtime_map.cjs
```

최초 구현은 선택된 `MapInfo` 슬롯만 열면 원래 P번호가 보존될 것으로 가정했다.
그러나 실제 SC2 엔진은 중간의 닫힌 슬롯을 건너뛰고 활성 플레이어를 내부 P1부터
연속으로 다시 번호 매긴다. 따라서 GUI의 P1~P14를 내부 플레이어 ID가 아닌 고정된
시작 위치 슬롯으로 정의하고, 활성 위치를 연속 런타임 플레이어에 매핑하도록 수정했다.

사람 전체 시야도 논리 위치 번호가 아니라 변환된 런타임 사람 ID에 적용한다. 커스텀
AI 슬롯은 `RequestCreateGame`에서 Computer로 만들어 소유권과 시작 유닛을 받지만,
맵의 `MeleeInitAI()`는 제거되어 내장 AI가 실행되지 않는다.

프로토콜에는 플레이어 setup을 명시적으로 만드는 `create_game_with_setups()`를 추가했다.
추가 엔진 검증 결과 SC2가 유일한 Participant를 Computer보다 항상 앞에 배치한다는
것을 확인했으므로, 최종 런타임 순서는 `사람, 논리 슬롯 순서의 AI들`로 생성한다.
맵 생성기는 각 런타임 플레이어의 `start_point`를 선택된 논리 위치의 고정 시작점으로
복사하고, 팀 관계도 변환된 ID 조합으로 다시 생성한다.

```text
Logical slots: human P10; AI P1, P2, P3, P4, P8, P9
Runtime IDs:  human P1; AI P2, P3, P4, P5, P6, P7
Human mapping: logical P10 -> runtime P1
setup types: Participant, Computer, Computer, Computer, Computer, Computer, Computer
```

Python 컴파일과 설정 단위 테스트를 통과했다. 아래 25절에서 실제 엔진 재번호화 오류와
수정 후 검증 결과를 이어서 기록한다.

## 25. 빈 슬롯 재번호화 수정 및 실제 엔진 검증

사람을 위치 P2로 옮기고 위치 P1을 비우면 최초 런처는 다음 오류를 표시했다.

```text
사람 슬롯 매핑 실패: P2를 선택했지만 게임에서는 P1로 참가했습니다.
```

이는 위치 배치 실패가 아니라 SC2가 유일한 첫 활성 플레이어를 내부 P1로 재번호화한
결과였다. 수정본은 위치 P2의 고정 `start_point`, 팀, 종족을 런타임 P1에 복사하며,
런처도 `logical P2 -> runtime P1` 변환값을 기준으로 참가를 검증한다.

SC2 5.0.16 실제 엔진에서 P2 사람, P1 비어 있음 구성으로 검증했다.

```text
logical_slot=P2 runtime_player=P1 expected=P1
owned_start_units=10
unit_center=(37.4,48.0)
ENGINE_MAPPING_TEST=PASS
```

설정 및 런타임 단위 테스트는 총 13개가 통과했다. 기존 일꾼 보급 호환 테스트 2개도
별도로 모두 통과한다. 이제 P1을 비우고 사람을 다른 위치로 옮겨도 내부 번호 차이로
실행이 중단되지 않는다.

## 26. Participant 우선 재정렬 확인 및 최종 매핑

사람보다 번호가 낮은 위치에 AI가 있을 때는 SC2가 setup 입력 순서와 관계없이 사람
Participant를 내부 P1로 올린다. 사용자가 실제 저장한 다음 구성에서 이 동작을 확인했다.

```text
사람: 위치 P3
아군 AI: 위치 P1, P2, P4
적 AI: 위치 P8, P9, P10, P11
```

최종 매핑과 실제 엔진 결과:

```text
logical P3 -> runtime P1 (human)
logical P1 -> runtime P2
logical P2 -> runtime P3
logical P4 -> runtime P4
logical P8 -> runtime P5
logical P9 -> runtime P6
logical P10 -> runtime P7
logical P11 -> runtime P8

human_logical=P3 joined_runtime=P1 expected=P1
owned_start_units=10
human_unit_center=(26.4,95.8)
P3_HUMAN_ENGINE_TEST=PASS
```

이에 맞춰 Python setup 순서, MapInfo 시작점 복사, Galaxy 팀 관계, 전체 시야 대상과
런처 검증을 모두 Participant 우선 순서로 통일했다. 설정 단위 테스트는 14개가 통과했다.

## 27. 런처 종료 동작 개선

`Custom AI v1.0.3`에서 footer에 `런처 종료` 버튼을 추가했다. `테스트 종료`는 실행한
SC2 게임만 종료하고 런처는 유지하며, `런처 종료`는 다음처럼 동작한다.

- 게임이 없으면 런처를 즉시 종료한다.
- 게임 실행 중이면 확인 후 SC2 연결과 런처가 생성한 SC2 프로세스를 정리한다.
- 정리가 끝난 뒤 런처 창과 Python 프로세스를 종료한다.
- 우측 상단 X도 같은 종료 경로를 사용한다.

오류 메시지 창의 X는 메시지 창만 닫고 뒤의 런처 본체는 유지하므로, 명시적인 종료
버튼을 통해 현재 상태를 구분하기 쉽게 했다.

## 28. 다중 AI 전략 명령 브리지 실증

사람이 AI 유닛을 공유 제어하는 방식은 사용하지 않는다. 사람의 단일 SC2 API 연결이
자기 소유의 명령 매개체에 이동 명령을 보내고, 맵의 Galaxy 트리거가 좌표를 해석해
각 Computer 플레이어에게 정상적인 게임 명령을 내리는 구조를 구현했다.

```text
X = 100 + opcode
Y = 100 + runtime player ID
```

검증용 opcode 2로 적 프로토스 runtime P5의 일꾼 8기에게 공격 이동 명령을 전달했다.
명령 전 2초 기준 이동과 명령 후 12초 이동을 분리해 측정했으며 최종 결과는 다음과 같다.

```text
beacon_action=(1,)
moved_to_command=8/8
GALAXY_AI_WORKER_ORDER_TEST=PASS
```

사람의 전체 시야와 AI 공유 제어권은 켜지 않았다. `RequestMapCommand`는 외부 명령으로
등록할 맵 메타데이터가 확인되지 않아 사용하지 않았고, 유닛 주문 이벤트 브리지를
채택했다.

## 29. 화면에 보이지 않는 명령 매개체

초기 검증에서는 맵 중앙에 무적 해병을 두었기 때문에 사용자가 `가우스 소총`을 가진
해병을 볼 수 있었다. 최종 브리지에서는 다음처럼 바꿨다.

- 사람 소유 해병을 원래 시작 지점에 생성
- `c_unitStateUsingSupply=false`로 인구수 미사용
- Actor `SetOpacity(0)` 및 `SetVisibility(false)`로 모델 완전 비표시
- 무적 상태로 유지하고 명령 처리 직후 원래 지점으로 복귀
- Python은 게임 시작 직후 raw observation에서 태그를 한 번만 저장

`c_unitStateHidden=true`는 화면뿐 아니라 API raw observation에서도 사라져 명령을
보낼 수 없으므로 사용하지 않았다. 선택 불가 상태도 raw 명령을 `NotSupported`로
거부하게 만들어 사용하지 않았다. 모델 비표시 방식에서는 명령 결과 `Success`와
8/8 이동 검증이 다시 통과했다.

## 30. Custom AI v1.1.0 하이브리드 전략 제어기

실행 경로에 `sc2team/strategy_controller.py`를 연결했다. 현재 역할 분담은 다음과 같다.

- Blizzard 정예(VeryHard) AI: 채광, 일꾼, 건설, 생산, 개별 유닛 전술
- 로컬 Python 전략 제어기: AI별 첫 출격 시간과 반복 출격 판단
- Galaxy 브리지: 해당 AI의 지상 이동 유닛만 골라 정상 공격 명령 실행
- 사람: 자신의 종족만 플레이하며 AI를 수동 조종하지 않음

GUI 세부 빌드는 우선 다음 두 계층에 반영된다.

- Blizzard AI 성향: Rush / Timing / Power / Macro
- 첫 지상군 출격: 러시 180초, 타이밍 240초, 압박 300초, 자원형 360초,
  무작위 지상 270초

모든 후속 지상군은 60초 간격으로 다시 출격한다. 공중 유닛은 이 출격 명령에서
제외된다.

비실시간 고속 엔진 검증으로 약 104초(game loop 2332)를 진행한 결과:

```text
target=P1->runtime P2
marauder_start=(26.9,16.2)
marauder_end=(56.8,10.5)
distance_sq=926.8
production=[SupplyDepot 70%, Barracks 87%]
units={CommandCenter:1, SupplyDepot:1, Barracks:1, SCV:16, ...}
STRATEGY_RUNTIME_TEST=PASS
```

처음 실시간 30초 시험에서 생산 건물이 없다는 이유로 일꾼 인구수 0을 원인으로
잘못 추정했다. 사용자가 배틀넷 기본 AI의 정상 동작과 보라색 일꾼이 주변 적 파일런을
공격하러 이동하는 상황을 알려주어 추정을 폐기했다. 104초 고속 시험에서는 경제와
건설이 정상임을 확인했다.

## 31. 현재 한계와 다음 구현 범위

v1.1.0은 완전 독립 매크로 AI가 아니라 작동 가능한 하이브리드 첫 버전이다.

- GUI의 `해병·불곰·공성전차` 같은 세부 조합을 정확히 강제하지는 않는다.
- 전투 지상군만 외부 출격시키지만 내장 AI가 전투 공중 유닛을 생산하는 것은 아직
  금지하지 않는다.
- 목표 선택은 현재 상대 팀 첫 시작 지점이며, 정찰 정보·전력 비교·다중 목표 분산은
  아직 없다.
- 명령 매개체는 보이지 않고 인구수를 쓰지 않지만 실제 엔진 유닛이므로 후속 버전에서
  전용 데이터 유닛으로 교체하면 충돌과 승패 판정까지 완전히 분리할 수 있다.

GUI와 맵 표시 버전은 `Custom AI v1.1.0`으로 통일했다. `start_custom_ai.cmd`를 실행하면
`runtime/maps/europe-melee-custom-ai-v1.1.0.SC2Map`을 새로 만들고 전략 제어기를 함께
시작한다.

## 32. Custom AI v1.2.0 지상군 생산 규칙

v1.1.0의 다음 한계를 v1.2.0에서 구현했다.

- 모든 커스텀 AI의 전투 공중 유닛 생산 상한을 0으로 설정
- `수송·탐지 지원 공중 유닛 허용` 체크 상태를 실제 생산 상한에 반영
- 무작위 지상 전략을 제외한 세부 빌드에서 조합 밖 지상 전투 유닛 생산 상한을 0으로 설정
- 선택 조합의 목표 병력 수를 15초마다 `AISetStockUnitNext`로 내장 AI 재고에 보강
- 내장 정예 AI의 일꾼, 채광, 확장, 생산 건물, 업그레이드 계획은 그대로 유지

지원 공중 허용 시에는 테란의 의료선·밤까마귀, 프로토스의 관측선·차원 분광기,
저그의 감시군주·수송 대군주만 예외로 남긴다. 바이킹·밴시·해방선·전투순양함,
불사조·공허 포격기·예언자·우주모함·폭풍함·모선, 뮤탈리스크·타락귀·무리 군주·
살모사는 생산하지 못한다. 지원 공중 옵션을 끄면 앞의 지원 유닛도 함께 제한한다.

현재 사용자의 4대4 설정으로 비실시간 고속 엔진을 game loop 12096, 약 9분까지 두 번
진행했다. 첫 시험에서 8개 AI가 경제와 생산을 계속하는 상태로 전투 공중 유닛 0기를
확인했다. 두 번째 시험에서는 조합 밖 지상 유닛 제한까지 추가하여 다음을 확인했다.

```text
P1  mech_macro: SiegeTank 1, Hellbat 3, support Medivac 2/Raven 2
P2  bio_tank: Marine 20, Marauder 9, SiegeTank 3, support Medivac 2/Raven 1
P9  immortal_colossus: Stalker 15, Immortal 5, Colossus 2
P11 gateway: Zealot 12, Stalker 8, Sentry 2
all checked players: disallowed ground=0, combat air=0
GROUND_COMPOSITION_CAP_TEST=PASS
```

고급 유닛은 기술 건물과 자원이 갖춰진 뒤 생산되므로 같은 빌드라도 9분 시점의 수량은
전황에 따라 달라진다. 제한은 조합 밖 유닛을 막고 선택 유닛을 우선 요청하는 방식이며,
유닛 한 기 단위의 고정 비율을 강제하지는 않는다.

GUI, 맵 내부 표시, 런타임 파일명을 `Custom AI v1.2.0`으로 통일했다. 실행 파일은
`runtime/maps/europe-melee-custom-ai-v1.2.0.SC2Map`이다. 다음 전략 단계는 적 첫 시작점
고정 공격을 정찰 정보, 가까운 위협, 아군 전력 집결 상태를 고려하는 목표 선택으로
교체하는 것이다.

## 33. Custom AI v1.3.0 사람·AI 아군 긴급 지원

기본 내장 AI가 팀원의 피격에 적극적으로 반응하지 않는 문제를 보완하기 위해 자동
긴급 지원 계층을 추가했다. 피해를 받은 플레이어가 사람이든 AI든 구분하지 않으며,
양 팀 모두 동일한 규칙을 사용한다.

지원 요청 성립 조건:

- 한 플레이어의 현재 유닛·건물 체력과 보호막 감소량을 1초마다 추적
- 4초 안에 피해 12 이상 누적
- 피해 위치 반경 20 안에 실제 상대 팀 유닛이 존재
- 같은 피해 플레이어에 대한 30초 재호출 제한

이 조건으로 스팀팩, 자체 체력 소모, 적이 없는 상태의 임의 체력 감소를 공격으로
오인하지 않는다. 전략 제어기는 화면의 전장의 안개를 해제하지 않고 controller 전용
raw observation에서 양 팀 피해를 계산한다.

지원자와 파견 규칙:

- 피해 플레이어와 같은 팀인 커스텀 AI 중 가장 가까운 AI 한 명 선택
- 동시에 공격받는 AI와 45초 지원 재사용 대기 중인 AI는 제외
- 일꾼, 지게로봇, 여왕, 건물, 공중 유닛은 파견 대상에서 제외
- 가용 지상군 절반, 최대 30기에 피해 위치 공격 이동 명령
- 파견 병력은 45초 동안만 script-controlled 상태로 유지
- 45초 뒤 `AISetUnitScriptControlled(unit, false)`로 Blizzard AI에 반환

지원 위치와 helper runtime ID는 명령 비컨 이동 좌표의 X 소수 두 자리로 함께 인코딩해
한 번의 raw 명령으로 Galaxy 브리지에 전달한다. 기존 전체 출격 병력도 45초 뒤 내장
AI로 돌아오도록 같은 반환 경로를 사용한다.

검증 결과:

```text
unit tests: 20 PASS
isolated bridge: created=4, moved=2, stationary=2
human P3 damaged: support_event=P2->P3, moved=2/4
enemy AI P8 damaged: support_event=P9->P8, moved=2/4
script controlled immediately after dispatch: 2
script controlled after 50 seconds: 0
ALLY_SUPPORT_HALF_FORCE_TEST=PASS
HUMAN_DAMAGE_WITH_ENEMY_TEST=PASS
ENEMY_TEAM_ALLY_SUPPORT_TEST=PASS
SUPPORT_CONTROL_RELEASE_TEST=PASS
```

GUI, 맵 내부 표시, 런타임 파일명을 `Custom AI v1.3.0`으로 통일했다. 최종 실행 맵은
`runtime/maps/europe-melee-custom-ai-v1.3.0.SC2Map`이며 기존처럼
`start_custom_ai.cmd`에서 자동 생성하고 실행한다.

## 34. Custom AI v1.4.0 생산 규모 연동 출격과 테란 생산 보정

시간이 됐다는 이유만으로 소수 병력을 보내던 v1.3의 출격 조건을 폐기했다. 각 AI의
완성된 관련 생산 건물 수와 현재 살아 있는 지상 전투 유닛의 보급 전투력을 계산한다.

```text
요구 전투력 = clamp(14, 70, 8 + 완성 생산 건물 수 × 6)
```

현재 지상 전투력이 요구치 이상일 때만 출격하며, 출격 뒤 45초 동안은 재명령하지
않는다. 의료선·밤까마귀·관측선·수송선 등 공중 지원 유닛과 일꾼은 전투력에 넣지
않는다. 예를 들어 병영 1개인 테란은 해병 13기와 의료선 15기가 있어도 전투력 13으로
계산되어 요구치 14를 넘지 못하므로 출격하지 않는다. 병영이 2개가 되면 요구치는
20으로 올라간다.

내장 AI의 약한 다음 재고 힌트였던 `AISetStockUnitNext`는 `AISetStock` 절대 목표로
교체했다. 기존의 일꾼·보급·업그레이드 재고를 지우는 `AIClearStock`은 사용하지
않으므로 Blizzard 정예 AI의 경제 계층은 유지된다. 15초마다 다음만 다시 지정한다.

- 선택 빌드의 생산·기술 건물 목표
- 선택 조합의 지상 전투 유닛 목표
- 종족별 3기지 확장 목표

또한 메카닉 테란이 내장 빌드의 병영과 우주공항을 과도하게 짓는 문제를 막았다.
메카닉 계열은 병영 1개, 우주공항 1개까지만 허용하고 공장에 자원을 집중한다.
의료선은 바이오·바이오 전차 계열에서만 최대 4기이며, 치료할 생체 주력군이 없는
화염차·전차·토르·메카닉 계열에서는 0기다. 밤까마귀는 탐지 지원용 최대 2기다.

현재 사용자의 13인 설정으로 약 9분(game loop 12186) 고속 엔진 검증을 수행했다.
모든 실제 출격에서 현재 전투력이 동적 요구치 이상이었다. 확인된 일부 출격은
`P1 24/20(생산 2)`, `P1 33/26(생산 3)`, `P2 45/32(생산 4)`,
`P9 62/50(생산 7)`이었다. 요구치 아래인 테란 P3·P5·P6는 출격하지 않았다.

생산 건물 상한 적용 시험의 테란 결과:

```text
P1 mech_macro: Barracks 1, Factory 3, Starport 1, ground power 27/26
P2 bio_tank:   Barracks 3, Factory 1, Starport 1, ground power 40/32
P3 mech_macro: Barracks 1, Factory 2, Starport 1, ground power 7/20
P5 thor_tank:  Barracks 1, Factory 2, Starport 1, ground power 10/20
P6 mech_macro: Barracks 1, Factory 1, Starport 0, ground power 0/14
V140_CAPS_READINESS_TEST=PASS
```

이 시험 시점에는 메카닉 의료선 0 보정을 넣기 전 이미 생산된 의료선이 포함됐지만,
최종 생성 맵에서는 해당 빌드의 의료선 생산 상한 자체가 0이다. GUI 상태 줄은 출격 때
`P번호 전투력 현재/요구·생산 건물 수`를 표시한다. GUI·맵·런타임 파일 버전은
`Custom AI v1.4.0`이며 실행 맵은
`runtime/maps/europe-melee-custom-ai-v1.4.0.SC2Map`이다.

## 35. Custom AI v1.5.0 경제·생산·확장 순환

v1.4의 고정 생산 건물 상한을 폐기하고 완성 기지 수를 지속 자원 수입 능력으로 삼는
동적 생산 계층으로 교체했다. 메카닉 테란의 목표는 다음과 같다.

```text
완성 기지 1: 병영 1, 공장 3, 우주공항 1
완성 기지 2: 병영 1, 공장 5, 우주공항 1
완성 기지 3: 병영 1, 공장 7, 우주공항 1
완성 기지 4: 병영 1, 공장 9, 우주공항 1
공장 목표 = 3 + (완성 기지 수 - 1) × 2
```

각 단계의 공장과 기본 테크 건물이 완성되기 전에는 `TechTreeUnitAllow`로 새 사령부
건설 권한을 잠근다. 사령부·궤도사령부·행성요새와 건설 중인 기지를 함께 세므로
사령부가 변신했을 때 상한을 우회하거나 여러 확장을 동시에 요청하지 않는다.

생산 목표를 충족했는데 광물이 400 미만이면 허용 조합의 전투 유닛 생산만 잠시
정지한다. 400광물을 확보하면 `AIExpand`로 다음 확장을 직접 요청하고, 확장 건설이
시작되는 즉시 유닛 생산 제한을 해제한다. 일꾼·보급·채광·업그레이드는 이 비축 중에도
내장 정예 AI가 계속 관리한다. 따라서 생산 건물만 많고 수입이 모자란 상태에서는
무한히 유닛을 찍느라 확장을 못 하는 대신 다음 자원 거점을 우선 확보한다.

생산 건물은 선행 건물이 완성된 뒤 한 번에 하나씩 직접 요청한다. 병영이 없는 공장,
인공제어소가 없는 로봇공학 시설 같은 요청은 넣지 않으므로 내장 건설 큐를 막지 않는다.
기지가 늘면 목표 병력 수도 기존 목표의 60%씩 추가되어 늘어난 생산 건물이 계속
가동된다. 공격 준비도는 v1.4와 동일하게 실제 완성 생산 건물 수에 맞춰 더 큰 병력을
요구한다.

다른 빌드의 생산 증가도 같은 원칙을 사용한다.

- 바이오: 1기지 병영 4, 확장당 병영 2 추가
- 바이오 전차: 1기지 병영 3·공장 2, 확장당 각각 1 추가
- 관문: 1기지 관문 4, 확장당 관문 2 추가
- 추적자·불멸자/거신/분열기: 관문과 로봇공학 시설을 함께 증가
- 저그: 테크 조건 충족 후 기지 자체를 생산 기반으로 연속 확장
- 명시 종족의 무작위 지상 전략: 해당 종족의 범용 생산 비율 적용

사람 1명과 메카닉 정예 AI 1명을 둔 비실시간 통제 시험에서 다음 순서를 확인했다.

```text
loop  4928: 1기지, 공장 3 완성
loop  7616: 두 번째 사령부 건설 중 (공장 3)
loop  9408: 2기지 완성
loop 11200: 공장 5 완성
loop 12544: 세 번째 사령부 건설 중 (공장 5)
loop 14336: 3기지 완성
loop 17024: 공장 7 완성
loop 17920: 네 번째 사령부 건설 중 (공장 7)
loop 19264: 4기지 완성
loop 21056: 공장 9 완성
loop 21952: 다섯 번째 사령부 건설 중 (공장 9)
loop 26432: 5기지 완성, 병영 1, 공장 9, 우주공항 1
SCV: 최대 66, 경제 AI 정체 없음
ADAPTIVE_ECONOMY_TEST=PASS
```

GUI·맵·런타임 파일 버전은 `Custom AI v1.5.0`이며 최종 실행 맵은
`runtime/maps/europe-melee-custom-ai-v1.5.0.SC2Map`이다.

## 36. Custom AI v1.6.0 빠른 첫 확장과 인구 상한 600

첫 번째 확장은 생산 건물 목표와 무관하게 즉시 요청하도록 경제 순환을 변경했다.
1기지이고 건설 중인 추가 기지가 없으면 사령부·연결체·부화장 상한을 2로 열고
`AISetStockExpand`와 `AIExpand`를 호출한다. 첫 확장이 완성된 뒤부터는 v1.5의
생산 기반 조건을 그대로 적용한다. 예를 들어 메카닉 테란은 2기지 공장 5개를
완성해야 3기지, 3기지 공장 7개를 완성해야 4기지를 요청한다.

사람 1명과 메카닉 정예 AI 1명의 비실시간 통제 시험 결과는 다음과 같다.

```text
loop  1792: 두 번째 사령부 건설 중, 완성 공장 0
loop  3136: 2기지 완성
loop  9856: 공장 5 완성
loop 12544: 세 번째 사령부 건설 중
loop 14336: 3기지 완성
loop 16128: 공장 7 완성
loop 16576: 네 번째 사령부 건설 중
loop 17920: 4기지 완성
FAST_FIRST_EXPANSION_TEST=PASS
```

최대 인구수는 테란·프로토스·저그 모두 600으로 변경했다. 기존
`Base.SC2Data/GameData/UnitData.xml`에 각 종족의 `FoodCeiling=600` 필드만
추가해 상위 모드의 시작 유닛 데이터를 보존한다. 처음 시도한 런타임
`c_playerPropSuppliesLimit` 변경은 시작 유닛을 제거하는 부작용이 있어 완전히
삭제했다. 완전한 종족 레코드를 맵에 복제하는 방식도 기존 시작 배열과 합쳐져
본진과 일꾼이 중복되므로 사용하지 않는다.

실제 SC2 5.0.16 엔진에서 테란 양쪽 모두 기존과 동일한 `사령부 1 + SCV 8`로
시작하는 것을 확인했다. 사람 플레이어에게 보급고 80개를 시험 생성했을 때
관측 최대 인구가 정확히 600에서 멈췄다.

```text
SUPPLY_600_AND_NORMAL_START_TEST=PASS
STRATEGY_RUNTIME_TEST=PASS
단위 테스트: 21개 통과
```

GUI·맵·런타임 파일 버전은 `Custom AI v1.6.0`이며 최종 실행 맵은
`runtime/maps/europe-melee-custom-ai-v1.6.0.SC2Map`이다.

## 37. Claude 인수인계 문서 체계

다음 작업자가 긴 작업 일지에서 현재 상태를 다시 추론하지 않도록 역할별 문서를
분리했다. `latest_status.md`는 기존처럼 한국어 연대기와 엔진 실험 증거를 보존하며,
현재 상태와 재개 순서는 루트 `HANDOFF.md`가 담당한다.

- `CLAUDE.md`: 가장 먼저 읽을 짧은 포인터, 정본 파일, 절대 되돌리면 안 되는 불변 조건
- `HANDOFF.md`: v1.6.0 현재 상태, 검증 범위와 공백, 안전한 작업 재개 순서
- `docs/README.md`: 문서 우선순위와 영역별 라우팅
- `docs/architecture/system-overview.md`: 프로세스·플레이어 매핑·명령 흐름
- `docs/modify/runtime-map.md`: 맵·Galaxy·생산·확장·인구 수정 절차
- `docs/modify/strategy-controller.md`: Python 공격·지원 판단과 브리지 규약
- `docs/verify/verification-guide.md`: 검증 단계와 실제 실행 명령
- `docs/verify/engine-tests.md`: 실시간/비실시간 엔진 프로브의 범위와 한계
- `docs/operations/local-runbook.md`: 설치·실행·종료·장애 대응
- `docs/decisions/known-constraints.md`: API 제한과 되풀이하면 안 되는 실패 방식

영역별 상세 문서는 Claude가 이어받기 쉽도록 영어로 작성했다. 문서에는 현재 자동화된
21+2개 단위 테스트, 빌더 내장 구조 검증, `realtime=False` 고속 런타임 시험을 구분해
기록했다. 또한 인구 600 정상 시작, 빠른 첫 확장, 장시간 경제·조합·지원 시험은 결과와
프로브 맵만 남아 있고 독립 실행 하네스가 없다는 점을 명시해 과거 PASS 기록을 현재
자동 회귀 시험으로 오인하지 않도록 했다.

