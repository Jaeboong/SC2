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

(작업 트리에 사용자 맵 `maps/generated/...SC2Map`, HANDOFF 삭제분, 다른 잡의 Terran/Protoss
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
- **스모크(필수, galaxy 수정 시):** `probe_v3_ground_builds.py --duration 360`
- V3 엔진(18분 미러, SC2 닫고): `probe_v3_ground_builds.py --all-lingbane|--all-roach-hydra|--all-gateway
  --mirror-count 12 --duration 1080 --report <out.json>` — `--mirror-count`는 **이 맵에선 12만 정상 스폰**
- P15 단독 엔진: `.\.venv\Scripts\python.exe v3\verification\probe_v3_wild_zerg.py` (`--destroy-locals`로 복원력)

규율 상세: [`../v3/docs/overlay-rules.md`](../v3/docs/overlay-rules.md)(커스텀 AI) /
[`../v3/docs/wild-zerg.md`](../v3/docs/wild-zerg.md)(야생 저그) /
[`rules/map-layer.md`](rules/map-layer.md)(맵 계층).
