# 담당 경계: 커스텀 AI / 야생 저그

담당자 두 명이 동시에 일할 때 **무엇이 누구 것인지**, 그리고 **겹치는 것을 어떻게 다루는지**.

담당은 이렇게 나뉜다:

- **커스텀 AI 담당** — 사용자가 로비에서 고르는 AI 슬롯(테란 101/102, 프로토스 201/202,
  저그 301/302). 규율: [`../v3/docs/overlay-rules.md`](../v3/docs/overlay-rules.md)
- **야생 저그 담당** — 맵 플레이어 15, build 315. 로비 밖의 제3세력.
  규율: [`../v3/docs/wild-zerg.md`](../v3/docs/wild-zerg.md)

둘 다 [`harness.md`](harness.md)와 [`rules/map-layer.md`](rules/map-layer.md)를 공유한다.

## 단독 소유

| 커스텀 AI 담당 | 야생 저그 담당 |
| --- | --- |
| `v3/ai/overlay/.../V3/Terran.galaxy` | `v3/ai/overlay/.../V3/Zerg.galaxy` **1~1141행** |
| `v3/ai/overlay/.../V3/TerranBionic.galaxy` | `tools/build/runtime.cjs`의 `sc2team_InitializeV3WildBootstrap` |
| `v3/ai/overlay/.../V3/TerranMechanic.galaxy` | `tools/build/mapinfo.cjs`의 `patchPlayers` P15 승격 |
| `v3/ai/overlay/.../V3/Protoss.galaxy` | `tools/build_custom_runtime_map.cjs`의 `patchWildZergStart` 호출 |
| `v3/ai/overlay/.../V3/ProtossGateway.galaxy` | `v3/verification/probe_v3_wild_zerg.py` |
| `v3/ai/overlay/.../V3/ProtossGatewayRobo.galaxy` | `v3/tools/patch_v3_wild_resilience_probe.cjs` |
| `v3/ai/overlay/.../V3/ZergLingBaneUltra.galaxy` | `tools/galaxy/hostile_wild_*.galaxy` (V1 경로, 현재 비활성) |
| `v3/ai/overlay/.../V3/ZergRoachHydraUltra.galaxy` | |
| `v3/ai/overlay/.../V3/Zerg.galaxy` **1142~끝** | |
| `v3/verification/probe_v3_ground_builds.py` | |

## 공유 자산 — 여기가 전부다

겹치는 것은 정확히 다섯 개다. 각각 처리 규칙이 다르다.

### 1. `v3/ai/overlay/.../V3/Zerg.galaxy` — 한 파일, 두 시스템

1,259줄짜리 파일 하나에 두 시스템이 다 들어 있다.

| 행 | 내용 | 소유 |
| --- | --- | --- |
| 1~3 | 헤더 | — |
| 4~53 | `V3SetZergMainMacroHatcheries` | **양쪽 공유** (아래 참조) |
| 54~1141 | `V3Wild*` 27개 함수, `V3RunWildZergCampaign` | 야생 저그 |
| 1142~1259 | `V3EnsureZergFirstExpansion`, `V3RunZergBuild` | 커스텀 AI |

**규칙:** 자기 행 범위 밖은 읽기만 한다. 상대 범위를 고쳐야 하면 상대 담당자에게 넘긴다.
파일을 분할하고 싶어도 지금은 하지 않는다 — 오버레이 `.galaxy` 개수는 10개로 고정이고
(`overlay-manifest.json` + `v3_ai_layout.cjs`가 강제), 늘리려면 mod 빌더와 검증기를 같이
고쳐야 한다.

**`V3SetZergMainMacroHatcheries(player, macroTotal)`는 양쪽이 호출한다:**

| 호출부 | 인자 | 소유 |
| --- | --- | --- |
| `Zerg.galaxy:1062` | `(player, 2)` | 야생 저그 |
| `ZergLingBaneUltra.galaxy:198/202/206` | `(player, 1/2/4)` | 커스텀 AI |
| `ZergRoachHydraUltra.galaxy:342` | `(player, macroHatcheryTarget)` | 커스텀 AI |

시그니처나 내부 동작을 바꾸면 반대편이 **조용히** 망가진다. 이 함수는 **동결**이다.
동작을 바꿔야 하면 자기 쪽에서 쓸 새 함수를 만들고, 상대는 기존 것을 계속 쓴다.

