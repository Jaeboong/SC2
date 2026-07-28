# HANDOFF

갱신: 2026-07-26

## 현재 버전

- **V3 임베디드 AI 모드 (현재 플레이 대상):** 앱 `3.2.0` / AI `V3.16` — 진입점
  `start_custom_ai_v3.cmd` → `app/play_custom_ai_v3.py` → `v3/sc2team_v3`.
  작업 로그: [`v3/docs/status.md`](../v3/docs/status.md).
  Blizzard 멜리 AI에 주입되는 오버레이 SC2Mod(`v3/ai`).
- **V1 런타임 맵 시스템:** `1.25.0` — **AI 계층은 비활성**(사용자가 V3만 플레이).
  맵 빌더 계층은 V3가 `melee_only=True`로 계속 사용한다.
  규율 아카이브: [`history/v1-ai-rules.md`](history/v1-ai-rules.md).

> **주의:** V3 변경은 `start_custom_ai_v3.cmd`로 실행해야 반영된다.
> `start_custom_ai.cmd`(V1)에는 없다.

## 하네스

- 역할·위임·검증 게이트·진단 규율: [`harness.md`](harness.md)
- 담당 경계(커스텀 AI / 야생 저그): [`ownership.md`](ownership.md)
- 규율 라우팅: [`../CLAUDE.md`](../CLAUDE.md) / [`README.md`](README.md)

## 활성 브랜치 / 최근 커밋

브랜치: `agent/v3-custom-ai-expansion-fix`

- `79fff4e` v3: 프로토스 Forge/Twilight/Templar를 AIBuild로
- `f2c4738` v3: 302 테크 구조물을 (드론 직접주문 아닌) AIBuild로
- `0155b23` v3: 302 직접 하이브 사슬 + 전군 회군 제거 + galaxy 컴파일 함정 2개 수정

(작업 트리에 사용자 맵 `map/source/...SC2Map`, HANDOFF 삭제분, 다른 잡의 Terran/Protoss
변경 등 미커밋 상태가 섞여 있음. 커밋은 항상 사용자 맵·미추적 파일 제외하고 V3 파일만 골라서.)

## 이번 세션(V3.16) 완료 + 검증

- **P15 캠페인형 야생 저그 build 315:** 선배치 둥지를 각각 독립 AI town으로 등록하고,
  본진·로컬별 생산/정적 방어/`GuardHome` 주둔을 V3 `Zerg.galaxy`에 구현했다. 알파는
  6 Spine/4 Spore·주둔 32기, 로컬은 2/2·주둔 10기를 최소 기준으로 쓴다.
- **9분 휴전:** 540초 전에는 `Wait` 상태를 계속 주입해 선제 공격만 금지하고 town 방어는
  유지한다. 540초에 V3 내부에서 한 번 `Attack` 상태로 넘긴 뒤 Blizzard 웨이브가 공격을 맡는다.
- **단발 외부 하네스 예외:** `MeleeInitAI()` 직후 P15에 `AIMeleeStart` + campaign town/harvest
  초기화 + build 315/공격 지연 seed + 50,000/50,000 자원 주입을 **각 1회만** 한다. 맵 쪽
  주기 트리거로 생산·경제·주둔·전투·공격 해제를 수행하지 않는다.
- **7v7 비의존:** 일반 V3 선택 플레이어가 0명이어도 `wild_zerg=true`면 plan/map patch를
  허용한다. 기본 야생저그 프로브는 P1 한 명 대 P15만으로 실행한다.
- **엔진 실측:** 120초 15/15 둥지 주둔, Drone 67·Ling 106·Roach 45·Hydra 8·Ultra 6;
  539초 적 기지 압박 0·15/15 주둔; 720초 둥지 밖 원정 22기로 9분 후 출격 확인.
  361초에 로컬 전부 제거한 복원력 프로브도 알파가 539초까지 신규 전투 38기,
  720초까지 92기를 재생산해 PASS.
- **§109 휴전 중 추격 출격 차단 (2026-07-26):** 사용자 관측 "야생저그가 2~3분에 본진을
  박살낸다". 원인은 `V3WildDispatchLocalSupport`가 540초 게이트 **바깥**에서
  `AIWaveTargetUnitGroup(threats)`로 주둔군을 내보낸 것 — `attackState`를 거치지 않아
  `Wait`이 무력했고, 목표가 좌표가 아니라 적 유닛 그룹이라 정찰 일꾼을 본진까지 쫓아갔다.
  호출을 540초 이후로 이동 + helper 거리 상한 40 + 선배치 인수 재시도. 실측은
  휴전 구간 `far_from_nests` 1기, 해제 후 600초 31 → 720초 43, 주둔 17/17 유지.
  상세와 한계(대조군 미측정)는 `v3/docs/status.md` §109.

