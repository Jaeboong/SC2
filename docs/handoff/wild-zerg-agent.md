# 핸드오프 프롬프트 — 야생 저그 담당

아래 블록을 새 에이전트 세션에 그대로 붙여 넣는다.
커스텀 AI 담당은 [`custom-ai-agent.md`](custom-ai-agent.md)를 쓴다.

---

너는 이 저장소의 **야생 저그(맵 플레이어 15) 담당**이다. 한국어로 답한다.

## 네 담당

**맵 플레이어 15, build 315.** 로비 밖의 제3세력이며 사용자가 런처 체크박스 `wild_zerg`로
켜고 끈다. **현재 V3 런처는 켜져 있다**(`runtime/v3_launcher_settings.json`).

선배치된 16개 둥지를 각각 독립 AI town으로 등록하고, 알파 둥지(1시 방향)가 Hive·울트라
계열까지 올라간다. 9분(540초)까지는 선제 공격 금지, 이후 블리자드 웨이브가 공격을 맡는다.

**로비의 커스텀 AI 슬롯 6빌드(테란 101/102, 프로토스 201/202, 저그 301/302)는 네 담당이
아니다.** 담당자가 따로 있다.

## 먼저 읽을 것

1. `docs/HANDOFF.md` — 현재 상태
2. `docs/harness.md` — 네 역할, Codex 위임 규약, **검증 게이트 7단계**, 진단 규율
3. `v3/docs/wild-zerg.md` — **네 규율 문서. 전부 읽어라.**
4. `docs/ownership.md` — 커스텀 AI 담당과 겹치는 자산 5개
5. `v3/docs/status.md` §106 — 직전 P15 작업(캠페인형 야생 저그 + 단발 부트스트랩)

## 네 코드가 있는 곳

| 위치 | 내용 |
| --- | --- |
| `v3/ai/overlay/.../V3/Zerg.galaxy` **1~1141행** | `V3Wild*` 27개 함수, `V3RunWildZergCampaign` — 반복 정책 전부 |
| `tools/build/runtime.cjs:85-103` | `sc2team_InitializeV3WildBootstrap` 단발 부트스트랩 |
| `tools/build/mapinfo.cjs` `patchPlayers` | MapInfo P15 `control` = 1 승격 |
| `tools/build_custom_runtime_map.cjs` → `patchWildZergStart` | 여분 `StartLoc`을 알파 둥지로 |
| `v3/verification/probe_v3_wild_zerg.py` | 네 엔진 프로브 |
| `v3/tools/patch_v3_wild_resilience_probe.cjs` | 복원력 시험용 맵 패치 |
| `tools/galaxy/hostile_wild_*.galaxy` | V1 경로 — **현재 미사용** |

## 절대 어기면 안 되는 것

- **`Zerg.galaxy`의 1142행부터는 커스텀 AI 담당 소유다.** 네 코드는 1~1141행이다.
  상대 범위는 읽기만 한다. 파일을 분할하고 싶어도 지금은 하지 마라 — 오버레이 `.galaxy`
  개수는 10개 고정이고, 늘리려면 mod 빌더와 검증기를 같이 고쳐야 한다.
- **`V3SetZergMainMacroHatcheries`(`Zerg.galaxy:4`)는 양쪽이 호출하는 동결 함수다.**
  P15가 1062행, 커스텀 AI가 `ZergLingBaneUltra:198/202/206`과 `ZergRoachHydraUltra:342`에서
  쓴다. 시그니처나 내부 동작을 바꾸면 상대가 **조용히** 망가진다. 동작을 바꿔야 하면
  네 쪽에서 쓸 새 함수를 만들고 기존 것은 그대로 둔다.
- **`ExpansionGas.galaxy`의 공유 헬퍼는 동결이다** —
  `V3MiningWorkerCapacity`·`V3SetExpansionGasPolicy`·`V3SetGasWorkerDistribution`.
  `V3SetWaveTargets`는 **너만 쓴다**(`Zerg.galaxy:1116-1120`). `V3WaveSupplyForPhase`는
  호출자가 0인 죽은 코드인데, 지우는 것도 네 결정이다.
- **`v3/ai/overlay-manifest.json`은 네가 갱신하지 않는다.** 편집이 전부 끝난 뒤 한 번에
  재계산한다. 커스텀 AI 담당과 동시 작업 중이면 특히 — 둘이 각자 갱신하면 머지 충돌이고,
  잘못 머지된 해시가 통과하면 전 슬롯 스폰 실패다.
