# V3 오버레이 편집 규율

커스텀 AI 슬롯(테란 101/102, 프로토스 201/202, 저그 301/302)을 담당할 때의 규율.
담당 경계는 [`../../docs/ownership.md`](../../docs/ownership.md), 파이프라인 구조는
[`build-integration.md`](build-integration.md), 실행 흐름은 [`architecture.md`](architecture.md).

## 대전제

**우리 계층은 보조(補助)이고 블리자드 멜리 AI가 주(主)다** — 상시 사용자 지시(§104).
멜리 AI가 게임을 소유한다. 우리 코드가 존재하는 이유는 정확히 셋이다:

1. 산출을 **끌어올린다** (확장·보급·유닛 생산 보조)
2. 설정된 빌드로 **유도한다**
3. 특정 유닛 타입을 **금지한다**

이 셋을 벗어나는 것은 기본적으로 범위 밖이고 사용자의 명시적 승인이 필요하다.
**멜리 AI가 실제로 내리는 결정(어느 유닛을 명령할지, 어디로 확장할지)을 뺏는 것은 반대
방향이며, 이 저장소에서 그렇게 한 사례는 전부 사용자 눈에 보이는 회귀를 냈다.**

## 파일 구성

오버레이는 **정확히 10개**다. 개수를 바꾸려면 `v3_ai_layout.cjs`, `build_v3_ai_mod.cjs`,
`overlay-manifest.json`, `verify_v3_structure.py`를 같이 고쳐야 한다.

| 파일 | 역할 |
| --- | --- |
| `ExpansionGas.galaxy` | 공유 헬퍼 11개. 세 종족이 첫 번째로 include |
| `Terran.galaxy` | 테란 디스패처 |
| `TerranBionic.galaxy` / `TerranMechanic.galaxy` | 101 / 102 |
| `Protoss.galaxy` | 프로토스 디스패처 |
| `ProtossGateway.galaxy` / `ProtossGatewayRobo.galaxy` | 201 / 202 |
| `Zerg.galaxy` | 저그 디스패처(**1142행부터**) + P15(1~1141행, 야생 저그 담당) |
| `ZergRoachHydraUltra.galaxy` / `ZergLingBaneUltra.galaxy` | 301 / 302 |

`ExpansionGas.galaxy`와 `Zerg.galaxy`는 야생 저그 담당과 **공유**한다. 소유 표와 동결
함수 목록은 [`../../docs/ownership.md`](../../docs/ownership.md)에 있다.
**`ExpansionGas.galaxy`에서 함수를 지우기 전에 반드시 `V3/` 전체를 grep 한다** —
`V3SetWaveTargets`는 커스텀 AI 쪽에서 보면 호출자가 없어 보이지만 P15가 쓴다.

## 함정 1: 오버레이의 네이티브 스코프는 map galaxy와 다르다

**오버레이가 컴파일되는 include 컨텍스트는 런타임 map galaxy(`tools/galaxy/*.galaxy`)와
다르다.** map galaxy에 있는 일반 트리거 네이티브가 AI mod에는 **미정의**일 수 있고, 그런
심볼을 참조하면 **V3 mod galaxy 전체 컴파일이 깨진다.**

맵이 mod 의존성에 걸려 있으므로 mod가 안 뜨면 **로비 플레이어 1~N이 시작 유닛도 없이
스폰 실패한다** (관전하면 owner 15=야생저그·16=중립만 남고 1~N은 유닛 0).

실제 사례 (2026-07-24, 동시에 둘):

1. `PointWithOffsetPolar` 사용 — map galaxy P15 코드엔 있지만 다른 오버레이에서 0번 사용,
   `v3/ai/upstream/`에 선언 없음.
2. 전역 배열을 C 스타일 `fixed gv_x[16];`로 선언 — Galaxy는 **`fixed[16] gv_x;`**
   (`type[size] name`) 구문만 허용한다.

또 하나 (2026-07-25, §108):

3. `AITechStockAdd(player, upgradeType)` — 이 네이티브는 인자가 **하나**다
   (`native void AITechStockAdd (string upgradeType);`).

규칙:

- **오버레이에 네이티브를 새로 쓰기 전에** 다른 오버레이에서 이미 쓰이는지, 또는
  `v3/ai/upstream/`에 선언돼 있는지 grep으로 먼저 확인한다. 시그니처(인자 개수·타입)까지
  본다. "map galaxy(P15)에서 됐으니 오버레이에서도 된다"는 가정은 금물.
- 배치점 계산이 필요하면 map 전용 `PointWithOffsetPolar` 대신 AI 네이티브
  **`AIGetBuildingPlacement(player, center, aliasUnitType, c_makeNoFlags)`** 를 쓴다.
- 전역 배열은 **`type[size] name;`** 구문으로 선언한다.

