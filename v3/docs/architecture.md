# V3 아키텍처

## 실행 흐름

```text
런처 빌드 선택
  → Python이 슬롯/종족/build ID plan 작성
    → Node 빌더가 고정 업스트림 54개와 V3 overlay 9개로 SC2Mod 생성
      → 종족 root 세 곳에 빌드 시점 dispatcher hook 생성
        → 맵에 mod dependency와 플레이어별 build ID 삽입
          → SC2가 MeleeInitAI()로 AI를 초기화하고 V3 Stock 정책 실행
```

Python과 Node는 게임 시작 전에 맵과 `SC2TeamV3AI.SC2Mod`를 만드는 도구다. 런처는
생성된 mod를 SC2 `Mods` 폴더에 설치하지만 Blizzard 원본 파일을 수정하지 않는다.
게임 중 외부 컨트롤러는 없다.

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

야생 저그가 활성화된 V3 맵은 `MeleeInitAI()` 직후 P15의 AI state index 1/2/3
(main/sub/attack)만 Disabled/Unset/Wait로 고정한다. 420 게임초의 일회성 트리거가
main/sub를 Init으로 바꾸면서 저그 AI 빌드가 시작된다. 플레이어 컨트롤러, 유닛
소유권, 동맹, 채집 명령은 이 지연 경로에서 변경하지 않는다.

## 데이터 계약

- AI user int 142: 빌드 ID
- AI user int 144: 첫 확장 gate 완료
- 빌드 ID: 101, 102, 201, 202, 301, 302
- 단계: 0~5분, 5~12분, 12분 이후

첫 확장은 14기·400광물 조건 후 `AIExpand()`로 타운을 등록하며
`AIIsExpandingOrHasExpanded()`로 중복 요청을 막는다. 직접 유닛 생산 명령은
사용하지 않는다.
