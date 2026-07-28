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

### 2~14인 지원: 2단계 완료 (맵 준비기와 빌드 경로)

**2~14인 맵이 빌드까지 끝까지 통과한다.** 실측:

```
설정: 슬롯 4 팀 2 활성 4 야생저그 False
BUILD_OK map=np-prepared-Flat128-4-4.SC2Map bytes=61554
설정: 슬롯 2 팀 2 활성 2 야생저그 False
BUILD_OK map=np-prepared-Simple64-2-2.SC2Map bytes=84422
```

**이미 인원 무관하게 동작하던 것 — 손대지 않았다.** `patchPlayers` 의
`activeSlots` 는 `[사람, ...커스텀AI]` 로 **압축된** 목록이고 MapInfo 플레이어 id 로
인덱싱한다. 활성이 8명이면 플레이어 9~14 는 `undefined` 가 되어 control 0 으로
꺼진다. `player_setups`·`runtime_player_id`·`v3_players` 도 전부 활성 슬롯 기준이다.

**고친 것 셋:**

1. `parseMapInfoPlayers` 의 15~16 제한. MapInfo 는 `사용 가능 인원 + 2`(id 0 과
   id 15)를 담는다 — Flat128 은 6(`0,1,2,3,4,15`), Simple64 는 4(`0,1,2,15`).
   최소 3개만 요구하도록 완화했다.
2. `build_custom_runtime_map.cjs` 에 용량 검사 추가. MapInfo 논리 플레이어 수가
   `activeSlots.length` 보다 적으면 실패한다. 위 15~16 검사가 하던 파싱-어긋남
   방어를 이게 대신한다.
3. `build_team_map.cjs` 의 7v7 하드코딩 네 곳 — 시작 지점 서/동 분할,
   `patchFixedPlayerStarts` 루프, Attributes XML(`MaxTeamSize`, 2011 슬롯 배정),
   커스텀 블록 galaxy 루프. `--players N` 으로 지정하고 기본값은 맵 수용 최대치다.
   **N=14 에서 Attributes·Galaxy 문자열이 바이트 단위로 이전과 같다.**

로비는 항상 2팀이다. 3·4팀은 로비 팀이 아니라 인게임 동맹이다.

### 검증기의 P15 둥지 앵커 검사 (게이트 추가)

`verify.cjs` 의 둥지 앵커 검사가 `wildZergActive` 게이트 **밖**에 있었다(게이트
블록은 358~397·1811~1844, 검사는 588행). 그래서 P15 저그 둥지가 없는 맵은 **야생
저그를 꺼도** 빌드가 거부됐다 — 임의 맵 지원의 유일한 남은 차단점이었다.

게이트를 끼우기 전에 세 가지를 실증했다:

- 이 검사만 열면 4인·2인 맵이 V3 파이프라인을 **끝까지** 통과한다(뒤에 다른
  차단점이 없다).
- 게이트를 끼운 뒤에도 **야생 저그를 켜면** 캠프 없는 맵은 여전히 막힌다 —
  `Wild Zerg has no town hall in Objects` 가 먼저 잡는다. 불변식이 이중 보호된다.
- 14인 오프라인 tier 무영향.

야생 저그가 꺼져 있으면 P15 는 둥지가 있든 없든 아무것도 생산하지 못한다(§90).
그래서 이 게이트는 인게임 동작을 바꾸지 않는다.

### 2~14인 지원: 3단계 완료 (런처 UI) — 목표 달성

맵을 고르면 행이 그 맵 인원만큼 다시 만들어지고, 팀 배치는 좌표에서 나오며,
팀 수 콤보가 맵 상한까지만 뜬다. `map_blocker` 는 이제 **2명 미만**만 막는다.

실측(임시 맵 디렉터리에 세 맵을 모아 런처를 조립):

| 맵 | 행 | 팀 콤보 | 배치 |
| --- | --- | --- | --- |
| europe 14인 | 14 | 2·3·4 | 2팀 `(1,1,1,1,1,1,1,2,2,2,2,2,2,2)` **고정표 일치** |
| | | | 3팀 `(3,3,3,1,1,1,1,3,3,3,2,2,2,3)` 기존 비대칭 유지 |
| | | | 4팀 `(3,3,3,1,1,1,1,4,4,4,2,2,2,4)` **고정표 일치** |
| Flat128 4인 | 4 | 2·3·4 | `(1,1,2,2)` / `(3,1,3,2)` / `(3,1,4,2)` |
| Simple64 2인 | 2 | **2만** | `(1,2)` |

전부 `validate()` 통과. **14인 배치는 한 칸도 바뀌지 않았다** —
`resolve_team_layout` 이 14슬롯에 고정표를 쓰기 때문이다.

