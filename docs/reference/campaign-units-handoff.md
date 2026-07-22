# 캠페인 유닛 이식 — 설계 · 조사 · 구현 핸드오프

작성: 2026-07-16. 상태: **확정 로스터 및 프로토스 전역 프리셋 완료(v1.8.0)**.

이 문서는 커스텀 AI 맵(`Custom AI v1.8.0`)의 SC2 캠페인/협동전 유닛 이식 결정과 구현 기록이다. 현재 수정 절차는 `docs/modify/campaign-units.md`가 우선한다.

> 후속 상태: v1.9.0에서 대표 프로토스 전용 무기·액티브·패시브가 추가됐다. 아래의 “호환 외형” 결론은 v1.8.0 당시 기록이며, 현재 동작은 `docs/modify/campaign-units.md`를 따른다.

관련 참고 문서:
- `docs/reference/campaign-units-catalog.pdf` — 전 종족 캠페인/협동전 유닛 카탈로그 + 프로토스 파벌 분기 매트릭스 + 특수 기능표
- `docs/reference/terran-unit-additions.md` — 테란 후보 유닛 상세
- `docs/reference/zerg-unit-additions.md` — 저그 후보 유닛 상세

## 2026-07-16 v1.8.0 구현 완료 업데이트 (이하의 초기 조사보다 우선)

데이터 소싱 게이트는 해결됐다. 공개 추출본 `SC2Mapster/SC2GameData`에서 필요한 레코드와 자산 경로를 조사하고, 빌더가 `tools/campaign_data/`의 작은 카탈로그 조각을 런타임 맵에 병합하는 **Method B(외과적 복사)** 를 사용한다. 전체 `Swarm Story` 종속성은 실제 로컬 API 맵에서 캠페인 카탈로그를 제공하지 않았고 불필요한 회귀 위험도 있어 사용하지 않는다.

토라스크는 별도 신규 유닛이 아니라 문서의 원래 권장안대로 표준 `Ultralisk` ID 109를 유지하는 전역 REPLACE로 완성됐다.

- `tools/campaign_data/torrasque/`: 울트라 부분 오버라이드, 토라스크 모델, 치명타 방지 행동, 부활 고치 배우 데이터.
- `tools/build_custom_runtime_map.cjs`: 카탈로그 병합과 10초 고치/부활, 부활 후 60초 재사용 대기 Galaxy 런타임.
- `app/play_custom_ai.py`: 실제 실행 맵 생성 시 캠페인 유닛 기능을 기본 활성화.
- `verification/verify_torrasque_pilot.py`: 실제 피해 후 고치→부활 및 사용 인구 6 유지 검증.
- `verification/verify_torrasque_ai_production.py`: 스톡 저그 AI가 ID 109를 정상 생산하는 장기 가속 검증.

확정 픽 전체가 구현됐다.

- 저그: 토라스크 REPLACE, 변종 ADD, 랩터 전역 업그레이드.
- 테란: 골리앗·프레데터·의무병 ADD.
- 프로토스: GUI에서 `기본/아이어/네라짐/정화자/탈다림` 중 하나를 고르는 전역 호환 외형 프리셋.
- ADD 유닛은 생산 능력과 버튼도 유효하지만 Blizzard 멜리 AI가 신규 ID를 `AISetStock`만으로 생산하지 않았다. 따라서 기술·자원·보급을 검사하고 비용을 차감하며 생산 건물별 빌드 시간 쿨다운을 적용하는 Galaxy 전략 구매를 사용한다.
- `app/play_custom_ai.py`는 `ResponseData`로 신규 전투 유닛 ID를 동적 해석한다. 의무병은 전투력에서 제외한다.

검증 결과: 카탈로그/생성 PASS, 약 800 게임 초 안에 추가 유닛 전종 및 랩터 연구 관측 PASS, 프로토스 네 프리셋 정상 시작 PASS, offline 11 checks 및 short-engine 2 checks PASS. 토라스크 빌드는 군락 뒤 울트라리스크 동굴을 정상 `AIBuild`로 보강해 내장 AI의 비결정적 테크 생략도 제거했다. 현재 수정 절차의 정본은 `docs/modify/campaign-units.md`다.

---

## 0. 목표 (한 줄)

