# V3 상태

갱신: 2026-07-23

V3 지상군 빌드 6개가 해시 고정 upstream+overlay SC2Mod로 구현되어 런처 선택과
연결됐다. Blizzard 원본 설치 파일은 수정하지 않는다.

## 완료

- 종족별 지상군 빌드 2개, 총 6개
- 공통 14 일꾼/400 광물/첫 생산 건물 전 선확장
- 14기·400광물에서 생산 건물보다 첫 확장을 먼저 등록
- 본진 생산 건물 최대 50%, 나머지는 확장 town-local Stock
- 시간 비의존 후속 확장: 이전 town 완성 후 하나씩 진행, 4기지 우선 확보
- 4기지 이후 광물 일꾼 포화 시 최대 6기지까지 동적 확장
- 완성 채광 기지마다 `광물 지점×2 + 완성 가스×3`으로 계산하는 일꾼 목표
- 완성된 각 확장의 raw gas spot별 town-local 가스 건물과 가스당 일꾼 3명 배정
- 의무병 최대 5%, 울트라 후반 단계
- 옵저버 모드와 플레이어별 build ID 142 연결
- 업스트림 TriggerLib 54개와 오버레이 10개 해시 검증
- 빌드 시점 dispatcher root hook과 AI SC2Mod 빌드·설치
- 14기 정지 회귀 검사: 모든 빌드가 6분까지 14기를 넘고 첫 확장 확보
- Python/Node 문법 검사 통과
- SC2 9분 3분 간격 프로브 통과
- P15 야생 저그 420초 gate: AI user int 145 전까지 저그 엔트리 반환
- V2 검증 경로를 이식해 P15 선배치 전투 유닛만 `AISetUnitScriptControlled`로 고정
- `Invalid MainState`를 만들던 state `-1` 지연 방식 제거 및 재등장 방지 검사
- P15 엔진 프로브 통과: 419초 이동 0기·건물 34, 480초 이동 18기·건물 36,
  600초 이동 49기·최대 200.7 거리, 일반 플레이어와 P15 모두 보존

## 엔진 결과

시작 5초의 P1~P6 소유 유닛이 모두 정상이며 `V3_GROUND_COMPILE=PASS`였다. 3분에는
전 플레이어가 첫 확장을 확보했고, 6분 일꾼은 19~33기, 9분 일꾼은 27~56기였다.
9분에는 여섯 빌드 모두 선택 roster의 병력을 생산해 `V3_GROUND_BUILDS=PASS`가
나왔다.

## V3.3 엔진 재검증

- 빌드별 단독 18분 엔진 관측은
  [`verification/v3.3-engine-log.md`](verification/v3.3-engine-log.md)에 고정했다.
- 여섯 빌드 모두 3분 간격으로 플레이어/기지/일꾼/병력 인구/가스/업그레이드/
  생산 건물을 기록했다.
- 3기지 이후에는 이 시험 맵에서 `AIHasNearbyOpenExpansion`이 false가 되어
  6기지 이상을 관측하지 못했다. 이는 6기지 구현 PASS가 아니라 별도 큰 맵
  검증이 남았다는 뜻이다.

## V3.4 확장 포화 판정 재검증

- 관문+로보의 2기지 정체는 수동 spot 산식과 native 경제 포화값의 불일치였다.
  후속 확장 판단을 upstream `AIGetMinPeonCount`로 맞춘 뒤 18분에 3기지까지
  실제 확장됨을 확인했다.
- 여섯 빌드의 최신 9분 단독 결과와 V3.4 장기 샘플은
  [`verification/v3.4-engine-log.md`](verification/v3.4-engine-log.md)에 있다.

## V3.5 저글링·맹독충 생산 회귀

- 18분 관측에서 `UnitNext(360 Zergling)`이 맹독충·울트라 morph를 뒤에
  가둔 것을 확인했다. 맹독충 4기 morph 체크포인트가 충족될 때까지 opening을
  유지한 뒤 진행하도록 고쳤다.
