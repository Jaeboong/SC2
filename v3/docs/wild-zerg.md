# 야생 저그 (P15, build 315) 규율

맵 플레이어 15. 로비 밖의 제3세력이며, 사용자가 런처 체크박스 `wild_zerg`로 켜고 끈다
(기본 on). 담당 경계는 [`../../docs/ownership.md`](../../docs/ownership.md).

현재 구현은 **V3 임베디드**다. 반복 정책 전부가
`v3/ai/overlay/Base.SC2Data/TriggerLibs/V3/Zerg.galaxy` **1~1141행**에 있다.
V1 시절의 맵 사이드 컨트롤러(`tools/galaxy/hostile_wild_ai.galaxy`)는 **더 이상 쓰이지
않는다** — 그 규율은 [`../../docs/history/v1-ai-rules.md`](../../docs/history/v1-ai-rules.md)에
보존돼 있다.

## 구조: 승격은 3종 세트다

**P15는 진짜 로비 Computer 슬롯이어야 한다. Neutral Hostile이면 안 된다.**

이건 취향이 아니라 엔진 제약이다. §90에서 프로브 12번으로 측정했다. Neutral Hostile일 때
P15는 **어떤 경로로도 전투 유닛을 생산할 수 없다.** 같은 라바에 같은 순간:

| 유닛 | 유효 |
| --- | --- |
| Drone, Overlord | 59 |
| Zergling, Roach, Hydralisk, Baneling, Mutalisk | **0** |
| Marine(테란), Zealot(프로토스), 캠페인 유닛 | **0** |

광물 47,000, 가스 50,000, 보급 여유 250+, 라바 94기, Galaxy가 완성된 스포닝 풀 8개를 세고
있는 상태에서다. Drone과 Overlord는 테크 구조물 없이 저그가 만들 수 있는 정확히 그 둘이다.
**엔진이 P15를 영구히 "구조물 없음"으로 취급한다.**

버튼 `Requirements` 속성 문제가 아니다 — 속성을 지운 커스텀 `LarvaTrain` 항목도 똑같이
거부됐고, Hatchery 쪽 `CAbilTrain`도 마찬가지였다. `TechTreeUnitAllow`/`TechTreeAbilityAllow`는
둘 다 "허용됨"이라고 보고하고, `TechTreeUnitCount`는 스포닝 풀을 보며,
`TechTreeRestrictionsEnable`은 어느 방향으로도 아무것도 바꾸지 않는다.

해결은 구조적이며 **세 조각 전부 필요하다** (`melee_only`와 무관 — V1·V3 공용 경로):

1. `tools/build/mapinfo.cjs` `patchPlayers` — MapInfo 플레이어 15 `control` = 1
2. `tools/build_custom_runtime_map.cjs` → `patchWildZergStart` — 여분 `StartLoc`을
   알파 둥지(1시 방향 Lair)로 이동
3. `player_setups`에 P15 Computer 항목 추가

**시작점 없이 승격만 하면** 멜리 AI가 8분 동안 스포닝 풀을 못 짓는다(실측).
`verify()`가 승격·시작점·알파 둥지 위치 중 하나라도 빠지면 빌드를 실패시킨다.

### 끄는 것은 트리거를 비우는 게 아니라 승격을 되돌리는 것이다

승격된 P15에는 **뇌가 둘**이다: 우리 컨트롤러와 블리자드 멜리 AI. 멜리 AI는 이미 자기
본진을 고르고 Hatchery 랠리를 설정한다(§90.7/§90.13 실측). 우리 것만 제거하면 두 번째가
계속 생산한다.

`wild_zerg=false`는 **셋 다** 해야 한다: `patchWildZergStart` 건너뛰기, MapInfo `control`을
원래 neutral-hostile 값으로 두기, `player_setups`에서 P15 항목 빼기. 그래야 슬롯 수가 맞고,
덤으로 위의 §90 측정이 2차 방어선이 된다.

`verify()`가 양방향으로 검사한다.

## 단발 부트스트랩 경계 (사용자 승인 예외, §106)