> **해결됨 (§109, 사용자 결정):** 검증기가 `(player, 4)`를 요구하고 코드가 `(player, 2)`인
> 불일치가 `V3_STRUCTURE=FAIL`의 유일한 원인이었다. **코드의 `2`가 정답이고 검증기를
> 내렸다.** 근거: P15는 120초에 이미 `total_supply=428`로 400 천장에 걸려 병력 생산이
> 멈추므로, 알파 해처리를 3개→5개로 늘려도 늘어나는 것은 일꾼·오버로드뿐 병력이 아니다.
> 지금은 `V3_STRUCTURE=PASS`다.

### 2. `v3/ai/overlay/.../V3/ExpansionGas.galaxy` — 공유 헬퍼

세 종족 디스패처가 모두 첫 번째로 include 한다. 헬퍼 11개의 실제 소유는 이렇다:

| 헬퍼 | 호출자 | 소유 |
| --- | --- | --- |
| `V3SetWaveTargets` | `Zerg.galaxy:1116-1120`만 | **야생 저그 전용** |
| `V3WaveSupplyForPhase` | **없음 (죽은 코드)** | — |
| `V3MiningWorkerCapacity` | 양쪽 | **공유 — 동결** |
| `V3SetExpansionGasPolicy` | 양쪽 (P15 1103행 / 커스텀 1254행) | **공유 — 동결** |
| `V3SetGasWorkerDistribution` | 양쪽 (P15 1106행 / 커스텀 1219·1257행) | **공유 — 동결** |
| `V3WorkerTarget` | 커스텀 6빌드 전부 | 커스텀 AI |
| `V3EnsureMiningExpansion` | 커스텀 6빌드 + Protoss/Terran 루트 | 커스텀 AI |
| `V3BuildProactiveSupply` | Protoss·Terran 루트 | 커스텀 AI |
| `V3SetMiningWorkerStock` | Terran·저그 2빌드 | 커스텀 AI |
| `V3RejoinStragglersOfType` | `ExpansionGas` 내부 | 커스텀 AI |
| `V3ZergRejoinMorphStragglers` | 커스텀 저그 | 커스텀 AI |

**함정:** `V3SetWaveTargets`는 커스텀 AI 쪽에서 보면 호출자가 없어 보인다. 지우면 P15
컴파일이 깨진다. **`ExpansionGas.galaxy`에서 함수를 삭제하기 전에 반드시 `V3/` 전체를
grep 한다.** `V3WaveSupplyForPhase`는 실제로 죽은 코드지만, 지우는 것도 야생 저그 담당의
결정이다.

### 2-b. 301 → 302 역방향 의존 (2026-07-26 발견)

`ZergLingBaneUltra.galaxy`(302)가 `ZergRoachHydraUltra.galaxy`(301)의 함수를 호출한다.

| 함수 | 정의 | 호출 |
| --- | --- | --- |
| `V3EnsureUltraliskCavernDrone` | 301 파일 | 302:515(Mid), 302:550(Late) |

`Zerg.galaxy`가 301을 먼저 include 하므로 컴파일은 되지만, **301 담당이 이 함수의
시그니처나 동작을 바꾸면 302의 울트라리스크 굴 건설이 조용히 깨진다.** 두 빌드가
같은 종족 파일 묶음 안에 있어서 생긴 것이고, 파일 이름만 보면 드러나지 않는다.

**규칙:** `V3EnsureUltraliskCavernDrone`을 고치기 전에 302 담당에게 알린다.
301 전용 동작이 필요하면 새 함수를 만들고 기존 것은 그대로 둔다.

같은 이유로 **301 파일에 함수를 추가·삭제할 때 302에서 grep**한다. 반대 방향
(302 → 301)도 마찬가지다.

### 3. `v3/ai/overlay-manifest.json` — 가장 위험

오버레이 10개 전부의 bytes와 SHA-256이 여기 있다. **누가 `.galaxy`를 한 글자만 고쳐도
이 파일이 바뀐다.**

**규칙:**
- Codex에게 매니페스트를 절대 맡기지 않는다. **헤드 에이전트가 마지막에 한 번 재계산한다.**
- 두 담당자가 동시에 galaxy를 편집하는 중에는 아무도 매니페스트를 갱신하지 않는다.
  모든 편집이 끝난 뒤 한 번에 재계산한다.