- 최신 9분 독립 run: 3기지, 일꾼 42, 저글링 22·맹독충 4, 병력 인구 13,
  `V3_GROUND_BUILDS=PASS`.

## 남은 확인

- 빌드별 단독 실행으로 2·3·6기지 생산 건물 위치와 총수 확인
- 2·3·4·6기지의 일꾼 상한, 순차 확장, 확장별 가스 건설·채굴 확인
- 18~21분 실행으로 울트라 실생산 확인
- 프로토스 두 빌드의 초기 병력 생산 속도 추가 조정

## V3.6 병력 무천장: 순차 벽 → 병렬 트랙 (2026-07-23)

사용자 지시: 병력에 천장을 두지 말고 자원 되는 만큼 계속 생산. 저그 ling/bane만
병력 규모가 대조(upstream 목표치)에 미달.

**1차 시도(실패): 순차 병력목표 ×16 상향.** `ZergLingBaneUltra`의 3단계 함수
army `AISetStock` 목표를 전부 ×16(Open 저글링 30→480 등). 12명 ling/bane 미러
18분 측정에서 **전 슬롯 Open 정체**로 회귀 — 일꾼 39→13, 울트라 6→0, Hive/Lair
전무, supply_cap 106→56, 유휴 라바 15~22.

**원인(측정+코드 일치): `AISetStock`는 누적 목표를 직렬로 채운다.** 절대 못 채우는
거대 병력목표(Open의 480 저글링)가 그 **뒤에 놓인 일꾼(Drone 22/24)·오버로드
(5/6)·테크 항목을 영구 차단**한다. 캡핑과 무관한 순수 증거는 오버로드: 벽 뒤의
Overlord 5·6 항목이 실행 안 돼 supply_cap이 54~56에 얼어붙음. 병렬이면 미달과
무관하게 계속 지었을 것이므로 직렬 확정.

**수정(성공): 병력을 비차단 병렬 트랙으로 분리.** HEAD 커밋판이 쓰던 방식 복원 —
병력=`AISetStockUnitNext(N, unit, c_stockAlways)`, 일꾼=`AISetStockPeons(...c_stockMaxPeons,
c_stockAlways)`, 공급=`AISetStockFarms(...c_stockNormalFarms)`. 순차 `AISetStock`
리스트에는 건물/테크/업그레이드만 남김. 3-함수(Open/Mid/Late) 구조·게이트·매크로
해처리 호출은 유지. manifest bytes 7844, sha256 `a6de0768…`. `V3_STRUCTURE=PASS`,
`V3_AI_MOD_BUILD=PASS`.

**측정(12명 미러 18분, `runtime/reports/zerg-lingbane-parallel-mirror-18m.json`):**

| 지표(18분 평균) | 대조(원래) | ×16(고장) | 병렬(수정) |
| --- | ---: | ---: | ---: |
| army_supply | 32.5 | 43.5 | 54.4 |
| supply_cap | 106 | 54 | 79.7 |
| workers | 29 | 12.6 | 37.1 |
| upgrades | 0/0 | 0/0 | 1.17/0.50 |
| Lair 진행 | 일부 | 없음 | 12명 전부 |

병력 추이 단조증가(6→17→45→52→54), 경제·테크·업그레이드·단계진행 전부 복구.
순차 벽 회귀는 완전 해소.

**소프트캡 발견:** `AISetStockUnitNext(N, c_stockAlways)`는 "N 유지"라 ~N에서
소프트캡. Codex 1차가 HEAD 보수값(저글링 47)을 써서 저글링이 전 슬롯 47~48에서
정체하고 18분에 유휴 라바 27.7 + 공급 여유(cap 80, pop 55)가 남았다. 이 트랙은
비차단이므로 증분 N을 큰 unreachable 값(STOCK_SQUEEZE)으로 올리면 supply 한계까지
무한 생산 가능.