표준 3종족에 캠페인/협동전 유닛을 **전역(global)** 으로 추가·교체한다. 프로토스는 "부족" 프리셋을, 테란·저그는 개별 유닛 몇 개를 넣는다. 스톡 Blizzard 멜리 AI가 실제로 그 유닛을 쓰게 만드는 것이 목표다.

---

## 1. 확정된 설계 결정

### 1.1 종족별 방식

| 종족 | 방식 | 비고 |
|---|---|---|
| **프로토스** | 부족 프리셋 **전역** 적용 (게임당 부족 1개, 모든 프로토스 공유) | 원래 per-player 부족을 원했으나, 스톡 AI 제약(아래)으로 **전역**으로 확정 |
| **테란** | 개별 유닛 몇 개 **전역** 추가/교체 | 부족 개념 아님 |
| **저그** | 개별 유닛 몇 개 **전역** 추가/교체 | 부족 개념 아님 |

### 1.2 왜 프로토스도 전역인가 (핵심 제약)

- 게임/협동전이 "플레이어마다 다른 유닛"을 구현하는 방식은 **종족(race)** 이다. 협동전 지휘관 = 사실상 커스텀 종족이고, **각 지휘관마다 Blizzard가 전용 AI를 따로 작성**했다.
- 이 프로젝트는 **스톡 멜리 AI**(표준 3종족에만 존재)에 의존한다. 커스텀 부족을 종족으로 만들면 **그걸 플레이할 스톡 AI가 없다.**
- per-player 변형은 트리거/업그레이드로 가능은 하나 AI 병력 집계 꼬임 등 위험이 크고 미검증이다.
- → **전역**이면 표준 종족을 유지한 채 데이터만 바꾸므로 스톡 AI가 그대로 작동한다. 대신 **한 게임에 프로토스 부족은 하나**(아이어 vs 네라짐 혼합 불가). 사용자 수용함.

### 1.3 확정 픽 리스트

| 종족 | 픽 | 방식 | 비고 |
|---|---|---|---|
| **저그** | 토라스크 (Torrasque) | **REPLACE** 울트라리스크 | 부활만 다름. 파일럿 대상 |
| | 변종 (Aberration) | **ADD** | 로치↔울트라 사이 중장 근접. 배선 필요 |
| | 랩터 저글링 (Raptor) | **업그레이드** (번식지 연구) | 저글링은 맹독충 변태 원천 → 교체 금지, 업그레이드로 |
| **테란** | 골리앗 (Goliath) | **ADD** | 지상 대공 보행. 공장+무기고 |
| | 의무병 (Medic) | **ADD** (지원) | 바이오 빌드 전용, 힐 오토캐스트. 전투력 미포함 |
| | 프레데터 (Predator) | **ADD** | 기계 근접, 대(對)경장/스웜. 메카닉 부대 근접 방어용. AI는 스크린 배치는 안 하고 어택무브만 |
| **프로토스** | 부족 프리셋 | **REPLACE 묶음** | 매트릭스는 PDF §프로토스 참조. `—`=기본 유닛 |

### 1.4 핵심 원칙 (모든 종족 공통)

- **REPLACE > ADD**: 교체는 AI가 원래 유닛인 줄 알고 알아서 뽑음(배선 불필요, 최저위험). 추가는 AI가 스스로 안 뽑아서 생산 테이블 등록 필요.
- **`—`(전용 변형 없음) = 기본 멀티플레이 유닛 사용.** (프로토스 파벌 매트릭스의 빈 칸)
- **능력 위주 캐스터**(에너자이저·하복·과학선 등)는 AI가 능력 미사용 → **기본 유닛으로 폴백** 또는 사람 전용.
- **변태 원천 유닛(저글링·로치·히드라) 교체 금지** → 추가나 업그레이드로.
- **공중 전투 유닛은 프로젝트가 AI에게 차단**(v1.2+). 지상 전투 중심.

---

## 2. 조사 결과 — 구현은 2부 구조

> 초기 조사 결론(현재는 대체됨): 아래에는 에디터/CASC 관문으로 기록되어 있으나, 위 구현 업데이트처럼 공개 추출 데이터 + StormLib 카탈로그 병합으로 레포 내부에서 재현 가능해졌다.