**이 오류는 정적 검증 4종이 전부 PASS인 채로 게임을 죽인다.** 6분 스모크가 유일한 방어선이다
([`../../docs/harness.md`](../../docs/harness.md) 게이트 5). 격리 진단은
`probe_v3_ground_builds.py --upstream-timing`.

## 함정 2: 매니페스트

`.galaxy`를 한 글자라도 고치면 `v3/ai/overlay-manifest.json`의 해당 항목 `bytes`와
`sha256`을 재계산해야 한다. 누락하면 mod 빌드가 실패한다.

**Codex에게 매니페스트를 맡기지 않는다.** 편집이 전부 끝난 뒤 헤드 에이전트가 한 번
재계산한다. 야생 저그 담당과 동시에 작업 중이면 더욱 그렇다 — 두 사람이 각자 갱신하면
머지 충돌이고, 잘못 머지된 해시가 통과하면 전 슬롯 스폰 실패다.

## 함정 3: 구조물은 AIBuild, 모프는 UnitIssueOrder

**테크 구조물 강제는 `AIBuild`**(멜리 AI가 배치와 워커를 고른다), **모프는
`UnitIssueOrder`**다. 우리가 직접 드론을 잡아 배치하는 주문은 **실패한다**(실측).

- 302 InfestationPit/Cavern을 드론 직접주문으로 하니 무효 → `AIBuild`로 바꾸자
  레어 정지 8/12→4/12, Hive 4/12→8/12, 첫 `V3_GROUND_BUILDS=PASS`.
- 프로토스 Forge/Twilight/Templar도 같은 전환으로 Forge 11/12→12/12, Templar 10/12→11/12.

### AIBuild는 무해한 no-op이 아니다

요구조건이 충족되지 않은 `AIBuild`를 멜리 계획이 그 구조물을 한 번 짓기 전에 매 틱 발행하면
**해당 플레이어의 빌드 매니저가 영구히 멈춘다** — §83 실측: 잘못된 오프닝 오더를 가진 모든
슬롯이 20 게임분 동안 일꾼·병력·확장 0. 강제 건설 오더에는 반드시 게이트가 필요하다.

**"턴 제로" 오더로 만들 때는 특히 주의한다.** §91에서 Forge를 요구조건 `Nexus`로 걸었더니
6분 시점에 모든 프로토스 슬롯이 Forge는 있고 **사이버네틱스 코어가 없고 병력이 0**이었다
(대조군: Forge 없음, 코어 있음, 병력 4~14). 요구조건은 **오프닝 뒤에 생기는 구조물**이어야
한다. 이건 §83의 약한 형태다 — 빌드 매니저가 멈춘 건 아니고 순서만 뒤집혔는데, 그 대가로
프로토스 팀 전체가 초반 병력을 잃었다.

## 스톡 사다리

`AISetStockUnitNext(player, N, unit, when)`의 N은 **그 유닛의 누적 총 목표치**다.
스톡 목록은 위에서부터 자금을 받는 우선순위 사다리다. **초반에 도달 불가능한 숫자를 위에
놓으면 그 아래가 전부 굶는다.**

- **비싼 것을 위, 싼 것을 아래.** §108에서 302가 각 티어 첫머리에 저글링을 두어 라바와
  광물을 전부 먹었고, 일꾼 66→18, 히드라 0, 울트라 0, 연구 10종→1종이 됐다. 티어 순서를
  `Queen → Ultralisk → Hydralisk → Baneling → Zergling`으로 뒤집고 저글링 목표치를 낮춰서
  회복했다.
- 생산 건물에는 **`c_stockIdle`**을 쓴다 — 기존 건물이 유휴일 때만 하나 더 짓는다(자가 조절).
  업스트림은 476회 쓰고 V3는 원래 3회밖에 안 썼다.
- 완전(Full) 티어는 교차 점증으로 사실상 무제한으로 둔다(울트라 14 → 20 → 30 → 50 …).
  한 유닛이 나머지를 막지 않게 단계를 나눠 붙인다.
- **병력 상한을 두지 않는다** (사용자 지시 §68). 커스텀 AI 슬롯에는 천장이 없다.
  (400 보급 천장은 P15 전용이다.)

업그레이드 사다리는 `AISetStockTechNext`/`AINewTechStock`/`AITechStockAdd`로, 다음 레벨만
스톡하고 유닛 수로 게이트하며 `AIHighCurrentlyUnderHeavyAttack` 중에는 건너뛴다.
`AISetTechLimitLevels`/`AILimitTech`로 테크 지출을 현재 은행의 50~70%로 제한한다.

## 공격 트리거

`AISetAttackStatus(player, unit, minAlly, minSelf, merge)`는 **유닛별 명부가 아니라 공격
트리거**다. 발동하면 `AIWaveMerge(c_waveMain, c_waveAttack)`이 **메인 웨이브 전체**를 옮긴다.
`minSelf = 999`는 "혼자서는 절대 개시하지 않음"(호위 유닛)이다.