- 매니페스트가 어긋나면 mod 빌드가 실패한다(그건 다행이다). 더 나쁜 경우는 잘못 머지된
  해시가 통과해서 **전 슬롯이 스폰 실패**하는 것이다 — §108에서 두 번 겪었다.

### 4. `v3/verification/verify_v3_structure.py` — 한 파일, 두 마커 집합

| 행 | 검사 대상 | 소유 |
| --- | --- | --- |
| ~105, 118~119 | 커스텀 AI 빌드 마커 | 커스텀 AI |
| 95~97, 122~159 | P15 마커 18종 + 워커/army 게이트 순서 | 야생 저그 |

**검증기를 통과시키려고 검증기를 고치는 것은 양쪽 모두 금지다.** 마커를 바꿔야 하는
정당한 이유가 있으면 사용자에게 보고한다.

### 5. V1 빌더의 P15 승격 — 슬롯 예산 공유

야생 저그를 켜면 **세 가지가 같이** 일어난다. 하나라도 빠지면 슬롯 수가 안 맞아 게임이
아예 안 뜬다:

1. `tools/build/mapinfo.cjs` — MapInfo 플레이어 15의 `control`을 1(Computer)로
2. `tools/build_custom_runtime_map.cjs` → `patchWildZergStart` — 여분 `StartLoc`을 알파 둥지로
3. `player_setups`에 P15 Computer 항목 추가

**이 경로는 `melee_only`와 무관하게 돌아서 V3도 그대로 쓴다.** 커스텀 AI 담당자가
슬롯 수를 바꾸는 작업(빌드 추가·제거, 플레이어 수 변경)을 하면 이 세 곳을 건드리게 되고,
그건 야생 저그 담당의 영역이다. **슬롯 구성을 바꾸기 전에 상의한다.**

반대로 V3에서는 `tools/galaxy/hostile_wild_ai.galaxy` / `hostile_wild_idle.galaxy`가
**쓰이지 않는다.** `melee_only=true`이면 `sc2team_InitializeV3WildBootstrap` 단발 부트스트랩으로
대체된다(`tools/build/runtime.cjs:85-103`). 이 두 파일은 V1 경로 전용이다.

## 절차

### 상대 영역을 건드려야 할 때

1. 고치지 말고 **보고**한다 — 무엇이, 왜 필요한지.
2. 상대 담당자가 자기 영역에서 고친다.
3. 양쪽 편집이 끝난 뒤 헤드 에이전트가 매니페스트를 한 번 재계산한다.
4. 스모크(6분) → 필요하면 전체 프로브.

### 측정 결과를 해석할 때

**야생 저그가 켜져 있으면 커스텀 AI 수치가 내려간다.** 근처 슬롯이 실제로 얻어맞기
때문이다. 커스텀 AI 담당자가 이걸 "생산 회귀"로 오진할 수 있다 — §104의 HomeDefense
사건이 정확히 그 형태였다(야생 저그 근처 슬롯의 하이브·울트라가 막힘).

- 커스텀 AI 생산을 측정할 때는 **야생 저그를 끄고** 돌린다.
- 회귀가 의심되면 야생 저그 on/off 두 번 돌려서 비교한다.
- 야생 저그 프로브(`probe_v3_wild_zerg.py`)는 기본이 P1 대 P15 단독이라 반대 방향
  간섭은 없다.

### 프로브 충돌 — A2A 통보 필수

SC2 인스턴스는 하나다. **SC2를 쓰는 모든 작업은 시작 전·종료 후에 A2A로 활성 세션 전부에
통보한다.** 18분 프로브뿐 아니라 6분 스모크와 육안 확인용 비주얼 프로브도 포함이다.
명령 형식과 주의점은 [`harness.md`](harness.md)의 "엔진 프로브는 배타 실행" 절에 있다.

실제로 겪은 것들:
- 한 세션이 점유 통보를 누락해 상대가 "SC2 비어 있음"으로 오판했다.
- 상대 지정에 짧은 id를 쓰면 `unknown session`으로 조용히 거부된다. `startcraft2/<id>` 형식을 쓴다.
- 담당 역할을 넘겨짚지 마라. 파일을 만진 세션이 그 파일의 담당이라는 보장이 없다 —
  야생 저그 담당을 302 담당으로 오인해 엉뚱한 곳에 조율 요청을 보낸 적이 있다.
  먼저 `peers`로 확인하고, 모르면 활성 세션 전부에 물어본다.