### 2.1 빌더 `tools/build_custom_runtime_map.cjs`

> **위치·줄번호 주의(§84 이후)**: 빌더는 `tools/build/*.cjs`로 분리됐고 아래
> 줄번호는 단일 파일이던 v1.8.0 시점의 것이다. 현재 위치 — `main()`/`Archive`는
> 진입점, `patchSupplyCeiling`·카탈로그 병합은 `build/archive.cjs`, 생산·조합
> 테이블은 `build/tables.cjs`, `verify()`는 `build/verify.cjs`. 또한 `FoodCeiling`은
> v1.16.0에서 600 → **800**으로 올랐다.

- **MPQ 편집**: `@jamiephan/stormlib`의 `Archive` (line 6). `main()` lines 1140-1171 — 소스 `.SC2Map` 임시 복사 → `Archive.open` → 변형 → `compact()` → `verify()` → `close()` → 출력 복사. API: `readFile`/`readFileAsString`, `addBuffer`/`addString`, `hasFile`, `removeFile`, `compact`. 엔트리 경로는 역슬래시(`"Base.SC2Data\\GameData\\UnitData.xml"`).
- **유닛/종족 데이터 편집**: `patchSupplyCeiling(archive)` lines 956-978 (호출 1164). `RaceData.xml` 셰도 제거 + `UnitData.xml`에 부분 `<CRace><FoodCeiling value="600"/></CRace>`만 주입. **일꾼 Food=0는 여기 없음** — 소스 맵 자체 데이터에 있음. 봇 관측용 일꾼 인구 복원은 `sc2team/worker_supply_proxy.py`.
- **생산/조합 테이블 (전부 모듈 상수)**:

  | 테이블 | 라인 |
  |---|---|
  | `COMBAT_AIR_BY_RACE` | 11-15 |
  | `SUPPORT_AIR_BY_RACE` | 17-21 |
  | `SUPPORT_AIR_CAP` | 23-30 |
  | `SUPPORT_AIR_CAP_OVERRIDES_BY_BUILD` | 32-36 |
  | `GROUND_COMBAT_BY_RACE` | 44-57 (Ultralisk = line 55) |
  | `PREFERRED_STOCK_BY_BUILD` | 63-80 |
  | `PREFERRED_INFRA_BY_BUILD` | 82-101 |
  | `SCALING_PRODUCTION_BY_BUILD` | 105-134 |
  | `SCALING_PRODUCTION_PREREQUISITE` | 136-141 |
  | `RANDOM_SCALING_PRODUCTION_BY_RACE` | 143-150 |
  | `FIXED_STRUCTURE_CAPS_BY_BUILD` | 154-171 |
  | `EXPANSION_GATE_INFRA_BY_BUILD` | 173-190 |
  | `EXPANSION_TOWN_HALL_BY_RACE` | 192-196 |
  | `ALLOWED_GROUND_BY_BUILD` | 198-215 (Ultralisk in `ultra_ling_bane` = line 213) |

  이 테이블들은 `makeProductionRules()` (334-618)이 Galaxy `TechTreeSetProduceCap`/`AISetStock`/`AIBuild`로 방출하고, `verify()` (980-1117)에서 재검증됨. 테이블은 **문자열 유닛 타입명** 사용.
- **맵 종속성(dependency) 처리 없음**: 빌더는 `DocInfo/Name` 등 **표시 문자열만** 편집(`patchLocalization` 936-954). 종속성/컴포넌트 리스트 처리 코드는 전무. StormLib으로 아무 엔트리나 쓸 수는 있으니 기술적으로 도달은 가능하나, 종속성 리스트를 파싱/재작성하는 코드는 **새로 짜야 함**. 문서상 의도된 방식은 SC2 에디터.

### 2.2 Python 테이블

