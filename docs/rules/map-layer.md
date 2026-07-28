# 맵·빌더 계층 규율

**V3와 V1이 공유하는 계층이다.** V3는 자체 맵 빌더가 없고
`build_runtime_map(..., melee_only=True)`로 이 계층을 그대로 쓴다
(`v3/sc2team_v3/runtime.py:228`). 여기 규율은 **어느 담당이든 적용된다.**

`melee_only=True`가 끄는 것은 V1의 AI 계층(MapScript 생산/연구/공급/전투 트리거)뿐이다.
맵, MapInfo, 슬롯, 팀, 시작점, 보급 상한, 캠페인 데이터, 프로토스 종족 교체, P15 승격은
전부 살아 있다.

## 빌더 구조

| 파일 | 책임 |
| --- | --- |
| `tools/build_custom_runtime_map.cjs` | CLI 진입, 오케스트레이션 순서, 스톡 사이드카 |
| `tools/build/util.cjs` | `fail`, 경로 상수, `readGalaxyTemplate` (build/ 의존 없음) |
| `tools/build/tables.cjs` | 종족·빌드 데이터: 스톡, 연구 사다리, 인프라, 핫키 |
| `tools/build/mapinfo.cjs` | MapInfo 바이너리 파싱, 슬롯 압축, 설정 검증 |
| `tools/build/production.cjs` | 생산 규칙 Galaxy (**V1 전용**) |
| `tools/build/runtime.cjs` | 런타임 Galaxy: 경제, P15, 조립 |
| `tools/build/unit_control.cjs` | 유닛 제어 Galaxy (**V1 전용**) |
| `tools/build/archive.cjs` | MPQ 패처: 로컬라이즈, 핫키, 카탈로그, 보급, 장식 |
| `tools/build/verify.cjs` | 빌드 시점 자체 검증 (`verify()`) |
| `tools/galaxy/hostile_wild_ai.galaxy` | V1 P15 야생 저그 (**V3에서 미사용**) |
| `tools/galaxy/hostile_wild_idle.galaxy` | V1 P15 채취 전용 (**V3에서 미사용**) |

작업 규칙:

- `tools/galaxy/`의 `.galaxy`는 `${}` 보간이 **없는** 생 Galaxy 소스다.
  `readGalaxyTemplate`이 CRLF를 LF로 정규화하는데, JS 템플릿 리터럴이 명세상 같은 일을
  하기 때문이다. 이걸 없애면 CRLF 체크아웃에서 빌드 결과가 달라진다. 보간이 필요한
  Galaxy는 `.cjs` 템플릿 리터럴에 둔다.
- Galaxy는 선언 후 사용이므로 `runtime.cjs`의 조립 순서 bridge → production을 유지한다.
- `tools/build/util.cjs`는 다른 `build/` 모듈을 require 하지 않는다 (순환 방지).
- 경로 상수는 `util.cjs`에만 둔다. `build/` 모듈에서 `path.join(__dirname, "..")`을
  다시 쓰지 않는다 — 깊이가 다르다.
- **빌더를 고쳤으면 회귀 판정 기준은 바이트 동일 재빌드다.** 오프라인 tier의 픽스처는
  결정적이므로 순수 리팩터는 1바이트도 움직이면 안 된다. 비교 전에
  `runtime/maps/verify-all-*`를 지운다 — 빌드가 실패하면 이전 맵이 남아서 거짓 일치가 된다.

## 플레이어 매핑

- SC2 API `Participant`는 **정확히 하나**다. 나머지 AI는 전부 인게임 `Computer`다.
- 그 하나의 Participant는 논리적 위치가 P1~P14 어디든 **런타임 플레이어 1**이 된다.
  항상 논리→런타임 매핑 헬퍼를 쓴다. 논리 P8이 런타임 P8이라고 가정하지 않는다.
- **엔진은 Participant 슬롯에 멜리 AI를 절대 돌리지 않는다.** `AIStart`/`AIMeleeStart`/
  `PlayerSetDifficulty` 조합은 전부 조용히 무시된다 (§66, 건강한 대조군 대비 4가지 변형 실측).
- **관전자 모드 예외(§66, 테스트 런처 전용):** Participant 없이 게임을 만들고 모든 슬롯을
  Computer로, API는 유일한 `Observer`로 접속한다. 런타임 ID 순서는 그대로다.
  관전 연결은 유닛 명령을 못 보낸다.