- **전군 회군 제거**, 주둔+국소방어 유지 (정적 검증만; 실효는 라이브 육안 몫).
- **302 테크 정지 수정:** 드론 직접주문은 무효, **AIBuild로 InfestationPit/Cavern 발주** →
  레어 정지 8/12→4/12, Hive 4/12→8/12, 첫 `V3_GROUND_BUILDS=PASS` (18분 12슬롯 미러 실측).
- **프로토스 Forge/Twilight/Templar를 AIBuild로** → Forge 11/12→12/12, Templar 10/12→11/12.
- **핵심 교훈(중요):** 테크 **구조물** 강제는 `AIBuild`(멜리 AI 배치+워커), **morph는 `UnitIssueOrder`**.
  우리가 직접 드론 잡아 배치하는 주문은 실패한다(측정). 상세: [[v3-allows-targeted-direct-orders]] 취지 =
  `v3/docs/status.md` V3.15, `v3/docs/build-integration.md` "함정" 절.

## 임의 맵 지원 (진행 중)

목표: 어떤 맵을 넣어도 처리한다. 플레이어 2~14명, 팀 수 상한은 인원이 정한다
(2명→2팀, 3명→3팀, 4명부터 4팀). 야생 저그는 P15 캠프가 있는 맵에만.

**끝난 것**

| | |
| --- | --- |
| 맵 능력 판정 | `tools/map_capabilities.cjs` → 수용 인원·팀 상한·시작 지점·P15 캠프·기하. 못 읽는 맵은 이유를 실어 돌려주고 목록에서 사라지지 않는다. |
| 수용 인원 상한 | MapInfo 슬롯 − 2 (중립·적대). 전 맵 성립 확인. 슬롯을 새로 만드는 경로는 없다. |
| 좌표 기반 팀 배치 유도 | `sc2team/team_layout.py`. 인원 균등 제약 아래 총 방위 비용 최소를 DP 로 정확히 푼다. |
| 미니맵 프리뷰 | `tools/make_map_previews.py` → `map/img/`. 시작 지점에 P 라벨을 팀 색상으로. 규칙은 [`rules/map-layer.md`](rules/map-layer.md). |
| 런처 맵 선택 + 프리뷰 패널 | `app/play_custom_ai_v3.py` 오른쪽 패널. 선택은 `runtime/v3_launcher_settings.json` 의 `map` 키에 저장. |
| 야생 저그 맵 조건 강제 | 캠프나 여분 시작 지점이 없으면 `wild_zerg=False` 로 강제하고 체크박스를 잠근다. 아래 참조. |

### 야생 저그 맵 조건

두 조건을 동시에 만족해야 켤 수 있다 — 선배치된 P15 저그 본진(없으면 §90 때문에
전투 유닛을 한 기도 못 만든다)과 활성 플레이어가 쓰고 남은 시작 지점 하나
(P15 를 로비 Computer 로 승격시킬 때 그 자리를 준다). 판정은
`MapProfile.wild_zerg_available(활성_플레이어_수)`.

**활성 플레이어 수로 센다 — 수용 인원이 아니다.** 슬롯을 켜면 여분 시작 지점이
사라져 조건이 뒤집히므로, 갱신이 세 시점에서 일어난다: 맵 변경, 프로필 로드,
**슬롯 컨트롤러 변경**. 실행 중에는 잠금이 풀리지 않는다.

`_start` 에 이중 가드가 있다. `runtime/v3_launcher_settings.json` 에 옛
`wild_zerg: true` 가 남아 있어도 그 조합으로는 시작되지 않는다.

동작 확인은 단위 테스트가 순수 함수(`wild_zerg_availability`)만 덮는다. 위젯 잠금·
강제 해제·조건 뒤집힘은 런처를 조립해 위젯 상태를 읽는 방식으로 확인했다(8항목).

### 2~14인 지원: 1단계 완료 (설정 계층)

**진짜 걸림돌은 숫자 14 가 아니라 고정표 역대조였다.** `team_mode_for_slots` 가
팀 배치를 `TEAM_LAYOUTS`(길이 14 튜플 3개)와 대조해 팀 수를 복원했다. 임의 인원
맵에는 대응 표가 없어 무조건 예외였다. 이제 팀 번호를 센다 — 1..N 연속이고
N 이 2~4 면 통과. 슬롯 수는 P1 부터 연속 2~14.

**같은 검사가 `tools/build/mapinfo.cjs` 의 `validateConfig` 에 미러링돼 있다.**
둘은 같은 계약의 양쪽이라 한쪽만 풀면 런처는 통과시키고 빌더가 거부한다. 양쪽을
같이 고쳤고 사례 12종으로 판정이 일치함을 확인했다(프리셋 3종, 2·3·4슬롯,
프리셋 아닌 배치, 팀 번호 구멍, 팀 5개, 한 팀, 팀 0, 15슬롯).