- `sc2team/custom_config.py`: `RACES` 13-18, `GROUND_BUILDS` 23-51, `DEFAULT_BUILD_BY_RACE` 53-58, `validate()` 85-116.
- `sc2team/custom_runtime.py`: `RACE_VALUES` 14-19, `AI_BUILD_BY_STRATEGY` 21-38 (빌드→Blizzard `Rush/Timing/Power/Macro`).
- `sc2team/strategy_controller.py`: `GROUND_COMBAT_SUPPLY` 27-38 (**숫자 타입 ID** 키, Ultralisk=109 line 34), `PRODUCER_TYPES_BY_BUILD` 41-58 (**숫자 생산건물 ID** 키, Factory=27).
- **정본 동기화 목록**: `docs/modify/runtime-map.md` lines 90-97.
- 요약: 빌더 테이블은 **문자열명**, `strategy_controller.py`는 **숫자 ID**를 쓴다. 새 유닛 ADD 시 양쪽 다 손봐야 함.

### 2.3 세 연산의 구체 편집점

**(a) REPLACE 울트라→토라스크 (파일럿)**
- **맵 데이터(수동, 에디터/CASC)**: 소스 맵의 `Ultralisk` `CUnit`/train 엔트리를 토라스크 몸체로. **캠페인 데이터 필요 → 에디터/CASC 단계. 이게 유일한 관문.**
- **레포 코드**: "Ultralisk" 문자열에 올라타므로 **테이블 변경 사실상 0.** AI가 이미 울트라를 뽑음(`GROUND_COMBAT_BY_RACE.Zerg` 55, `ALLOWED_GROUND_BY_BUILD.ultra_ling_bane` 213, `PREFERRED_STOCK_BY_BUILD` 78).
- **권장 구현 방식 = 리스탯**: 울트라 유닛 ID(109)를 유지한 채 모델·스탯·부활만 부여 → `strategy_controller.py`의 숫자 ID 테이블도 안 건드림. (진짜 별도 Torrasque 유닛으로 바꾸면 문자열·숫자 테이블 전부 새 ID로 갱신해야 함.)
- **검증 포인트**: 부활 ↔ 600 인구/유닛 집계 상호작용만 엔진에서 확인.

**(b) ADD 새 지상 유닛 (예: 골리앗)**
- 빌더: `GROUND_COMBAT_BY_RACE.Terran`(46-48)에 `"Goliath"` 추가; 대상 빌드의 `ALLOWED_GROUND_BY_BUILD`(예 `thor_tank`/`mech_macro` 202-203); `PREFERRED_STOCK_BY_BUILD`(66-68); 필요 시 `PREFERRED_INFRA_BY_BUILD`/`SCALING_PRODUCTION_BY_BUILD`(생산건물 공장+무기고); `verify()` 기대값(1024-1088)도 확장.
- `strategy_controller.py`: `GROUND_COMBAT_SUPPLY`(27-38)에 골리앗 **숫자 ID**→보급 가중치; 생산건물 ID(Factory=27)가 `PRODUCER_TYPES_BY_BUILD`(41-58)에 있는지 확인.
- `custom_config.py`/`custom_runtime.py`: **새 빌드**를 만들 때만. 기존 빌드에 유닛 추가면 불필요.
- **맵 데이터(수동)**: 골리앗 `CUnit`/train 엔트리가 맵에 존재해야 함 → 에디터/CASC 단계.

**(c) 데이터 소싱이 에디터/CASC를 요구하는가 → 그렇다.**
- 레포에 비-멜리 유닛 데이터를 가져오는 메커니즘이 **전무.** 후보 유닛(토라스크·골리앗·변종 등) 전부 멜리 카탈로그에 없음.
- 두 경로 모두 **소스 맵 대상 에디터/CASC 작업**:
  - (A) 캠페인 데이터 **종속성 추가**
  - (B) 필요한 `CUnit/CWeapon/CActor/CAbil/CButton` 레코드만 **외과적 복사**(Method B)
- 테란 조사는 (B)를 권고(종속성 통째는 멜리 카탈로그 셰도 → "시작 유닛 누락/중복" 회귀 위험). 단 (B)는 CASC에서 레코드를 **읽을** 도구가 필요(현재 미설치).

### 2.4 절대 불변 조건 (되돌리면 안 됨)

- 맵 레벨 `RaceData.xml` 추가 금지.
- 전체 `CRace` 복사 금지(시작 배열 병합→본진/일꾼 중복).
- `UnitData.xml`은 부분 `FoodCeiling=600`만.
- 런타임 `c_playerPropSuppliesLimit` 변경 금지.
- 일꾼 Food=0, 고정 시작점, 팀 속성, 50000 자원 보존.
- `runtime/maps/` 생성물 직접 편집 금지 — 빌더나 베이스 맵 수정 후 재생성.