- 팀 게임에 외부 ProBot을 여러 개 넣지 않는다. SC2 5.0.16은 1v1보다 큰 다중 에이전트
  게임을 거부한다.

## 맵 파일

| 경로 | 무엇 |
| --- | --- |
| `map/source/` | 런처가 고를 수 있는 플레이용 맵. **불가침.** 새 맵은 여기 넣는다. |
| `map/img/<맵이름>/` | `tools/make_map_previews.py` 가 만드는 프리뷰 PNG. **맵마다 하위 디렉터리** 하나다 — `terrain.png` (마커 없음) 와 `2team.png`·`3team.png`·`4team.png`. 생성물이라 덮어써도 된다. |
| `runtime/maps/` | 빌드 산출물. `v3-<맵이름>.SC2Map` 로 나온다. |

- `runtime/maps/` 아래 생성된 맵을 **소스 파일로 편집하지 않는다.** 빌더나 고정 팀 베이스
  맵을 고치고 재생성한다.
- **사용자 맵 편집은 보존한다.** 요청이 명시적으로 대체하는 경우가 아니면 건드리지 않는다.
  `map/source/**`는 불가침이다. 중간 산출물을 여기 쓰지 않는다 — 이 디렉터리가 곧
  런처의 맵 목록이다.
- 베이스 맵: `map/source/europe-melee-2-7v7-rich-50000-fixed-teams.SC2Map`.
  **rich(50000)이다** — 자원 부족은 어떤 증상의 원인도 될 수 없다.
- 실행 중인 게임은 의존성 목록을 맵의 `DocumentInfo`가 아니라 **`DocumentHeader`**에서
  읽는다. 둘 다 패치하지 않으면 의존성이 조용히 무시된다.

## 맵 기하와 미니맵 프리뷰

`MapInfo` 는 전체 크기(`width`/`height`)와 **플레이 영역**(카메라 경계
`left`/`bottom`/`right`/`top`)을 따로 들고 있다. 둘은 다르다 — Flat128 은 전체
152x160 에 플레이 영역 128x128 이다. `tools/build/mapinfo.cjs` 의
`readMapInfoGeometry` 가 이 값을 읽는다.

**미니맵 좌표 변환 규칙 (맵 22개 실측 확정, 예외 없음):**

- 아카이브의 `Minimap.tga` 는 2의 거듭제곱 크기 텍스처다.
- 그 안에 플레이 영역이 **정수 배율**로 확대돼 **중앙 정렬**로 들어간다.
- 배율 = `min(texW // playW, texH // playH)`.
- 게임 좌표 -> 픽셀: `px = left + (x - bounds.left) * scale`,
  `py = top + (bounds.top - y) * scale`. **SC2 는 +y 가 북쪽이고 이미지는 위가 행 0**
  이므로 y 를 뒤집는다.

실측 사례 세 형태: 유럽 256x256 -> 1024x1024 배율 4 (패딩 없음), Torches
128x144 -> 128x256 배율 1 에 세로 패딩 56, Flat48 48x48 -> 64x64 배율 1 에
사방 패딩 8. 22개 전부에서 이 계산 결과가 실제 이미지의 비검정 경계와 정확히
일치했다. 구현은 `sc2team/map_preview.py`.

## MapInfo 파싱

`MapInfo` 는 길이 표가 없는 **순차 위치 파싱**이다. 필드 하나를 잘못 읽으면 그
뒤가 전부 밀린다. 실측으로 확정된 두 가지를 지켜라.

**로드스크린 경로는 조건 없이 항상 오는 cstring 이다.** `loadScreenType` 값으로
읽을지 말지를 가르면 안 된다 — Flat128 도 Torches LE 도 타입은 `0` 인데 전자는
빈 문자열, 후자는 `Assets\Textures\ui_void_loading_taldarim01.dds` 를 담는다.
경로 뒤 불투명 구간은 **60바이트**다 (Flat128 87 -> 147, Torches 137 -> 197).
같은 이유로 `previewType` 에 걸린 조건부 문자열 읽기도 없다 — 그 자리는
`u32, u32, cstring, cstring` 이다.

경로를 조건부로 읽어도 우리 맵에서는 한동안 멀쩡해 보인다. 빈 문자열의 종결
바이트 `0x00` 이 뒤따르는 u16 의 첫 바이트로 먹히고 둘 다 0 이라 값이 안 바뀌며,
1바이트 밀린 오프셋을 뒤 스킵이 상쇄하기 때문이다. **우연이지 정상이 아니다.**