행 재생성은 기존 `SlotRow` 위젯을 `destroy()` 한 뒤 다시 만든다
(`grid_remove()` 만 하면 위젯이 누적된다). 슬롯이 줄면 앞쪽 설정을 보존하고,
사람 슬롯이 잘려 나가면 P1 을 사람으로 복구한다.

**남은 것**

1. **축소 -> 확대 후 로비가 무효가 될 수 있다 (실측).** 14인 -> 2인 -> 14인 으로
   돌아오면 살아남은 활성 슬롯이 P1·P2 뿐이고, 14칸 2팀 배치에서 둘 다 1팀이라
   활성 팀이 하나가 된다. 야생 저그가 꺼져 있으면(캠프 없는 맵을 거치면 강제로
   꺼진다) `validate()` 가 "최소 두 팀" 으로 거부한다. 배치 자체는 정상이고
   시작 버튼을 누를 때까지 드러나지 않는다. 행을 다시 만든 뒤 활성 팀이 2개
   미만이면 필요한 최소 개수만 활성화해 항상 유효한 로비를 유지해야 한다.
2. ~~**[별도조사] MapInfo 파서 견고화**~~ — **해결됨.** 아래 절 참고.

`unit_control.cjs` 와 `strategy_controller.py` 의 `1..14` 는 런타임 ID 범위라 그대로 둔다.
`SlotConfig.side` 의 `slot <= 7` 은 V1 계층 전용이라 범위 밖.
3. **로비 Attributes 를 맵 슬롯 수에 맞춰 생성** — `tools/build_team_map.cjs` 가
   7v7/14슬롯 XML 을 하드코딩한다.
4. ~~**[별도조사] MapInfo 파서 견고화**~~ — **해결됨.** 아래 절 참고.

**동의가 필요한 것 하나** — 3팀 배치가 바뀐다. 기존 고정표는 의도적 비대칭
(남부 7 / 북서 4 / 북동 3)이고, 임의 맵에 쓸 일반 규칙인 균등 분배로는
북서 5 / 북동 5 / 남부 4 가 된다. 2팀·4팀은 고정표와 **완전히 일치**한다.
지금은 `resolve_team_layout` 이 14슬롯 맵에 고정표를 그대로 쓰므로 **동작은 그대로다.**

### MapInfo 파서 견고화 — 해결 (2026-07-28)

**원인은 로드스크린 이미지 경로였다.** 이전 기록의 "`str4` 가 4바이트 길어서"는
오독이다. 문자열은 길이를 동적으로 읽으므로 길이 차이 자체는 정렬을 깨지 않는다.

`loadScreenType` 뒤의 경로는 **타입 값과 무관하게 항상 오는 cstring** 인데,
파서가 `if (loadScreenType === 2)` 로 걸어 두었다. 두 맵 모두 타입은 `0` 이다:

| 맵 | 경로 | playerCount 오프셋 |
| --- | --- | --- |
| Flat128 | `""` (종결 바이트 하나) | 147 |
| Torches LE | `Assets\Textures\ui_void_loading_taldarim01.dds` | 197 |

우리 맵이 지금까지 멀쩡했던 건 **우연이다.** 빈 문자열의 종결 바이트 `0x00` 을
파서가 뒤따르는 u16 의 첫 바이트로 잘못 삼켰고 둘 다 0 이라 값이 안 바뀌었으며,
1바이트 밀린 오프셋을 뒤쪽 고정 스킵(61바이트)이 정확히 상쇄했다. 경로가 실재하는
순간 46바이트가 통째로 밀려 `readU16()` 이 29505 를 읽고 버퍼 밖으로 튄다.
**로드스크린 이미지를 지정한 맵이면 무엇이든 걸린다** — 래더 맵만의 문제가 아니다.

고친 것 (`tools/build/mapinfo.cjs` 한 파일):

- 로드스크린 경로를 조건 없는 cstring 으로 읽고, 뒤 불투명 구간을 61 -> **60바이트**로.
- 근거 없던 `if (previewType === 2) readCString()` 두 줄 제거. 실측 레이아웃은
  `u32, u32, cstring, cstring` 이다 — (타입, 경로) 쌍이라면 오프셋 28 이 문자열이어야
  하는데 그 바이트는 `0x01` 이다. 22개 맵 전부 previewType 이 1 이라 한 번도 실행된 적이 없다.
- 플레이어 표 정합성 검사 강화. 기존 "64 이하" 는 너무 성기다. 22개 맵에서 예외 없이
  id 가 `0, 1..N, 15` 였다 — 이 모양(0 으로 시작, 15 로 끝, 엄격 증가, 0..15 범위)과
  버퍼 오버런을 검사로 승격시켰다.