---

## 3. 데이터 소싱 게이트 (해결됨 — 역사적 조사 기록)

캠페인 유닛 데이터를 소스 맵에 넣는 단계가 유일한 미해결 관문. 현재 환경:
- SC2 데이터는 `SC2Data`의 **CASC** 저장소 안. **CASC 추출기 미설치.** ImageMagick 없음, Pillow 있음(이미지엔 무관).
- SC2 에디터(`StarCraft II Editor.exe`)는 설치돼 있으나 **GUI라 헤드리스 자동화 불가.**

두 경로:
1. **CASC 스파이크**: CASC 추출기를 세팅해 토라스크 레코드를 뽑아 빌더의 StormLib으로 `UnitData.xml`에 직접 주입. 성공 시 에디터 불필요·자율 진행. 실패 시 에디터로 폴백. (불확실, 프로젝트 가장 취약 영역 건드림)
2. **에디터 경로**: 사람이 SC2 에디터에서 캠페인 데이터 1회 추가(정확 절차 안내 가능). 확실·의도된 방식. GUI 작업 1회는 사람 몫.

> 어느 경로든 **엔진 검증은 SC2를 띄워 사람이 확인**해야 한다(고정 포트 14111/14112, SC2·에디터 종료 필요).

---

## 4. 파일럿 — 토라스크 REPLACE (v1.7.0 완료)

가장 저위험(REPLACE, 코드 거의 0)으로 "데이터 소싱 → 데이터 편집 → 검증" 파이프라인을 먼저 뚫는다.

1. **데이터**: 소스 맵에서 울트라리스크(ID 유지)에 토라스크 모델 + 부활(reincarnation) 능력 부여. (§3의 경로 1 또는 2)
2. **레포 코드**: 없음 또는 극소(리스탯이면 없음).
3. **오프라인 검증**: 빌더 구조 검증 + 단위 테스트(21+2).
4. **엔진 검증(사람)**: 정상 시작 유닛 / 600 인구 / 고정 시작 재통과 + **토라스크 부활 시 인구·집계 정상** 확인.
5. 통과 시 → 나머지 ADD(골리앗·프레데터·변종·의무병) 및 업그레이드(랩터), 그다음 프로토스 부족 프리셋으로 확장.

---

## 5. 구현 순서 (완료 기록)

1. 데이터 소싱 경로 확정(Method B) — 완료.
2. 파일럿: 토라스크 REPLACE — v1.7.0 완료.
3. 저그 ADD: 변종 + 랩터 업그레이드 — v1.8.0 완료.
4. 테란 ADD: 골리앗 → 프레데터 → 의무병 — v1.8.0 완료.
5. 프로토스 전역 프리셋 — v1.8.0 호환 외형 범위로 완료.
6. 각 단계마다 오프라인 + 엔진 검증, 결과를 `HANDOFF.md`/`docs/latest_status.md`에 기록.
7. 릴리스 시 `APP_VERSION`(Python)·CJS 맵 이름·문서·출력 파일명 동시 이동.

---

## 6. 검증 요구 (모든 게임플레이 변경)

- 오프라인 티어: `docs/verify/verification-guide.md`. 단위 테스트 + 빌더 구조 검증.
- 엔진 검증: 유닛/종족 데이터·생산 변경이므로 필수. 특히 **정상 시작 유닛 / 관측 최대 인구 600 / 고정 시작점** 세 가지를 매 추가마다 증분 확인. 토라스크는 추가로 **부활-인구 상호작용**.
- `runtime/maps/`의 과거 프로브 맵 존재만으로 재검증됐다고 주장 금지.

---

## 7. 남은 결정 / 다음 액션

- 데이터 소싱과 로스터는 완료됐으며 재논의 불필요하다.
- 다음은 실제 4v4/7v7 플레이를 통한 목표 수량·비용 밸런스 조정이다.
- 프로토스에 캠페인 고유 능력까지 넣을지는 별도 결정이다. 현재는 스톡 AI 안정성을 위해 표준 능력/무기/생산을 보존하고 대표 유닛 외형만 바꾼다.
