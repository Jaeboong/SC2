# V3 HANDOFF

갱신: 2026-07-23

## 현재 구조

V3는 Blizzard 설치 파일을 수정하지 않는다. 고정 upstream 54개와 V3 overlay 9개를
검증해 별도 `SC2TeamV3AI.SC2Mod`를 만들고, 생성된 맵이 이 mod를 dependency로
참조한다. Node와 Python은 맵·mod 생성과 실행에만 쓰이며 게임 중 명령을 발주하지
않는다.

핵심 소스는 다음과 같다.

- `v3/ai/manifest.json`, `v3/ai/upstream/`: upstream commit과 원본 54개
- `v3/ai/overlay/Base.SC2Data/TriggerLibs/V3/`: 독립 빌드 6개
- `v3/tools/build_v3_ai_mod.cjs`: 해시 검증, 종족 root hook 생성, mod 패키징
- `v3/tools/patch_v3_ai.cjs`: 맵 dependency와 플레이어별 build ID 삽입

`MeleeInitAI()`는 일꾼·타운·채집·웨이브 등 엔진 AI 기반을 초기화한다. 빌드 시 생성된
종족 Open/Mid/Late dispatcher가 V3 build ID에 대해서만 커스텀 Stock 정책을 실행한다.
업스트림 파일은 manifest의 SHA-256과 일치해야 하고 영구 root hook은 허용하지 않는다.

## 빌드 6개

| ID | 빌드 | 핵심 유닛 |
| ---: | --- | --- |
| 101 | 테란 바이오닉 | 해병, 불곰, 의무병, 공성전차 |
| 102 | 테란 메카닉 | 골리앗, 사이클론, 공성전차, 토르 |
| 201 | 프로토스 관문 | 광전사, 집정관, 고위 기사, 파수기 |
| 202 | 프로토스 관문+로보 | 광전사, 용기병 대체 유닛, 파수기, 불멸자, 거신 |
| 301 | 저그 바퀴/히드라 | 바퀴, 히드라, 후반 울트라 |
| 302 | 저그 저글링/맹독충 | 저글링, 맹독충, 후반 울트라 |

의무병은 비의무병 병력 보급을 기준으로 최대 5%만 Stock에 올린다. 프로토스 진영에
없는 유닛은 공통 맵 데이터의 기본 프로토스 대체 규칙을 따른다.

## 공통 운영 규칙

- 현재 opening gate는 일꾼 14기까지 생산하고 400광물을 비축한다.
- 일꾼 14기와 실제 보유 광물 400을 확인한 뒤 `AIExpand()`로 첫 확장 town을
  등록한다. `AIIsExpandingOrHasExpanded()`가 중복 요청을 막는다.
- 본진 반복 생산 건물은 단계 목표의 최대 50%만 둔다.
- 나머지 생산 건물은 완성된 확장 기지의 town-local Stock으로 균등 배분한다.
- 저그는 완성된 각 확장에 매크로 부화장 목표를 둔다.
- 야생 저그 7분 AI 지연은 아직 별도 엔진 검증 전이며 이번 커밋 범위가 아니다.

## 9분 실제 엔진 검증

SC2 5.0.16.97425에서 옵저버 모드로 여섯 빌드를 동시에 실행했다. 5초 시작 소유자는
P1~P6 모두 정상 보존됐고 Galaxy 컴파일도 통과했다.

| 빌드 | 3분 일꾼/확장 | 6분 일꾼/확장 | 9분 일꾼 | 9분 병력 예시 |
| --- | ---: | ---: | ---: | --- |
| 바이오닉 | 15/1 | 33/1 | 53 | 해병6, 불곰2, 전차1 |
| 메카닉 | 16/1 | 26/1 | 43 | 골리앗2, 사이클론3 |
| 관문 | 17/1 | 22/1 | 41 | 광전사8, 파수기1 |
| 관문+로보 | 17/1 | 20/1 | 27 | 광전사3, 추적자2, 파수기1, 불멸자1 |
| 바퀴/히드라 | 15/1 | 28/1 | 52 | 바퀴15, 히드라9 |
| 저글링/맹독충 | 13/1 | 19/3 | 56 | 저글링32, 맹독충4 |

결과: `V3_GROUND_BUILDS=PASS`. 3분에 병력이 없었던 빌드도 경제와 테크는 계속
진행했고 9분에는 여섯 빌드 모두 지정 병력을 생산했다. 동맹끼리 확장 자리를
경쟁하므로 후속 확장 수와 2·3·6기지 생산 건물 배치는 빌드별 단독 검증이 남아 있다.

## 핵심 파일과 다음 작업

| 경로 | 역할 |
| --- | --- |
| `v3/sc2team_v3/config.py` | 빌드 이름, ID, 종족 검증 |
| `v3/sc2team_v3/runtime.py` | 슬롯 매핑, plan 작성, 맵 빌드 |
| `v3/ai/upstream/` | 해시 고정 upstream AI 54개 |
| `v3/ai/overlay/Base.SC2Data/TriggerLibs/V3/` | 빌드 정책 6개 |
| `v3/tools/build_v3_ai_mod.cjs` | 검증된 V3 AI mod 빌드 |
| `v3/tools/patch_v3_ai.cjs` | 맵 dependency·build ID 삽입 |
| `app/play_custom_ai_v3.py` | V3 런처 |
| `v3/verification/probe_v3_ground_builds.py` | 3분 간격 엔진 프로브 |

다음 검증은 빌드별 단독 18~21분 실행으로 후반 울트라, 2·3·6기지 생산 건물 분산,
야생 저그의 7:00 적대 복원을 확인하는 것이다.

## 금지사항

- SC2 설치본의 원본 TriggerLib 수정
- manifest 검증 없이 upstream/overlay 변경
- MapScript/주기 트리거에서 `AIBuild`, `AITrain`, `AIResearch` 사용
- 생산자를 찾아 `UnitIssueOrder`로 생산·건설·연구 강제
- 런타임 Python/Node 컨트롤러 추가
- V1/V2 강제 생산 제어를 V3로 이식