검증 (맵 22개 전수, HEAD 파서 복제본과 대조):

```
맵 22개: 새 파서 성공 22 / 기존 파서 성공 21 / 구제됨 1
기존 21개 전부 SAME — geometry·플레이어 목록·오프셋까지 완전 동일
torches-le-Pro-Bot_test  RESCUED  slots=4 ids=0,1,2,15 160x208 bounds=14,32,142,176
음성 대조 6종 전부 거절 (첫 id 위반 / 마지막 id 위반 / 엄격증가 위반 /
                        0..15 이탈 / 개연성 초과 / 잘린 버퍼)
MAPINFO_REGRESSION=OK
```

게이트: `Ran 108 tests / OK`, `VERIFY_ALL[offline]=PASS (13 checks, 0 failed)`,
`LAUNCHER_SMOKE=OK`, `MULTIMAP_CHECK=OK`. `.galaxy` 는 건드리지 않았으므로 스모크
프로브 대상이 아니다.

## 엔진 프로브 (2026-07-28, HEAD 4e07150)

밀려 있던 게이트 5를 통과시켰다. 두 판 모두 SC2 점유 전후 A2A 통보를 보냈다.

**게이트 5 — 6분 스모크** (`probe_v3_ground_builds.py --duration 360`)

```
RAW_OWNERS at=5s counts={1: 10, 2: 9, 3: 9, 4: 9, 5: 13, 6: 13, 15: 252, 16: 734}
GROUND_COMPILE=PASS source=V3_CUSTOM players=6 unit_types=2018
```

여섯 슬롯 전원 스폰, 6분에 전원 2번째 기지 완성(`expansions=1`), 일꾼 평균 26.7.
**galaxy 는 깨지지 않았다** — 이 게이트의 목적이 그것이다.

전체 판정은 FAIL 로 나왔는데 성격이 둘로 갈린다:

- **duration 부작용:** 로스터 2종 기준은 기본 duration 900 초를 전제로 쓰였다.
  P2 테란 메카닉(골리앗·사이클론·시즈탱크·토르)과 P4 프로토스 로보(이모탈·
  콜로서스)는 6분에 존재할 수 없는 로스터다. 6분 스모크에서는 이 실패를 무시한다.
- **진짜 신호:** P5 저그 바퀴·히드라 일꾼 14. 이 검사는 코드에서 `duration >= 360`
  으로 6분에 걸도록 설계됐고 경계(`<= 14`)를 정확히 밟았다. 아래 열린 항목 참조.

**프로토스 확장 재현 — 2v2 9분** (`--all-gateway --mirror-count 4 --duration 540`)

`V3_GROUND_BUILDS=PASS`. 리포트: `runtime/reports/protoss-gateway-2v2-540.json`.

정체가 재현되던 구성(확장 후보가 많이 남는 2팀 2v2)에서 생산이 멈추지 않는다:

| 3분 → 6분 → 9분 | |
| --- | --- |
| 일꾼 | 16.2 → 27.2 → **52.2** |
| 병력 보급 | 0 → 5.0 → 15.5 |
| 기지 | 1.0 → 2.0 → 2.5 (최대 3) |
| 가스 | 2.0 → 2.0 → 4.5 (`gas_sat` 13.5/13.5 포화) |

리서치도 실제로 돈다 — WarpGate, GroundWeapons1, Charge, Shields1, GroundArmor1.
집정관 1기(P2), 고위기사 2기(P3·P4)까지 나왔다. 게이트된 AIBuild/Morph 경로가
살아 있다는 뜻이다.

## 열린 항목 (다음 우선순위)

1. **P5 저그 바퀴·히드라 일꾼 정체 (신규, 2026-07-28 실측)** — 6분에 13 -> 14.
   같은 판에서 다른 슬롯은 16~17 -> 26~30, **같은 저그인 P6 링·맹독은 12 -> 33**
   이므로 종족 문제가 아니다. P5 는 라바를 병력에 돌렸다(바퀴 3·라바저 2, 병력
   보급 12). 기존 저그 경제 미달과 같은 계열로 보이나 **원인 미측정.**
   [[zerg-expansion-gas-aibuild-regresses]] 대로 AIBuild 직접 확정은 역효과였다.
   게임 동작 변경이므로 수정 전 사용자 동의 필요.
2. **저그 극단 "저글링 홍수" 4슬롯** — 테크 이전 상류 행동. 4/12가 드론~28·저글링 100+·InfestPit 0으로
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