**빌드마다 개시자는 하나여야 한다.** 여럿이면 서로 다른 조건으로 웨이브를 찢는다.

| 빌드 | Open | Mid | Late | 999 호위 |
| --- | --- | --- | --- | --- |
| 저그 302 | Zergling 4/18 | Zergling 2/30 | Zergling 4/40 | Baneling, Hydralisk, Ultralisk |
| 저그 301 | Hydralisk 2/14 | Hydralisk 2/14 | Hydralisk 2/24 | Roach, Ravager, Ultralisk |
| 프로토스 201 | Sentry 1/3 | Sentry 1/3 | Archon 1/4 | Zealot, (후반) Sentry |
| 프로토스 202 | Stalker 2/8 | Stalker 2/8 | Immortal 1/4 | Zealot, Sentry, Colossus, (후반) Stalker |
| 테란 101 | SiegeTank 1/2 | SiegeTank 2/4 | SiegeTank 2/8 | Marine, Marauder, Medic |
| 테란 102 | SiegeTank 2/4 | SiegeTank 2/4 | Thor 1/4 (Thor≥2일 때) | Goliath, Cyclone, (후반) SiegeTank |

숫자는 `minAlly/minSelf`다. 재공격 판정은 업스트림
`MeleeWaveAI.galaxy:567 WaveAdvancedIdleAttackLogic`이 `AILastAttackRatio`로 한다 —
우리가 바꾸지 않는다.

**공격 로직은 블리자드 원본을 쓴다** (사용자 결정). 상시 공격 강제는 병력이 나오는 족족
찔끔찔끔 나가게 만들어서 채택하지 않았다.

## 확장

**확장은 V3 기존 로직을 그대로 따른다** — 상시 사용자 지시. 업스트림 생산 로직을 참고해도
확장은 가져오지 않는다(업스트림은 확장을 충분히 하지 않는다).

- 첫 확장: 일꾼 14기·광물 400 조건 후 `AIExpand()`, 중복은
  `AIIsExpandingOrHasExpanded()`로 차단.
- **`AIGetUserInt(player, 144)` 첫 확장 플래그 설정을 지우지 않는다.**
  `V3EnsureMiningExpansion`은 144가 0이면 즉시 반환한다. §108에서 이 한 줄이 빠져 저그 301의
  일꾼이 30→18, 기지가 2→1이 됐다.
- 첫 확장 이후에는 `AIIsExpandingOrHasExpanded()`를 쓰지 않는다 — 두 번째 town이 있으면
  계속 true라 후속 판정에 부적합하다.
- 각 종족 디스패처는 `V3EnsureMiningExpansion` 호출을 유지해야 한다. 검증기가 강제한다.
- 일꾼 목표는 `V3WorkerTarget(player, N)`을 거친다. 검증기가 우회를 잡는다.
  용량이 0이면 요청값을 그대로 돌려주므로 복구 상황에서도 동작한다.

## 금지

- `AIMakeCounters`, `AIDefaultExpansion`, `AIAdjustedDefaultExpansion`
- `AITrain`, `AIResearch`
- `v3/ai/upstream/**` 수정 (읽기 전용, SHA-256 고정)
- 검증기를 통과시키려고 `verify_v3_structure.py` 수정
- 오버레이 `.galaxy` 개수 변경 (10개 고정)

V3는 더 이상 "스톡 전용"이 아니다 — 스톡으로 멜리 AI가 안정적으로 못 만드는 것
(울트라리스크 모프, 집정관 합체, 테크 구조물)은 **게이트된** 직접 주문으로 처리한다.
스톡 전용으로 되돌리지 않는다.

## 검증

`.galaxy`를 고쳤으면 [`../../docs/harness.md`](../../docs/harness.md)의 게이트 1→5를 순서대로.
생산·전투 수치를 주장하려면 게이트 6까지.

```powershell
.\.venv\Scripts\python.exe v3\verification\verify_v3_structure.py
node v3\tools\build_v3_ai_mod.cjs <출력.SC2Mod> <plan.json>
.\.venv\Scripts\python.exe v3\verification\probe_v3_ground_builds.py --duration 360
.\.venv\Scripts\python.exe v3\verification\probe_v3_ground_builds.py --all-lingbane --mirror-count 12 --duration 1080 --report <out.json>
```

**`--mirror-count`는 이 맵에서 12만 정상 스폰한다** (6/8은 플레이어가 안 뜬다).
리포트 JSON의 `samples[].players[owner].counts[type]`으로 건물·유닛 수를 집계한다.

**커스텀 AI 생산을 측정할 때는 야생 저그를 끄고 돌린다** — 켜져 있으면 근처 슬롯이 실제로
얻어맞아 수치가 내려가고, 그걸 생산 회귀로 오진하게 된다(§104 선례).