**플레이어 id 는 예외 없이 `0, 1..N, 15` 다** (맵 22개 실측). 0 으로 시작해 15 로
끝나고, 엄격히 증가하며, 전부 `0..15` 안에 있다. 이 모양이 정렬이 맞았는지를
가장 값싸게 판별한다 — 슬롯 수 상한 검사보다 훨씬 촘촘하다. 어긋나면 조용히
이상한 값을 돌려주지 말고 실패시켜라.

**준비 전 맵은 슬롯 -> 좌표 연결이 없다.** MapInfo 의 `startPoint` 가 모든
슬롯에서 0 이며, 엔진이 경기 시작 때 배정한다. `tools/build_team_map.cjs` 로
준비할 때 고정된다. 그래서 프리뷰의 슬롯 번호는 준비 전 맵에서 **잠정**이고
이미지에 그렇게 표시한다 — 방위 분할(팀 색)은 좌표에서 나오므로 잠정 여부와
무관하게 맞다.

## 보급 상한

- 런타임에 `c_playerPropSuppliesLimit`를 **설정하지 않는다.** 두 방식 모두 시작 유닛이
  사라지거나 중복되는 결과를 냈다.
- 800 상한은 기존 맵 `UnitData.xml` 안의 **부분 `CRace` 오버라이드**로 유지한다.
  맵 레벨 `Base.SC2Data/GameData/RaceData.xml`은 추가하지 않는다 — 표준 종족 카탈로그를
  가리고 시작 유닛을 없앤다.
- 전체 `CRace` 복사도 금지다. 시작 배열을 상속·병합해서 시작 유닛이 중복된다.

## 캠페인 데이터

캠페인 유닛은 V3에서도 `v3_config.campaign_units`로 켤 수 있다. 카탈로그 계층 규율은
그대로 적용된다.

- 캠페인 추가와 프로토스 종족 교체는 `tools/campaign_data/` 아래 **외과적 카탈로그
  스니펫**이다. 전체 스토리 의존성을 추가하지 않는다.
- **의존성 목록을 최소로 유지한다.** Swarm Story를 추가하면 `Campaigns/Swarm.SC2Campaign`이
  딸려 오고, 그게 Goliath 구매가 쓰는 `FactoryTrain` `Train20` 슬롯을 뺏어 런처가 아예
  시작하지 않는다.
- 캠페인 의존성은 **에셋 제공자이지 런타임 GameData import가 아니다.** 의존성을 추가해도
  `HotSTorrasque`·Predator·Goliath·Medic·Aberration·Raptor의 부모 레코드가
  `ResponseData`에 생기지 않는다. 필요한 retail XML 레코드를 `tools/campaign_data/`에
  직접 넣는다.

### 로스터 카탈로그 함정

각 항목은 실제로 깨져서 배운 것이다.

- 로스터 `CActorUnit`은 `Generic*` 베이스 액터에서 상속하고 자기 `unitName`을 설정한다.
  구체 유닛 액터에서 상속하면 부모의 `UnitBirth` 토큰이 박혀서 액터가 바인딩되지 않고
  **회색 구체**가 된다.
- `CModel`의 `parent`는 `Model` 에셋 경로를 상속하지 않는다. 모든 로스터 `CModel`은 자기
  `.m3` 경로를 명시한다.
- 로스터 `CUnit`은 블리자드의 캠페인 레코드에서 상속한다. 멜리 유사품에서 상속하지 않는다.
  원본과 같은 값의 스탯은 다시 쓰지 말고 지운다.
- **카탈로그·디버그생성·전투 프로브는 회색 구체 상태에서도 전부 통과한다.**
  `verification/verify_campaign_render.py`나 실제 게임 화면만 판별할 수 있다. 모델이나
  액터 변경은 렌더된 프레임을 보기 전에 검증됐다고 하지 않는다.
- SC2는 유닛 액터의 음성을 **액터 id로** 연결한다. 로스터 액터 이름이 `SC2Team*`이라
  자동 연결이 아무것도 못 찾는다. `SoundArray`에 블리자드 `CSound`를 명시하지 않으면
  전부 무음이다. 잘못된 사운드 id는 치명적이 아니라 그냥 무음이다.
- 무기 발사·피격 사운드는 `CActorAction`에서 오고, `effectAttack`은 `CEffectDamage`
  **리프**를 지목해야 한다. 무기나 이를 감싸는 `CEffectSet`이 아니다.
- 베이스 게임과 Liberty 캠페인의 사운드만 쓴다. `Aberration_*` 음성 세트는 Swarm Story에만
  있고, 그게 Goliath 생산을 깨는 그 의존성이다.