`wild_zerg=true`일 때만, 맵 Galaxy가 `MeleeInitAI()` 직후 P15를 **한 번** 부팅한다.
실체는 `tools/build/runtime.cjs:85-103`의 `sc2team_InitializeV3WildBootstrap`이다.

허용되는 것은 이것뿐이다:

```
AIMeleeStart(15)
AIInitCampaignTowns(15) / AIInitCampaignHarvest(15) / AIHarvestRate(15, 1)
AISetUserInt(15, 142, 315)     빌드 마커
AISetUserInt(15, 139, 540)     공격 지연 seed (9분)
AISetSpecificState(15, 1..3, 1)
PlayerModifyPropertyInt 광물/가스 각 50,000  ← 1회
```

**맵 계층에 P15용 주기 트리거를 넣으면 안 된다.** 생산·경제·주둔·전투·해제 컨트롤러는
전부 임베디드 `V3/Zerg.galaxy` 소관이다. `verify()`는 V3 melee-only 맵에서 커스텀 주기
트리거를 거부한다.

시험용 프로브 맵은 파괴적 측정 이벤트를 주입해도 되지만
(`v3/tools/patch_v3_wild_resilience_probe.cjs`), 그 스크립트는 **런처가 만드는 맵과 V3 mod에
절대 들어가면 안 된다.**

P15는 일반 V3 플레이어 목록과 분리돼 있어 7v7 슬롯 구성이 필요 없다. `wild_zerg=true`이면
일반 V3 빌드 선택이 0개인 plan도 유효하다.

## build 315 동작

선배치 해처리/레어를 **각각 독립 AI town으로 등록**한다. 각 town은 자기 생산 최소치와
Spine/Spore, `GuardHome` 주둔 wave를 가져 로컬 기지 단위로 방어한다.

| 항목 | 알파 town (1시) | 로컬 town |
| --- | --- | --- |
| Spine / Spore | 6 / 4 | 2 / 2 |
| 주둔 | 32기 | 10기 |
| 매크로 해처리 | **3 (코드) / 5 (검증기 기대) — 아래 미해결 참조** | — |
| 테크 | Hive / Ultralisk 계열 | — |

> **미해결 — 사용자 결정 필요.** `verify_v3_structure.py:135`는
> `V3SetZergMainMacroHatcheries(player, 4)`를 요구하는데 `Zerg.galaxy:1074`는 `(player, 2)`다.
> 이 함수는 본진 해처리를 `1 + macroTotal`개로 맞추므로 코드는 3개, 기대치는 5개다.
> `V3_STRUCTURE=FAIL`의 유일한 원인이고 §106 작업의 미커밋 불일치이며,
> V3 런처가 `wild_zerg: true`이므로 **알파 둥지 라바 생산에 실제 영향이 있다.**

- **일꾼:** 자원 town당 8기. P15 은행은 트리거로 채워지므로 Drone은 수입용이 아니다.
- **보급:** Overlord는 `SuppliesMade >= 448`에서 멈춘다 (400 천장 + 48 여유).
- **병력:** 플레이어 전체 `SuppliesUsed < 400`에서만 생산한다.

### 400 보급 천장 (§92, 사용자 지시)

> "저그가 진짜 물량을 말도안되게 뽑던데 … 병력 상한을 둔다. 인구 400을 상한으로 두겠다"

§89의 "상한 전부 제거" 지시를 사용자가 뒤집은 것이다. 충돌이 아니다 — §89의 문제는 P15가
**아무것도 생산하지 못하는** 상태였고, §90이 그걸 고친 뒤에 나온 판단이다.

성질 세 가지를 유지해야 한다:

1. **병력만 막는다.** 일꾼·Overlord·건설은 계속 돈다. 천장에 닿은 뒤 병력을 잃은 P15에
   경제가 없으면 재건이 불가능하다. 이건 생산 동결이 아니라 천장이다.
2. **`SuppliesUsed`로 잰다.** `SuppliesLimit`(800, 무의미)도 `SuppliesMade`(Overlord 수에
   따라 요동)도 아니다.