의도적 완화다 — 프리셋이 아닌 배치도 받는다. 좌표에서 유도한 배치를 써야 하므로
어쩔 수 없고, 연속·2~4 조건으로 쓰레기 배치는 계속 거부한다.

**남은 것**

1. **2~14인 지원 2단계** — 아직 14인 맵만 실행된다(`map_blocker` 가 그 외를 막는다).
   남은 곳: 런처의 14행 UI(맵 인원만큼 행을 만들고 팀 배치를 `resolve_team_layout`
   에서 받아야 한다), `tools/build/mapinfo.cjs` 의 `patchPlayers`
   (`activeSlots[player.id - 1]` 가 길이 14 배열을 전제), `v3/sc2team_v3/config.py`
   의 슬롯 상한(값은 맞으나 확인 필요), `SlotConfig.side` 의 `slot <= 7`.
   `unit_control.cjs` 와 `strategy_controller.py` 의 `1..14` 는 런타임 ID 범위라 그대로 둔다.
3. **로비 Attributes 를 맵 슬롯 수에 맞춰 생성** — `tools/build_team_map.cjs` 가
   7v7/14슬롯 XML 을 하드코딩한다.
4. **[별도조사] MapInfo 파서 견고화** — 순차 위치 파싱이라 선택적 필드가 있는 맵에서
   어긋난다. Torches LE 실측: `str4` 가 4바이트 길어 오프셋 88 에서 u16 길이를 29505 로
   읽는다. 지금은 개연성 검사로 깔끔히 거절한다. 공수 미지.

**동의가 필요한 것 하나** — 3팀 배치가 바뀐다. 기존 고정표는 의도적 비대칭
(남부 7 / 북서 4 / 북동 3)이고, 임의 맵에 쓸 일반 규칙인 균등 분배로는
북서 5 / 북동 5 / 남부 4 가 된다. 2팀·4팀은 고정표와 **완전히 일치**한다.
지금은 `resolve_team_layout` 이 14슬롯 맵에 고정표를 그대로 쓰므로 **동작은 그대로다.**

## 열린 항목 (다음 우선순위)

1. **저그 극단 "저글링 홍수" 4슬롯** — 테크 이전 상류 행동. 4/12가 드론~28·저글링 100+·InfestPit 0으로
   경제·테크 방치. AIBuild로도 안 됨(멜리 빌드매니저가 병력에 매몰). §68 병력캡 금지라 **경제/라바 넛지**로
   접근해야 함. 원인 아직 미측정.
2. **회군 제거 라이브 확인** — "다들 집콕/아무도 공격 안 감"이 실제로 풀렸는지 육안. 안 풀리면 주둔(25%)·
   국소방어 자체를 손봐야 함.
3. **업그레이드** — 저글링 아드레날린(`c_ZR_ZerglingHaste`)이 302 빌드에 **아예 없음**(진짜 누락). 히드라
   사거리/바퀴 이속 등은 요청은 하나 실제 리서치 여부 계측 필요. (히드라 "이속" Muscular Augments는 LotV
   멜리에 없음 — Grooved Spines에 통합.)

## 빌드 / 검증

전체 게이트 표는 [`harness.md`](harness.md)에 있다. 자주 쓰는 것:

- V3 정적: `.\.venv\Scripts\python.exe v3\verification\verify_v3_structure.py` → `V3_STRUCTURE=PASS`
- V3 mod 빌드: `node v3\tools\build_v3_ai_mod.cjs <출력.SC2Mod> <읽기가능 .v3plan.json>` → `V3_AI_MOD_BUILD=PASS`
- 오프라인 tier: `.\.venv\Scripts\python.exe verification\verify_all.py --tier offline`
- 파이썬 단위 테스트: `.\.venv\Scripts\python.exe -m unittest discover -s tests -q`
  (pytest 는 설치돼 있지 않다)
- 맵 능력 확인: `node tools\map_capabilities.cjs map\source` (디렉터리·파일 모두 받는다)
- 맵 프리뷰 재생성: `.\.venv\Scripts\python.exe tools\make_map_previews.py --force`
- **스모크(필수, galaxy 수정 시):** `probe_v3_ground_builds.py --duration 360`
- V3 엔진(18분 미러, SC2 닫고): `probe_v3_ground_builds.py --all-lingbane|--all-roach-hydra|--all-gateway
  --mirror-count 12 --duration 1080 --report <out.json>` — `--mirror-count`는 **이 맵에선 12만 정상 스폰**
- P15 단독 엔진: `.\.venv\Scripts\python.exe v3\verification\probe_v3_wild_zerg.py` (`--destroy-locals`로 복원력)

규율 상세: [`../v3/docs/overlay-rules.md`](../v3/docs/overlay-rules.md)(커스텀 AI) /
[`../v3/docs/wild-zerg.md`](../v3/docs/wild-zerg.md)(야생 저그) /
[`rules/map-layer.md`](rules/map-layer.md)(맵 계층).
