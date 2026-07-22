# V3 03:47 기준본: 업스트림 AI 호출 흐름

이 문서는 `runtime/v3-opening-static-check/SC2TeamV3AI.SC2Mod`(2026-07-23 03:47)의
manifest와 Galaxy 소스를 기준으로 작성한다. V3 정책은 직접 명령을 발행하지 않고,
업스트림의 stock·town·wave 엔진을 유지한다.

## 초기화와 메인 상태

`MapScript.galaxy`의 `MeleeInitAI()`가 엔진 melee AI를 시작한다. 이후 종족별
`AIMeleeTerr`, `AIMeleeProt`, `AIMeleeZerg`는 `e_mainState`를 읽어 다음 상태로
분기한다.

```
Init -> RaceInit -> Open -> Mid -> Late
              \-> Disabled (오류 또는 명시적 지연만)
```

각 `RaceInit`은 `AIMeleeSharedInit`을 호출한다. 공통 초기화는 위험 유닛 등록,
빌드 메뉴 설정, 전술 지연, 난이도 초기화, opening/late build 선택을 수행한다. 종족
초기화는 기본 군대 유닛·타운홀·종족 요구사항을 설정하고 `Open/Init` 상태로 넘긴다.

## V3 dispatcher와 정책

빌드 시에만 Terran/Protoss/Zerg root에 V3 include와 Open/Mid/Late dispatcher를
삽입한다. player user-int 142가 V3 build ID일 때 dispatcher가 `true`를 반환하여
난이도별 기본 build script 대신 V3 policy를 실행한다.

| 상태 | V3 phase | 전환 |
| --- | ---: | --- |
| Open | 0 | 시작부터 300초 전까지 |
| Mid | 1 | 300초 이후 |
| Late | 2 | 720초 이후 |

각 policy는 `AIClearStock` 뒤에 `AISetStock`, `AISetStockUnitNext`,
`AISetStockPeons`, `AISetStockFarms`, `AISetStockExpand`를 선언하고
`AIEnableStock`으로 엔진에 전달한다. 따라서 일꾼 충원, 가스, 생산 건물, 병력 생산,
업그레이드, 확장과 확장지 자원 분배는 엔진 stock/town 처리 흐름에 남는다.

## 첫 확장과 생산 순서

여섯 V3 policy는 14 완성 일꾼 및 400 광물에서 열린 확장 위치를 확인하고
`AIExpand()`로 확장 town을 등록한다. 두 번째 타운홀이 queued-or-better가 될 때까지
생산 건물 목표를 공개하지 않고 Stock을 활성화한 채 return한다.

업스트림 `AIIsExpandingOrHasExpanded`는 town state가 `Claimed` 또는 `Building`이면
즉시 확장 중으로 보고, established town도 검사한다. V3도 이 함수를 사용해
`AIExpand()` 중복 호출을 막고 실제 건설은 town/stock 엔진에 맡긴다.

## 아군 지원과 공격 wave

`MeleeWaveAI`가 wave를 운용한다. 우선순위는 자기 기지 위협 방어,
`AIAnyAllyNeedsDefending`에 따른 아군 지원, 대기/집결, 공격이다. 방어 wave는
위협이 사라진 뒤 30초 대기하면 attack wave로 합쳐진다. V3 policy는
`AISetAttackStatus`로 병력 편성과 병합 규칙만 제공하고, 이동·교전 명령을 직접
내리지 않는다.

## 야생 저그 제약

P15의 소유권·동맹·플레이어 슬롯은 변경하지 않는다. `MeleeInitAI()` 직후 P15의
main state를 Disabled, attack state를 Wait로 두고 420초에 main/sub state를 Init으로
돌린다. 엔진 검증에서 P15 일꾼은 5초 20기와 419초 20기로 고정됐고 480초에는
25기로 늘었다. 같은 실행에서 일반 플레이어와 P15 소유자가 모두 보존됐다.