**무천장 완성(측정, `runtime/reports/zerg-lingbane-unbounded-mirror-18m.json`):**
각 유닛 최종 증분만 상향(Open 저글링 47→200·맹독 33→140; Mid 저글링→300·맹독→200·
바퀴→120; Late 저글링→470·맹독→330·바퀴→160·히드라→120·감염→40·울트라→30). 앞쪽
페이싱 체크포인트·일꾼·공급·테크·게이트·구조는 그대로. manifest bytes 7855, sha256
`f8f61a1b…`, 두 검증 PASS, `V3_GROUND_BUILDS=PASS`.

| 지표(18분 평균) | 대조 | ×16 | 병렬(소프트캡) | 무천장 |
| --- | ---: | ---: | ---: | ---: |
| army_supply | 32.5 | 43.5 | 54.4 | 72.0 |
| supply_cap | 106 | 54 | 79.7 | 102.0 |
| 유휴 라바 | 35 | 15.5 | 27.7 | 11.9 |
| 최다 저글링 | ~48 | ~48 | ~48 | 133 |

저글링이 47 캡을 뚫고(P4 133, P1 90, P5 78) army_supply 단조증가(6→17→48→65→72,
18분에도 상승 중), 유휴 라바 27.7→11.9 급감 — 남던 자원이 병력으로 전환. 경제·테크·
업그레이드는 건강 유지(비차단 확인). 사용자 목표 "병력 무천장" 달성.

**남은 것:** 울트라 실전 투입은 별개 이슈(테크 타이밍). 이번 4판 모두 18분에
Lair까지만 가고 Hive 미완이라 울트라 0. 미러에서 6분부터 교전해 테크가 느린 탓 +
울트라 체인이 순차 리스트 뒤쪽. 증분 상향으론 안 풀리며, 원하면 Hive/동굴 우선순위를
앞당기거나 21분+ 관측 필요. → V3.7에서 해결.

## V3.7 울트라 테크 앞당김 (2026-07-23)

**진단(측정+코드):** 단계 머신 Open→Mid→Late(userInt 146). Hive·InfestationPit·
UltraliskCavern·울트라 훈련이 **전부 Late 단계에만** 있는데, Mid→Late 게이트
(`Drone≥26 AND Roach≥12 AND Baneling(진행중이상)≥8`)가 맹독 morph 불안정으로 잘
안 열려 **다수 슬롯이 Mid에 갇힘** → Hive 영구 0. Late 재정렬은 도달을 못 하니 무의미.

**수정:** `V3ZergLingBaneUltraMid`에 울트라 테크 체인+훈련을 비차단 연속 트랙으로
추가(게이트에서 분리). Lair는 이미 Mid에 있어 재사용.
```
AISetStockUnitNext( player, 1, c_ZB_InfestationPit, c_stockAlways );
AISetStockUnitNext( player, 1, c_ZB_Hive, c_stockAlways );
AISetStockUnitNext( player, 1, c_ZB_UltraliskCavern, c_stockAlways );
AISetStock( player, 1, c_ZR_UltraliskArmor );
AISetStockUnitNext( player, 30, c_ZU_Ultralisk, c_stockAlways );
```
게이트·Open·Late·일꾼·공급·병력 증분은 불변(가산 변경). manifest bytes 8263,
sha256 `1b38b9c1…`, 두 검증 PASS.

**측정(12명 미러 18분, `runtime/reports/zerg-lingbane-ultratech-mirror-18m.json`):**
Hive 12분에 8/12 슬롯 보유(이전 4판 전부 Hive 0), 15분 9/12, 18분 대부분. **울트라
최초 등장(P12 18분 4기)** — 동굴 완성 직후라 18분 창엔 선두만 잡힘. 무천장 병력·경제
유지(저글링 P2 192기, 이전 최대 133 초과). 평균 army 62.8은 이번 판 P5 전멸·P4 대파
전투 변동 탓. 울트라 규모 확인은 21~24분 관측 필요(미확정).