- `CButton`은 아이콘일 뿐이다(블리자드 것도 마찬가지). 핫키는 `GameHotkeys.txt`의
  `Button/Hotkey/<id>`, 텍스트는 `GameStrings.txt`의 `Button/Name|Tooltip/<id>`에서 온다.
  `_NRS`/`_SC1`/`_USD`/`_USDL` 프로필 변형을 전부 써야 기본 프로필 외에서도 동작한다.
- 커맨드 카드에서 안 보이는 유닛은 보통 버튼이 깨진 게 아니라 **`Requirements` 미충족**이다.
  SC2는 그런 버튼을 비활성이 아니라 숨긴다. Goliath는 `HaveArmory`, Medic은
  `HaveAttachedTechLab`이 필요하다. Predator는 요구조건이 없어 "카드가 배선돼 있나"의
  대조군이다.
- 버튼이 사라지는 다른 이유는 **최종 멜리 레이아웃과의 슬롯 충돌**이다(liberty 베이스가
  아니라). voidmulti는 SiegeTank 버튼을 Factory (0,3)으로 옮기고, 유효한 버튼 둘이 한
  슬롯을 공유하면 낮은 인덱스만 보인다. Goliath는 (1,2)에 있다. 새 버튼을 놓기 전에
  liberty→swarm→voidmulti 합성 카드를 확인한다.
- 멜리 무기/방어 업그레이드는 효과와 유닛을 id로 참조한다. 새 로스터 유닛은
  `roster/UpgradeData.xml`이 멜리 `CUpgrade` 레코드에 참조를 덧붙이기 전까지 업그레이드
  혜택도 +N 표시도 없다. 무기는 자기 레벨 0 `Icon`도 필요하다(없으면 정보 패널 무기
  슬롯이 빈칸).
- `CAttachMethodPattern`은 `Driver`(발사 효과 id)로 구동된다. 블리자드의 `AMPatternGoliath`
  (Driver `GoliathALM`)를 다른 발사 효과로 재사용하면 아무것도 resolve 되지 않고 미사일이
  유닛 원점(골반)에서 나간다. 발사 효과마다 패턴을 복제하고, 액션의 `LaunchAttachQuery`에
  `Fallback="SetB"`를 유지한다.

## 명령 인덱스 유도

`CAbilTrain`/`CAbilWarpTrain`/`CAbilResearch`의 InfoArray에서 유도한다
(`TrainN` → 인덱스 N-1). 합성 순서는 liberty→liberty-campaign→swarm→swarmmulti→voidmulti,
소스는 `vendor/sc2gamedata-source`.

**잘못된 인덱스는 에러가 아니라 조용한 오작동이다** — 다른 유닛이 나오거나 아무 일도
일어나지 않는다. 벤더 레이어에서 다시 유도하지 않고 인덱스를 고치지 않는다.

## 야생 저그 승격 (양쪽 담당 공유)

`wild_zerg=true`면 **세 가지가 같이** 일어난다. 하나라도 빠지면 슬롯 수가 안 맞아 게임이
안 뜬다.

1. `mapinfo.cjs` — MapInfo 플레이어 15 `control`을 1(Computer)로
2. `patchWildZergStart` — 여분 `StartLoc`을 알파 둥지(1시 방향)로 이동
3. `player_setups`에 P15 Computer 항목 추가

**이 경로는 `melee_only`와 무관하다 — V3도 그대로 쓴다.** 상세와 담당 경계는
[`../ownership.md`](../ownership.md), 동작 규율은
[`../../v3/docs/wild-zerg.md`](../../v3/docs/wild-zerg.md).

## 테스트 모드

- 테스트 모드는 `full_vision`을 강제하고 이 값은 맵 빌드 시점에 구워진다. 따라서 **자기
  `-test` 맵 파일로만 빌드**해야 하고 릴리스 맵을 덮어쓰면 안 된다. 강제된 값을 사용자
  저장 설정에 다시 쓰지도 않는다.
- `all_resources`는 무제한 상태가 아니라 **1회성 5000/5000 지급**이다. 반복 지급이
  누적되는 것이 테스트 런처의 무한 자원이 동작하는 유일한 이유다. `minerals`/`gas`
  개별 지정은 신뢰할 수 없다(가스는 실측상 움직이지 않았다).
- `fast_build`는 건물을 즉시로 만들지만 유닛은 약 17배 빠르게 할 뿐이다.