3. **플레이어 단위로 유지한다.** 둥지별 `armyTarget`과 조합 상한은 여전히 금지다 —
   그것들은 둥지별 생산 분배를 왜곡했고, 이 천장은 그러지 않는다.

### 9분 휴전

540초 전에는 `Wait` 상태를 계속 주입해 **선제 공격만** 금지한다. town 방어는 유지된다.
540초에 V3 내부에서 한 번 `Attack` 상태로 넘긴 뒤, 그 다음부터의 공격 전환은 블리자드
웨이브 시스템이 맡는다.

휴전은 **선제 공격만** 막는다. 생산·건설·확장·방어 대응은 전부 계속된다.

## 금지 사항

- **`UnitCreate`로 P15 병력을 만들지 않는다** (사용자 지시 §89.14: "직접 생산도 아니고 —
  롤백하라"). 라바를 완성 유닛으로 치환하면 알과 부화 시간을 건너뛴다. 비용을 정직하게
  차감해도 그건 생산이 아니라 치환이다. `verify()`가 `sc2team_HostileWildForceSpawn`
  재등장을 빌드 실패로 만든다.
- **둥지별 `armyTarget`, 조합 상한(`desiredRoaches`/`desiredHydras`), 유닛 해금 타이머를
  다시 넣지 않는다.** `verify()`가 식별자 재등장을 막는다.
- **채취 전용 컨트롤러(`hostile_wild_idle.galaxy`)에 `TechTree*Allow`를 넣지 않는다.**
  그 호출은 neutral-hostile P15의 생산을 *열기* 위해 있었으므로 그 모드가 원하는 것의
  정확한 반대다. (V1 경로 전용 파일이지만 규율은 유지한다.)
- **확장과 공격을 결합하지 않는다.** 개발은 휴전과 분리돼 있다.

## 진단

- **P15 생산 문제를 코드를 읽어서 고치지 않는다.** 이 경로는 에러를 전혀 보고하지 않는다 —
  `UnitOrderIsValid`가 false를 반환하고 주문이 조용히 스킵될 뿐이다. 소스에서 추론해서
  **연속 다섯 번 오진**했다(§89.5–89.12: 은행 고갈, 트리거 연산 한도, 보급 막힘, 라바 경합,
  `Requirements` 속성 — 전부 측정으로 반증됨).
- **엔진이 실제로 무엇을 거부하는지 측정한다.** 같은 라바에 같은 순간 대조군 유닛을 함께
  잰다.
- **마커 유닛 채널은 위치나 방향이 아니라 "서로 다른 유닛 타입의 개수"로 인코딩한다.**
  `UnitCreate`는 배치 불가 지형에서 유닛을 옮기고 비콘 액터는 자기 방향을 강제한다 —
  이것 때문에 앞선 프로브 설계 두 개가 조용히 오염됐다.
- **자원 부족은 원인이 아니다.** 맵이 rich(50000)이고 P15는 은행 top-up까지 받는다.

## 검증

```powershell
# P15 단독 엔진 프로브 (기본: P1 대 P15)
.\.venv\Scripts\python.exe v3\verification\probe_v3_wild_zerg.py

# 알파 복원력 (로컬 둥지 전멸 후 재건) — 시험 전용 맵 패치
.\.venv\Scripts\python.exe v3\verification\probe_v3_wild_zerg.py --destroy-locals
```

기준선 실측(§V3.16): 120초에 15/15 둥지 주둔, Drone 67·Ling 106·Roach 45·Hydra 8·Ultra 6;
539초에 적 기지 압박 0·15/15 주둔; 720초에 둥지 밖 원정 22기. 361초에 로컬을 전부 제거한
복원력 프로브에서 알파가 539초까지 신규 전투 38기, 720초까지 92기를 재생산해 PASS.

`.galaxy`를 고쳤으면 [`../../docs/harness.md`](../../docs/harness.md)의 게이트 5(6분 스모크)를
반드시 통과시킨다. 정적 검증은 컴파일 깨짐을 못 잡는다.
