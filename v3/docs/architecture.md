# V3 아키텍처

## 실행 흐름

```text
런처 빌드 선택
  → Python이 슬롯/종족/build ID plan 작성
    → Node 빌더가 고정 업스트림 54개와 V3 overlay 10개로 SC2Mod 생성
      → 종족 root 세 곳에 빌드 시점 dispatcher hook 생성
        → 맵에 mod dependency와 플레이어별 build ID 삽입
          → SC2가 MeleeInitAI()로 AI를 초기화하고 V3 Stock 정책 실행
```

Python과 Node는 게임 시작 전에 맵과 `SC2TeamV3AI.SC2Mod`를 만드는 도구다. 런처는
생성된 mod를 SC2 `Mods` 폴더에 설치하지만 Blizzard 원본 파일을 수정하지 않는다.
게임 중 주기적으로 명령하는 외부 컨트롤러는 없다. 사용자 승인 예외로 P15는 맵 Galaxy가
시작 시 AI 초기화와 초기 자원 주입만 한 번 수행하고 즉시 역할을 끝낸다.

## 소스 경계

| 계층 | 책임 |
| --- | --- |
| 공통 맵 빌더 | 맵, 슬롯, 팀, 시작점, 캠페인 데이터, 프로토스 대체 규칙, 야생 저그 |
| `v3/ai/upstream` | commit과 SHA-256이 고정된 Blizzard AI 54개 |
| `v3/ai/overlay` | dispatcher 3개와 독립 빌드 정책 6개 |
| CJS mod 빌더 | 해시 검증, root hook 생성, SC2Mod 패키징 |
| CJS 맵 패처 | mod dependency와 build ID 142 삽입 |
| 엔진 하네스 | 3분 간격 인구·일꾼·병력·건물·기지 측정 |

`MeleeInitAI()`는 타운, 채집, 요구조건, 생산 실행기와 웨이브 시스템을 초기화한다.
종족별 Open/Mid/Late dispatcher는 build ID가 V3일 때 Blizzard 난이도별 빌드 대신
V3 Stock 목표를 실행하고, 나머지 엔진 흐름은 그대로 유지한다.

야생 저그가 활성화되면 맵 Galaxy는 `MeleeInitAI()` 직후 P15를 한 번만 부팅하고 즉시
역할을 끝낸다. 타이머나 주기 이벤트는 만들지 않으며, 이후에는 임베디드
`V3/Zerg.galaxy`(1~1141행)만 반복 실행된다.

build 315의 town 구조, 400 보급 천장, 9분 휴전, 승격 3종 세트, 금지 사항은
→ [`wild-zerg.md`](wild-zerg.md)

## 데이터 계약

- AI user int 142: 빌드 ID
- AI user int 144: 첫 확장 gate 완료
- 빌드 ID: 101, 102, 201, 202, 301, 302, 315(P15 전용)
- 단계: 0~5분, 5~12분, 12분 이후

첫 확장은 14기·400광물 조건 후 `AIExpand()`로 타운을 등록하며
`AIIsExpandingOrHasExpanded()`로 중복 요청을 막는다. V3는 기본적으로 Stock
목표만 제공하지만, Stock으로 멜리 AI가 안정적으로 만들지 못하는 것(울트라리스크
모프, 집정관 합체 — §71/§87 방식, v3.11~13)은 게이트된 직접 주문(`UnitIssueOrder`)으로
처리한다. `AITrain`/`AIResearch`는 여전히 쓰지 않는다. 자세한 근거는
[`references.md`](references.md)·[`status.md`](status.md) 참조.

첫 확장 이후에는 `AIIsExpandingOrHasExpanded()`를 사용하지 않는다. 이 업스트림
함수는 두 번째 town이 존재하면 계속 true이므로 후속 확장 판정에 적합하지 않다.
공통 확장 경제 정책은 `Claimed`·`Building` town이 없는지 직접 검사하고, 완성된
채광 town이 4개 미만이면 이전 town 완성 후 다음 `AIExpand()`를 요청한다. 4기지
이후에는 현재 일꾼이 `광물 지점×2 + 완성 가스×3` 목표에 도달했을 때만 최대
6기지까지 확장한다.

일꾼 Stock의 모든 고정 목표는 완성된 채광 town의 `광물 지점×2 + 완성 가스×3`
상한으로 제한한다. 확장 가스는 전역 총량과 별도로 established non-main town에
`AISetStockEx`로 등록하고, `AIGetHarvestableGasNumSpots * 3`을 해당 town의 가스
일꾼 목표로 사용한다.