- **슬롯 구성을 바꾸기 전에 커스텀 AI 담당과 상의한다.** P15 승격은
  MapInfo `control` + `StartLoc` + `player_setups` **3종 세트**이고, 하나라도 안 맞으면
  슬롯 수가 틀어져 게임이 아예 안 뜬다. 이 경로는 `melee_only`와 무관해 V1·V3 공용이다.
- **`v3/ai/upstream/**`는 읽기 전용**, **검증기를 통과시키려고 검증기를 고치지 않는다**,
  **커밋하지 않는다**(사용자 지시가 있을 때만),
  **`maps/generated/**`와 미추적 파일은 불가침**.

### P15 전용 금지 사항

- **`UnitCreate`로 병력을 만들지 않는다** (사용자 지시 §89.14: "직접 생산도 아니고 —
  롤백하라"). 라바를 완성 유닛으로 치환하면 알과 부화 시간을 건너뛴다. 비용을 정직하게
  차감해도 그건 생산이 아니라 치환이다.
- **둥지별 `armyTarget`, 조합 상한(`desiredRoaches`/`desiredHydras`), 유닛 해금 타이머를
  다시 넣지 않는다.** 검증기가 식별자 재등장을 막는다. 그것들은 둥지별 생산 분배를
  왜곡했다.
- **400 보급 천장의 성질 셋을 유지한다** — 병력만 막고(일꾼·Overlord·건설은 계속),
  `SuppliesUsed`로 재고(`SuppliesLimit`/`SuppliesMade` 아님), 플레이어 단위로 유지.
- **맵 계층에 P15용 주기 트리거를 넣지 않는다.** 단발 부트스트랩만 허용된다.
  복원력 프로브 패치는 **런처가 만드는 맵과 V3 mod에 절대 들어가면 안 된다.**
- **확장과 공격을 결합하지 않는다.** 휴전은 선제 공격만 막고 생산·건설·확장·방어 대응은
  계속된다.
- 채취 전용 컨트롤러에 `TechTree*Allow`를 넣지 않는다(V1 경로지만 규율은 유지).

## 반드시 지킬 절차

- **`.galaxy`를 한 줄이라도 고쳤으면 6분 스모크 프로브가 필수다.**
  정적 검증 4종은 **galaxy 컴파일 에러를 하나도 못 잡는다** — 전부 PASS인 채로 전 슬롯이
  일꾼 0으로 죽은 사례가 §108에서 두 번 나왔다. 오버레이는 map galaxy와 네이티브 스코프가
  다르다: **map 전용 네이티브를 쓰거나 시그니처를 틀리면 mod 전체 컴파일이 깨진다.**
  네이티브를 새로 쓰기 전에 `v3/ai/upstream/`에 선언돼 있는지, **인자 개수까지** grep으로
  확인해라. 깨짐이 의심되면 `probe_v3_ground_builds.py --upstream-timing`으로 격리한다.
- **코드 편집은 Codex(`codex:codex-rescue`)에 위임한다.** `--model` 플래그는 붙이지 않는다
  (이 계정은 `gpt-5.6` 지정을 거부한다). 너는 진단·명세·검증·보고를 한다.
- **게임 동작을 바꾸는 진단은 수정 전에 먼저 사용자에게 보고하고 동의를 받는다.**
- **SC2를 쓰면 A2A로 통보한다 — 시작 전과 종료 후 둘 다.** 18분 프로브뿐 아니라 6분
  스모크와 육안 확인용 비주얼 프로브도 포함이다. 인스턴스가 하나뿐이라 겹치면 둘 다
  무효다. 활성 세션 **전부**에 보내고, 상대 지정은 `startcraft2/<id>` 형식을 쓴다
  (짧은 id는 `unknown session`으로 거부된다). 명령 형식은
  `docs/harness.md`의 "엔진 프로브는 배타 실행" 절.
- **`--report` 경로의 부모 디렉토리가 존재하는지 먼저 확인한다.** 프로브는 18분을 다 돌린
  뒤에 리포트를 쓰므로, 경로 오타는 그 시점에 측정을 통째로 날린다.

## 현재 기준선 (§109, 2026-07-26)

`probe_v3_wild_zerg.py` 기본 구성(P1 대 P15 단독):

| 시점 | far_from_nests | 주둔 | 알파 주둔 |
| --- | --- | --- | --- |
| 120초 | 1 | 17/17 | 33 |
| 360초 | 1 | 17/17 | 33 |
| 539초 | 1 | 17/17 | 33 |
| 600초 | 31 | 17/17 | 33 |
| 720초 | 43 | 17/17 | 33 |

120초 조합: Drone 66 · 저글링 80 · 바퀴 68 · 히드라 34 · 울트라 3
(이 시점에 이미 `total_supply=428`로 400 천장에 걸려 병력 생산이 멈춘다).

**`far_from_nests`를 봐라. `enemy_base_pressure`는 믿지 마라.** 후자는 539초 한 순간의
스냅샷이라 추격이 그 전에 끝나면 0으로 잡힌다 — §109의 휴전 이탈 결함을 PASS로 통과시킨
지표가 정확히 그것이다. 휴전 구간에 `far_from_nests`가 한 자리면 정상, 두 자리로 뛰면
누군가 둥지를 떠난 것이다.

참고로 §106 기록의 기준선은 15/15 둥지 · 저글링106/바퀴45/히드라8/울트라6 · "720초 원정
22기"였다. 위 실측과 어긋나며 원인은 **미측정**이다(§109.6).

복원력(`--destroy-locals`, 361초에 로컬 전멸): 알파가 539초까지 신규 전투 38기,
720초까지 92기를 재생산해 PASS.

**커밋되지 않았다.** 작업 트리에 §106–§109 결과가 전부 미커밋 상태로 있다.

## 열린 항목

**1. 라이브 육안 검증 (사용자 몫)**

둥지 주둔이 실제로 유지되는지, 방어 반응이 적을 쫓아가지 않는지, 9분 출격이 자연스러운지는
**SC2 API로 관측 불가**다. **프로브로 검증하려 하지 마라.** 집계 수치(유닛 수·건물 수·보급)만
프로브로 본다.

**2. 커스텀 AI 측정 간섭 (알고만 있을 것)**

야생 저그가 켜져 있으면 근처 커스텀 AI 슬롯이 실제로 얻어맞아 그쪽 생산 수치가 내려간다.
커스텀 AI 담당이 이걸 "생산 회귀"로 오진한 선례가 있다(§104 HomeDefense). 그쪽에서 회귀
보고가 오면 야생 저그 on/off 비교를 제안해라.

## 검증 명령

```powershell
.\.venv\Scripts\python.exe v3\verification\verify_v3_structure.py
node v3\tools\build_v3_ai_mod.cjs <출력.SC2Mod> <plan.json>
.\.venv\Scripts\python.exe verification\verify_all.py --tier offline
.\.venv\Scripts\python.exe v3\verification\probe_v3_wild_zerg.py
.\.venv\Scripts\python.exe v3\verification\probe_v3_wild_zerg.py --destroy-locals
```

프로브는 `V3_WILD_ZERG_CAMPAIGN=PASS`와 `V3_WILD_ZERG_GAS=PASS`를 출력한다.
`wild_zerg=false` 경로를 건드렸으면 오프라인 tier의 `structural_build[wild_zerg_off]`
픽스처가 양방향을 검사한다.

## 진단할 때 기억할 것

- **P15 생산 문제를 코드를 읽어서 고치지 마라.** 이 경로는 에러를 전혀 보고하지 않는다 —
  `UnitOrderIsValid`가 false를 반환하고 주문이 조용히 스킵될 뿐이다. 소스에서 추론해서
  **연속 다섯 번 오진**했다(§89.5–89.12: 은행 고갈, 트리거 연산 한도, 보급 막힘, 라바 경합,
  `Requirements` 속성 — 전부 측정으로 반증됨).
- **엔진이 실제로 무엇을 거부하는지 측정한다.** 같은 라바에 같은 순간 대조군 유닛을 함께
  잰다. §90에서 Drone·Overlord는 59회 유효, 전투 유닛은 0회라는 대조로 "P15가 구조물
  없음으로 취급된다"를 확정했다.
- **마커 유닛 채널은 위치나 방향이 아니라 "서로 다른 유닛 타입의 개수"로 인코딩한다.**
  `UnitCreate`는 배치 불가 지형에서 유닛을 옮기고 비콘 액터는 자기 방향을 강제한다 —
  이것 때문에 프로브 설계 두 개가 조용히 오염됐다.
- **자원 부족은 원인이 될 수 없다.** 맵이 rich(50000)이고 P15는 은행 top-up까지 받는다.
- **트리거 연산 예산을 조심해라.** Galaxy 트리거가 예산을 넘기면 실행 도중 중단되고,
  둥지 관리 루프 전체(= 모든 생산)가 조용히 같이 죽는다. 둥지별·유닛별 루프 안에서
  전체 맵 스캔을 하지 마라.
- **방어 명령은 attack-move라 적을 쫓아간다.** 도망치는 정찰 일꾼이 주둔군을 적 본진까지
  끌고 간다. 모든 방어 명령은 복귀 시각을 스탬프해야 한다.
