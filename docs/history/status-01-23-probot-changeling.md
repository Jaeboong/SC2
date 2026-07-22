# 과거 상태 기록 §1–23 — ProBot·Changeling 실험기 (Custom AI 이전)

`docs/latest_status.md`에서 분리한 원문이다. 절 번호는 원본 그대로 보존한다.
이 구간의 구조(외부 ProBot 다대다, Changeling 연동)는 §23에서 종료됐고 현재
버전과 무관하다.

## 1. 목표

원래 목표는 StarCraft II 로컬 환경에서 아래와 같은 커스텀 봇 팀전을 실행하는 Windows 런처를 만드는 것이었다.

```text
사람 + ProBot A  vs  ProBot B + ProBot C
```

Battle.net이나 일반 래더에는 접속하지 않고, 모든 게임과 봇 프로세스를 사용자 PC에서만 실행하는 것을 전제로 했다.

## 2. 사용자 환경

- 운영체제: Windows
- StarCraft II 설치 경로: `C:\Program Files (x86)\StarCraft II`
- 확인된 최신 실행 파일: `Versions\Base97425\SC2_x64.exe`
- 게임 버전: `5.0.16.97425`
- CPU: AMD Ryzen 7 9800X3D
- GPU: NVIDIA GeForce RTX 5070 Ti
- 메모리: DDR5-6000 32GB
- Python: 3.14.0
- Node.js: 설치됨
- Git: 설치됨
- .NET SDK: 설치되지 않음
- CMake: 설치되지 않음

하드웨어 성능은 SC2 프로세스 4개와 여러 봇 프로세스를 동시에 실행하기에 충분하다. 이번 중단 원인은 PC 성능이 아니라 SC2 API의 게임 생성 제한이다.

## 3. 조사 결과

### s2client-proto

`Blizzard/s2client-proto`는 SC2 게임 소스나 완성된 봇이 아니라, 외부 프로그램과 SC2 클라이언트 사이의 Protocol Buffers 통신 규격이다.

주요 용도는 다음과 같다.

- 스크립트 또는 머신러닝 기반 봇
- 게임 상태 관측과 유닛 명령
- 리플레이 분석
- 사람 조작을 보조하는 도구

관련 저장소:

- 프로토콜: <https://github.com/Blizzard/s2client-proto>
- 공식 C++ 클라이언트: <https://github.com/Blizzard/s2client-api>
- AlphaStar 연구 코드: <https://github.com/google-deepmind/alphastar>

### AlphaStar와 공개 ProBot

- AlphaStar 완성 모델은 일반 사용자가 설치하여 대전할 수 있는 형태로 공개되지 않았다.
- DeepMind의 공개 저장소는 주로 학습 아키텍처와 오프라인 학습 도구를 제공한다.
- 커뮤니티 ProBot은 AI Arena에서 봇 대 봇 경기를 진행한다.
- 사람이 ProBot과 1대1로 대전할 때는 VersusAI의 ProBots vs Human App을 사용할 수 있다.

관련 사이트:

- AI Arena: <https://aiarena.net/>
- VersusAI 사람 대 ProBot 안내: <https://versusai.net/how-to-play-against-the-probots/>

## 4. 내려받은 외부 자료

### ProBots vs Human App 2025 S1

- 원본 파일: `vendor/archives/SC2AIApp_2025_S1.zip`
- 크기: 295,266,567바이트
- 압축 해제 위치: `vendor/SC2AIApp_2025_S1/`
- 출처: VersusAI 공식 사람 대 ProBot 안내 페이지의 Dropbox 링크

포함된 봇 디렉터리:

- `BenBotBC`
- `changeling`
- `MicroMachine`
- `sharkbot`
- `dummy_bot` — 실행 및 설정 확인용 봇

포함된 앱은 Qt 기반 네이티브 `SC2AIApp.exe`이며, 공식 사용 흐름은 사람 1명과 ProBot 1명의 1대1 대전이다. 앱은 SC2 창을 사람용과 봇용으로 각각 하나씩 실행한다.

`HumanLadder.json`, `PlayerIds`, 각 봇의 `ladderbots.json`을 확인해 실행 형식과 런타임 종류를 조사했다.

봇별 확인된 실행 유형:

| 봇 | 종족 | 실행 유형 |
|---|---|---|
| BenBotBC | Terran | Java JAR |
| changeling | Random | C++ 실행 파일 |
| MicroMachine | Terran | C++ 실행 파일 |
| sharkbot | Protoss | self-contained .NET 실행 파일 |
| dummy_bot | Terran | Python |

외부 봇과 앱의 라이선스 및 재배포 조건은 아직 개별 검토하지 않았다. `vendor/`와 원본 ZIP을 공개 저장소에 올리기 전에는 반드시 라이선스를 확인해야 한다.

### Blizzard Melee Map Pack

- 원본 파일: `vendor/archives/Melee.zip`
- 크기: 235,477바이트
- 출처: <https://blzdistsc2-a.akamaihd.net/MapPacks/Melee.zip>
- 암호: `iagreetotheeula`
- 압축 해제 위치: `maps/Melee/`

압축 해제된 맵:

- `Empty128.SC2Map`
- `Flat32.SC2Map`
- `Flat48.SC2Map`
- `Flat64.SC2Map`
- `Flat96.SC2Map`
- `Flat128.SC2Map`
- `Simple64.SC2Map`
- `Simple96.SC2Map`
- `Simple128.SC2Map`

맵 팩을 사용하는 것은 Blizzard AI and Machine Learning License 동의가 전제된다.

## 5. 프로젝트에 구현된 파일

### `sc2team/protocol.py`

SC2 API WebSocket 통신을 위한 최소 프로토콜 클라이언트다.

구현된 기능:

- SC2 API 포트 연결과 재시도
- `ping`
- 로컬 맵 데이터로 `create_game`
- 멀티플레이 포트 세트를 포함한 `join_game`
- 실시간 `observation`
- `quit`
- 참가자 수에 따른 server/client port 배정

### `sc2team/process.py`

Windows에서 SC2 실행 파일을 찾고 여러 인스턴스를 실행·종료한다.

중요하게 확인된 실행 조건:

- 실제 실행 파일은 `Versions\Base97425\SC2_x64.exe`다.
- 작업 디렉터리는 실행 파일의 폴더가 아니라 SC2 설치 폴더의 `Support64`여야 한다.
- 실행 파일 폴더를 작업 디렉터리로 사용하면 SC2가 오류 없이 즉시 종료된다.
- `Support64`를 작업 디렉터리로 사용하면 `-listen`과 `-port`로 지정한 API 포트가 정상적으로 열린다.

### `verification/smoke_test.py`

SC2 인스턴스 4개를 실행하고 네 참가자를 하나의 로컬 게임에 연결해 보는 재현용 검증 프로그램이다.

기본 실행 명령:

```powershell
.\.venv\Scripts\python.exe -u .\verification\smoke_test.py --seconds 8
```

기본 검증 맵은 `maps/Melee/Flat128.SC2Map`이다.

### Python 가상환경

프로젝트 폴더의 `.venv/`에 설치했다.

`requirements.txt`에 고정된 패키지:

```text
protobuf==3.20.3
s2clientprotocol==5.0.16.97425.0
websockets==16.1
```

`s2clientprotocol`의 생성 코드가 오래된 Protobuf descriptor 방식을 사용하므로 최신 `protobuf 7.x`에서는 불러오지 못했다. 호환성을 위해 `protobuf 3.20.3`으로 고정했다.

## 6. 실제 실행 검증

### 첫 번째 실행

결과: 실패

원인: `SC2_x64.exe`의 작업 디렉터리를 `Versions\Base97425`로 지정했다. 네 프로세스가 종료 코드 0으로 즉시 종료되어 API 포트가 열리지 않았다.

수정: 작업 디렉터리를 `C:\Program Files (x86)\StarCraft II\Support64`로 변경했다.

### 두 번째 실행

다음 단계까지 성공했다.

1. SC2 프로세스 4개 실행
2. API 포트 `14100`부터 `14103`까지 WebSocket 연결
3. 네 프로세스 모두 `ping` 성공
4. 네 프로세스 모두 게임 버전 `5.0.16.97425` 보고
5. 로컬 맵 데이터와 참가자 4명으로 게임 생성 요청

게임 생성 요청에서 SC2 엔진이 다음 오류를 반환했다.

```text
Only 1v1 is supported when using multiple agents
```

프로그램이 기록한 예외:

```text
sc2team.protocol.Sc2ProtocolError:
create_game failed (7): Only 1v1 is supported when using multiple agents
```

따라서 실패 원인은 포트, 맵 경로, 컴퓨터 성능 또는 런처 코드가 아니다. SC2 5.0.16 게임 엔진이 외부 API 참가자가 여러 명인 게임을 1대1로 제한하기 때문이다.

### 세 번째 실행: Participant 2명 + 내장 Computer 2명

다음 구성의 가능성을 추가로 검증했다.

```text
사람 + 기본 AI  vs  ProBot + 기본 AI
```

이를 API 기준으로 다음과 같이 구성했다.

- 외부 API `Participant`: 2명 — 사람과 ProBot에 해당
- SC2 내장 `Computer`: 2명
- 외부 SC2 프로세스: 2개
- 맵: `Flat128.SC2Map`
- 실행 명령:

```powershell
.\.venv\Scripts\python.exe -u .\verification\smoke_test.py `
  --participants 2 --computers 2 --seconds 6
```

두 SC2 프로세스 실행, API 연결 및 버전 확인까지 성공했지만 `create_game` 단계에서 엔진이 다시 같은 오류를 반환했다.

```text
create_game failed (7): Only 1v1 is supported when using multiple agents
```

따라서 외부 참가자는 사람과 ProBot 두 명뿐이더라도, 여기에 내장 Computer 슬롯을 추가해 2대2 게임을 만드는 것은 불가능하다. SC2 API의 제한은 외부 에이전트 수만이 아니라 다중 에이전트 게임의 전체 플레이어 구성을 1대1로 제한한다.

### 네 번째 실행: Participant 1명 + 내장 Computer 3명

직접 제작하는 AI를 커스텀 맵 내부 Computer 슬롯과 연결할 수 있는지 판단하기 위해 다음 구성을 추가로 검증했다.

```text
외부 API Participant 1명 + SC2 내장 Computer 3명
```

실행 명령:

```powershell
.\.venv\Scripts\python.exe -u .\verification\smoke_test.py `
  --participants 1 --computers 3 --seconds 5
```

결과는 성공이었다.

```text
Connected: 5.0.16.97425
Created game with 1 participants and 3 computers
SUCCESS: participants joined with player IDs [1]
game loops: [0], [24], [47], [69], [91]
```

따라서 SC2 API가 금지하는 것은 Computer 슬롯 여러 개 자체가 아니라 외부 API Participant가 2명 이상 참여하면서 전체 게임이 1대1을 넘는 구성이다. 외부 Participant를 한 명만 두면 여러 Computer 플레이어가 있는 게임은 정상 실행된다.

## 7. 최종 기술 결론

아래 구성은 공식 SC2 API로 구현할 수 없다.

```text
사람 + 독립 ProBot A  vs  독립 ProBot B + 독립 ProBot C
```

다음 혼합 구성도 실제 검증 결과 구현할 수 없다.

```text
사람 + SC2 기본 AI  vs  독립 ProBot + SC2 기본 AI
```

이 구성은 사람을 포함해 독립된 외부 API 참가자 슬롯이 총 4개 필요하다. SC2 엔진이 게임 생성 단계에서 이를 거부하므로, 다음 작업을 추가해도 해결되지 않는다.

- 4인용 맵 교체
- WebSocket 프록시 추가
- 포트 배정 방식 변경
- AI Arena 매치 컨트롤러 확장
- SC2 인스턴스 추가 실행
- PC 사양 향상

SC2 게임 바이너리 자체를 변조하지 않는 범위에서는 이 제한을 우회할 수 없다고 판단한다. 바이너리 변조는 안정성·호환성·서비스 약관 문제 때문에 프로젝트 범위에서 제외한다.

단, 직접 제작하는 AI를 일반 SC2 API Participant가 아니라 커스텀 맵 내부 Computer 플레이어의 제어 로직으로 구현하는 별도 방식은 가능하다. 이 경우 유명 ProBot과 호환되는 표준 SC2 API 봇 구조가 아니라 전용 맵과 전용 명령 브리지를 사용해야 한다.

## 8. 가능한 대안

### 현실적으로 구현 가능한 기능

1. 사람 대 유명 ProBot 1대1 로컬 런처
2. ProBot 대 ProBot 1대1 로컬 런처
3. 상대 봇, 맵, 사람 종족을 선택하는 GUI
4. 리플레이 자동 저장과 봇 로그 수집
5. 봇별 런타임 검사와 실행 오류 안내

현재 내려받은 패키지만으로도 MicroMachine, Sharkbot, Changeling, BenBotBC를 대상으로 1대1 런처를 개발할 수 있다.

### 팀전과 비슷하지만 동일하지 않은 대안

- 사람 대 ProBot 1대1 맵에서 양쪽에 기지와 시작 유닛을 두 세트씩 제공
- 사람과 봇이 한 플레이어의 유닛을 동시에 조작하는 공유 제어 실험
- SC2 일반 커스텀 게임에서 사람과 내장 AI를 섞은 2대2

이 방법들은 독립 ProBot 네 명이 참가하는 진짜 2대2가 아니다. 특히 여러 봇이 한 플레이어를 공유하면 자원·보급·생산·유닛 명령이 충돌하므로 일반적인 유명 1대1 봇을 그대로 사용할 수 없다.

### 직접 제작 AI를 이용한 실제 다대다 대안

네 번째 실행 결과를 기반으로 다음 전용 구조는 구현 가능하다.

```text
SC2 게임
├─ Player 1: 사람 — 유일한 외부 API Participant
├─ Player 2: 직접 만든 AI A — 맵 내부 Computer
├─ Player 3: 직접 만든 AI B — 맵 내부 Computer
└─ Player 4: 직접 만든 AI C — 맵 내부 Computer
```

필요한 구성 요소:

1. SC2 Editor로 만든 4인 전용 맵
2. 맵 시작 시 `Player 1 + Player 2`와 `Player 3 + Player 4`의 동맹을 설정하는 Galaxy 트리거
3. Computer 플레이어의 유닛에 명령을 내리는 맵 내부 제어 코드
4. 선택적으로 Python 중앙 AI 컨트롤러와 Galaxy 맵 사이의 `RequestMapCommand` 명령 브리지
5. 각 Computer 플레이어별 관측 필터, 자원 상태 및 전략 모듈

중앙 Python 프로그램 하나에 AI A/B/C 모듈을 넣고 각 모듈이 자기 플레이어만 판단하도록 만들 수 있다. 계산한 행동은 표준 `RequestAction`이 아니라 커스텀 맵 명령을 통해 해당 Computer 플레이어의 유닛에 적용한다.

이 방식은 실제 게임 안에서 플레이어별 유닛·자원·보급·동맹이 분리된 다대다를 만들 수 있다. 그러나 기존 MicroMachine, Sharkbot 같은 ProBot은 직접 참가자 접속과 `RequestAction`을 전제로 하므로 그대로 사용할 수 없으며, 새 인터페이스에 맞춰 AI를 직접 작성해야 한다.

## 9. 확정된 현재 목표

```text
서쪽: Player 1(사람) + 내장/커스텀 AI 3명
동쪽: 내장/커스텀 AI 4명
```

- 원본 맵: 한국 서버 `유럽 섬멸전_2`
- 게시자: `dddsa#517`
- Battle.net 식별자: `battlenet:://starcraft/map/3/162910`
- 원본의 14개 플레이어 슬롯 유지
- 실제 플레이어는 우선 8명만 사용
- P1~P4는 서쪽, P5~P8은 동쪽에 팀별 배치
- 모든 광물과 가스를 풍부한 자원으로 변경하고 한 덩어리당 50,000으로 설정
- 일반 전투 유닛과 건물 데이터는 섬멸전 기본값 사용
- SCV, 탐사정, 일벌레의 보급 비용만 0으로 변경

공개 맵 메타데이터상 이 맵은 14인용 섬멸전 맵이며 2023-05-12에 게시된 버전 1.1이다. 확인용 미니맵은 `docs/assets/map_candidates/europe-melee-2-14p.jpg`에 저장했다.

## 10. 정확한 원본 확보

사용자가 Battle.net에서 맵을 연 뒤 새로 생긴 캐시 파일을 찾아 다음 위치로 복사했다.

```text
maps/source/europe-melee-2-original.SC2Map
```

- 파일 크기: 2,931,559바이트
- SHA-256: `ABEF037D164C4B658D7FA8E7DA3C185F4EC64AD83B441C9239AE20AD562CCC70`
- 플레이어 슬롯: Player 1~14
- 내부 `StartLoc` 객체: 20개

사용자가 말한 14개는 실제 맵 구조상 플레이어 슬롯 수다. 원본에는 무작위 시작점 후보가 20개 있으며, 최종 맵에서도 이 20개를 한 개도 삭제하거나 변경하지 않았다.

## 11. 구현된 맵 변환

`tools/build_team_map.cjs`가 원본 `SC2Map`을 복사한 뒤 내부 MPQ 데이터를 수정한다.

### 풍부한 자원

- `MineralField` → `RichMineralField`
- `MineralField750` → `RichMineralField750`
- `MineralFieldOpaque`, `MineralFieldOpaque900` → `RichMineralField`
- `VespeneGeyser`, `ProtossVespeneGeyser`, `SpacePlatformGeyser` → `RichVespeneGeyser`

이미 풍부한 자원 종류는 그대로 둔다. 변환 후 광물과 가스 오브젝트 763개 전부에 `Resources="50000"`을 명시하며 `StartLoc` 객체는 수정하지 않는다.

### 비표준 유닛 데이터 제거

원본 `Base.SC2Data\\GameData\\UnitData.xml`에서 다음 변경을 발견했다.

- 벙커 시작/최대 체력 2000
- 관문 능력 배열 항목 제거
- 관문 생산 카드 슬롯 변경·제거

맵 후기에 언급된 유닛 누락 또는 기본값 이탈의 실제 원인으로 판단된다. 최종 빌드에서는 기존 유닛 오버라이드를 전부 폐기하고 아래 세 항목만 새로 작성한다.

```xml
<CUnit id="Drone"><Food value="0"/></CUnit>
<CUnit id="Probe"><Food value="0"/></CUnit>
<CUnit id="SCV"><Food value="0"/></CUnit>
```

따라서 나머지 유닛과 건물은 설치된 SC2 5.0.16의 `Void`/`VoidMulti` 기본 섬멸전 데이터를 상속한다. 지형과 장식을 위한 Actor/Model/Light/Water 데이터는 유지한다.

### 4대4 동맹과 배치

- P1~P4: 공유 시야 동맹
- P5~P8: 공유 시야 동맹
- 양 팀 사이: 적대
- 20개 시작점 후보 중 가장 서쪽 4곳과 가장 동쪽 4곳 사용
- `MeleeInitUnits()` 직후 시작 건물과 일꾼을 지정 위치로 이동
- 이동과 동맹 설정 후 `MeleeInitAI()` 실행

## 12. 최종 맵과 검증 결과

생성된 최종 파일:

```text
maps/generated/europe-melee-2-4v4-rich-50000.SC2Map
```

- 파일 크기: 2,931,556바이트
- SHA-256: `A1F5EB40780A188596C85A8C6A0045112474FA59EA6B26A1A46C6F1FD1AB4F1A`
- 원본/최종 `StartLoc` XML 비교: 20개 모두 동일
- 일반 광물 종류 잔존 수: 0
- 일반 가스 종류 잔존 수: 0
- 광물/가스 오브젝트 763개 모두 시작 자원량 50,000
- 최종 `UnitData.xml` 유닛 항목: `Drone`, `Probe`, `SCV`뿐

사람 Participant 1명과 내장 Computer 7명으로 SC2 5.0.16에서 실행 검증했다.

```text
P1~P4: 서쪽, P1 기준 Self/Ally
P5~P8: 동쪽, P1 기준 Enemy
Player 1 food_used: 0
서쪽 팀 평균 X 최대: 39.2
동쪽 팀 평균 X 최소: 202.0
```

기본 유닛 복원도 런타임에서 추가 확인했다.

- 벙커 현재/최대 체력: `400/400`
- 벙커, 관문, 파수기, 사도, 고위 기사, 암흑 기사: 모두 사용 가능
- 관문 생산 명령: 광전사, 추적자, 고위 기사, 암흑 기사, 파수기, 사도

## 13. 현재 상태 요약

- 정확한 `유럽 섬멸전_2` 원본: 확보 완료
- 14개 플레이어 슬롯 유지: 완료
- 원본 시작점 후보 20개 무변경 보존: 완료
- 풍부한 광물·풍부한 가스: 완료
- 일꾼 보급 비용 0: 완료
- 비표준 벙커·관문 데이터 제거: 완료
- P1~P4 서쪽 / P5~P8 동쪽 배치: 완료
- 4대4 동맹과 적대 관계: 완료
- 사람 1명 + 내장 AI 7명 실제 엔진 실행: 통과
- 외부 ProBot 여러 명이 참가하는 다대다: SC2 API 엔진 제한으로 여전히 불가

## 14. 실제 플레이용 설정 GUI

`app/play_local.py`와 더블클릭용 `start_4v4.cmd`를 추가했다.

GUI에서 설정할 수 있는 항목:

- P1 사람 종족: 무작위, 테란, 저그, 프로토스
- P2~P8 AI 종족: 무작위, 테란, 저그, 프로토스
- 각 AI 빌드: 선택한 종족의 공식 지상 세부 빌드
- 각 AI 난이도: 아주 쉬움부터 정예까지와 시야/자원/광란 치터

### AI 빌드 선택 범위 정정

처음 구현한 종족별 `테란 자원·확장 집중`, `관문 중심 초반 러시` 등의 표시는 공식 빌드명이 아니라 API의 6개 범주에 붙인 임의 설명이었다. 실제 선택 범위로 오해할 수 있어 제거했다.

설치된 SC2 5.0.16 빌드 97425의 프로토콜과 게임 데이터를 대조한 결과는 다음과 같다.

- `s2client-proto`의 `PlayerSetup.ai_build`가 허용하는 값은 `RandomBuild`, `Rush`, `Timing`, `Power`, `Macro`, `Air` 여섯 개뿐이다.
- 게임 내부에는 이와 별도로 더 자세한 빌드가 존재한다.
- 공식 한국어 자원 빌드는 테란 `바이오닉 해불선`, `메카닉`, `토르 순양함`, 저그 `감염충`, `히드라 가시지옥`, `울트라리스크`, `무리 군주`, 프로토스 `관문 불멸자`, `거신`, `관문 공중`이다.
- 이 세부 빌드들은 일반 API의 `ai_build` 필드로 개별 지정할 수 없다.

이 제한을 넘기 위해 실행 직전에 `tools/configure_team_map.cjs`가 P2~P8의 상세 빌드 ID를 임시 맵에 기록한다. 맵 스크립트는 `c_specificLobbyBuild`에 해당하는 AI 내부 사용자 변수 130을 유지하여 종족별 상세 빌드를 적용한다. GUI에서 종족을 변경하면 공식 한국어 지상 빌드만 동적으로 표시된다.

### 지상전 전용 규칙

2026-07-15 실험에서 세부 빌드 ID를 AI 내부 변수에 반복 적용하고 공중 전투 유닛을 기술 트리에서 차단했으나, 실제 실행 시 다수 플레이어의 시작 유닛이 생성되지 않는 회귀가 발생했다. 검증 도구에서도 P2, P3, P4, P5, P6, P8 유닛 누락을 재현했다.

문제가 발생한 맵 내부 세부 빌드 강제와 기술 트리 차단 코드는 전부 롤백했다. 안정 버전에서는 다음만 적용한다.

- 일반 API의 `Air` 성향을 GUI에서 제외
- 기본 성향은 `Macro` 유지
- 세부 빌드 선택을 실제 적용하는 것처럼 표시하지 않음

롤백 후 실제 SC2 검증에서 P1~P8 모두 시작 유닛이 존재하고, 게임 루프 97까지 정상 진행했다. 확인된 시작 유닛 수는 순서대로 `10, 9, 13, 9, 9, 13, 11, 9`이며 동·서 진영, 동맹, 일꾼 인구 0도 통과했다. 완전한 지상전 강제는 시작 유닛 초기화와 충돌하지 않는 별도 방식이 확인될 때까지 미구현 상태다.

요청된 기본값:

```text
P2~P7: 정예 (VeryHard)
P8: 자원 치터 (CheatMoney)
P2~P8 빌드: 종족별 지상 자원형 자동
P1~P8 종족: 무작위
```

마지막 설정은 `runtime/launcher_settings.json`에 저장되며 GUI의 `기본값 복원` 버튼으로 초기 설정을 되살릴 수 있다.

`sc2team/protocol.py`에는 AI별 `race`, `difficulty`, `ai_build`, 이름을 전달하는 `ComputerPlayer` 설정을 추가했다. GUI는 이 설정으로 SC2를 한 개 실행하고 사람 Participant 1명과 서로 다른 설정의 Computer 7명을 만든 뒤, 게임 종료까지 API 연결을 유지한다.

검증 결과:

- 설정 모델 단위 테스트 5개 통과
- Tkinter 8.6 GUI 생성 통과
- 종족별 지상 세부 빌드 표시/값 변환 통과
- P8 기본 `CheatMoney` 확인
- API에는 AI 7명 모두 호환용 `Macro`를 전달하고 맵에서 세부 빌드를 덮어쓰는 구조 확인
- 지상 세부 빌드 ID가 기록된 맵으로 SC2 5.0.16 게임 생성, P1 참가 및 게임 루프 진행 성공

## 15. Battle.net 로비의 섬멸전 4대4 변형 수정

첫 게시본의 로비에서 범주와 모드가 모두 `그 밖의 범주`로 표시되는 문제를 확인했다. 원인은 맵 내부 `Attributes`가 다음 사용자 변형으로 남아 있었기 때문이다.

```text
CategoryId=6
ModeName=기타
MaxTeamSize=12
```

로컬 Battle.net 캐시에 저장된 정상적인 4대4 섬멸전 맵의 변형을 대조하여 다음 값으로 수정했다.

```text
CategoryId=2
ModeName=4 대 4
MaxTeamSize=4
```

> 이후 14인 표준 섬멸전 변형을 추가 대조한 결과 `CategoryId=2` 판단은 잘못된 것으로 확인됐다. 현재 도구는 섬멸전 범주 `CategoryId=6`과 슬롯별 팀 속성 `2011`을 사용하며, 자세한 정정 내용은 18절에 기록했다.

수정용 도구 `tools/fix_lobby_variant.cjs`를 추가했으며, `tools/build_team_map.cjs`도 이후 빌드부터 같은 로비 설정을 자동 적용한다. 에디터에서 사용자가 직접 변경한 자원 위치를 보존하기 위해 게시 직전 저장본을 입력으로 삼아 별도 파일을 생성했다.

```text
maps/generated/europe-melee-2-4v4-rich-50000-melee.SC2Map
```

- 파일 크기: 2,931,519바이트
- SHA-256: `312B470FF7447F30D9815868E2A48C7C0C72BD83D250CB313BD6946F6D82D972`
- 수동 편집 후 남은 광물·가스 오브젝트: 715개
- 715개 전부 자원량 50,000
- P1~P4 서쪽 / P5~P8 동쪽 강제 배치 스크립트 유지
- P1~P4 동맹 / P5~P8 동맹 / 양 팀 적대 유지
- 일꾼 보급 비용 0 유지

SC2 5.0.16 실제 엔진 검증 결과, P1~P8 시작 유닛이 모두 생성됐고 게임 루프 74에서 동서 배치, 동맹, 일꾼 보급 0, 자원량 50,000 검사를 모두 통과했다. 로컬 실행 GUI도 이 수정본을 기본 맵으로 사용하도록 변경했다.

## 16. 최대 7대7 동·서 고정 배치 확장

2026-07-15 게시 로비에서 참가자를 7대7로 늘렸을 때, 기존 맵 스크립트가 P1~P8만 이동시키고 P9~P14는 원래 무작위 시작 위치에 남겨 두어 아군과 적군이 같은 본진에 겹쳐 생성되는 현상을 확인했다.

맵 내부를 다시 조사한 결과 플레이어 슬롯은 14개이고 `StartLoc` 객체는 20개다. 14개 시작 위치를 다음과 같이 확정하고 중앙에 가까운 나머지 6개 시작점은 강제 배치에서 제외했다.

```text
서쪽 P1~P7:
(28.5,11.5), (27.5,47.5), (13.5,90.5), (10.5,144.5),
(61.5,181.5), (47.5,221.5), (8.5,245.5)

동쪽 P8~P14:
(199.5,14.5), (246.5,32.5), (186.5,60.5), (200.5,129.5),
(231.5,159.5), (161.5,188.5), (237.5,240.5)
```

적용 내용:

- 동맹 루프를 P1~P14로 확장
- P1~P7 공유 시야 동맹
- P8~P14 공유 시야 동맹
- 두 진영 사이는 적대
- 14명의 시작 유닛을 서로 다른 지정 좌표로 이동
- 로비 변형을 `섬멸전 / 7 대 7 / 팀당 최대 7명`으로 변경
- 로컬 GUI를 P2~P14 내장 AI 설정으로 확장
- 기본값은 P2~P13 정예, 적 팀 P14 자원 치터, 전원 `Macro`

사용자가 수동으로 수정한 자원 배치가 들어 있는 4대4 최종본은 덮어쓰지 않고, 해당 파일을 입력으로 별도 7대7 파일을 생성했다.

```text
maps/generated/europe-melee-2-7v7-rich-50000.SC2Map
```

- 파일 크기: 2,931,237바이트
- SHA-256: `5A0BDB985E4C12996C5786F7E110A122866A7E30701C0BF6C8D57540C03829F5`
- 원본의 20개 시작 지점과 수동 자원 배치 보존
- 광물·가스 701개 관측, 전부 시작량 50,000
- 일꾼 보급 비용 0 유지

SC2 5.0.16.97425 실제 엔진에서 사람 1명과 내장 AI 13명으로 게임을 생성해 게임 루프 75까지 검사했다. P1~P14 모두 각자 지정된 본진 반경에서 시작 유닛이 확인됐으며, 서쪽 7명은 P1의 Self/Ally, 동쪽 7명은 Enemy로 확인됐다. P14에는 원본 맵의 장식성 소유 오브젝트가 다수 포함되어 전체 소유 유닛 수가 108개로 잡히지만, 실제 시작 유닛 9개는 지정된 동쪽 좌표 `(237.5,240.5)`에서 정상 확인됐다.

재생성 도구는 `tools/expand_to_7v7.cjs`다. `tools/build_team_map.cjs`, `verification/verify_team_map.py`, `app/play_local.py`도 이후 7대7 기준으로 갱신했다. `tools/fix_lobby_variant.cjs`는 기존 4대4 파일의 로비만 복구하는 도구이므로 7대7 확장에는 사용하지 않는다.

## 17. 일꾼 중앙 이동 및 랠리 위치 수정

7대7 최초 확장본은 `MeleeInitUnits()`가 무작위 시작점에 유닛을 생성한 다음 `UnitSetPosition()`으로 시작 유닛과 건물만 지정 본진으로 옮겼다. 이 방식은 유닛 좌표만 바꾸고 다음 상태는 원래 무작위 시작점에 남겼다.

- 엔진의 `PlayerStartLocation(player)`
- 내장 AI가 인식하는 주 본진 위치
- 시작 사령부·연결체·부화장의 랠리 좌표

그 결과 게임이 시작되면 내장 AI 일꾼이 원래 시작점 방향으로 일제히 이동하고 시작 건물 랠리도 중앙 쪽에 남는 문제가 발생했다. 초기 검증기는 시작 직후의 유닛 좌표만 확인했기 때문에 이 후속 명령 문제를 발견하지 못했다.

수정본은 맵의 바이너리 `MapInfo`를 분석해 P1~P14 플레이어 레코드의 `start_point`에 각 `StartLoc` 오브젝트 ID를 직접 기록한다. 기존 `sc2team_MovePlayerStart` 및 `UnitSetPosition` 코드는 완전히 제거하고, Galaxy 스크립트에는 7대7 동맹 설정만 유지했다.

최종 파일:

```text
maps/generated/europe-melee-2-7v7-rich-50000-fixed-starts.SC2Map
```

- 파일 크기: 2,931,860바이트
- SHA-256: `C9EDCBC77BBEF132085570FAC94525FD572AA0BAE1A2A9D2F0EF8693C286CD70`
- P1~P7 `start_point`: 서쪽 7개 StartLoc ID
- P8~P14 `start_point`: 동쪽 7개 StartLoc ID
- 순간이동 함수: 없음
- 로컬 런처 기본 맵: 위 수정본으로 변경

SC2 5.0.16.97425 실제 엔진 검증에서 순간이동 없이 P1~P14의 시작 유닛이 지정 본진 반경에 직접 생성됐다. 게임 루프 140에서도 AI 시작 유닛이 각 본진 반경에 남아 있었으며, P1 시작 건물 랠리 목표는 지정 시작점에서 7.4 거리로 측정되어 원래 무작위 시작점이 아닌 본진 광물 방향을 가리켰다. 자원량 50,000, 일꾼 보급 0, 서쪽/동쪽 동맹도 함께 통과했다.

재현 및 재생성 도구는 `tools/fix_player_starts.cjs`이며, 원본부터 새로 빌드할 때 사용하는 `tools/build_team_map.cjs`도 동일한 고정 시작점 방식으로 변경했다. 검증기 `verification/verify_team_map.py`에는 시작 건물과 랠리 거리 검사를 추가했다.

## 18. Battle.net 로비 팀과 종족이 섞이는 문제 수정

2026-07-15 Battle.net 로비에서 1팀을 전부 테란, 2팀을 전부 프로토스로 지정했지만 게임 안에서는 양 진영의 종족이 섞이는 현상을 확인했다. 종족 설정 자체가 바뀐 것이 아니라, 기존 맵이 내부 플레이어 번호 `P1~P7 / P8~P14`만 기준으로 시작점과 동맹을 강제하는 반면 로비 변형에는 각 슬롯이 어느 팀에 속하는지 나타내는 속성이 없었던 것이 원인이다.

로컬 Battle.net 캐시의 실제 14인 섬멸전 맵 `밀림의 왕(14인 비대칭)`의 7대7 변형을 대조했다. 정상 변형은 다음 구조를 사용한다.

```text
CategoryId=6
MaxTeamSize=7
Attribute 2000=29746 (2팀)
Attribute 2011:
  Slot 0~6  -> Team 1 (Value 21553, Index 0~6)
  Slot 7~13 -> Team 2 (Value 21554, Index 0~6)
```

기존 생성본에는 `Attribute 2011`이 전부 빠져 있었고 `CategoryId=2`가 기록돼 있었다. `tools/build_team_map.cjs`, `tools/expand_to_7v7.cjs`, `tools/fix_player_starts.cjs`를 모두 위 표준 구조로 수정했다. 따라서 로비에서 1팀에 놓인 참가자는 P1~P7 슬롯과 서쪽 시작점으로, 2팀 참가자는 P8~P14 슬롯과 동쪽 시작점으로 연결된다. 팀 사이로 참가자를 옮기면 해당 팀의 슬롯으로 이동하므로 종족 설정도 참가자와 함께 유지된다.

새 최종 게시용 파일:

```text
maps/generated/europe-melee-2-7v7-rich-50000-fixed-teams.SC2Map
```

- 파일 크기: 2,931,138바이트
- SHA-256: `DB3601B8ED55F45B76DA00DC78F510C430DDBD0F82BC9531D29F6F7B34EC4791`
- 20개 StartLoc과 P1~P14 고정 시작점 유지
- P1~P7 서쪽 / P8~P14 동쪽 유지
- 유닛 순간이동 코드 없음
- 로비 슬롯 0~6 = 1팀, 슬롯 7~13 = 2팀
- 로비 범주를 표준 섬멸전 `CategoryId=6`으로 복구
- 로컬 런처 기본 맵을 새 파일로 변경
- 검증기는 P1~P7 테란 / P8~P14 프로토스 구성도 추가 검사
- `tools/verify_team_archive.cjs`를 추가해 섬멸전 범주, 14개 팀 슬롯, 순간이동 코드 제거를 게시 전에 검사

맵 내부 검사 결과 `CategoryId=6`, 팀 슬롯 7+7, 순간이동 코드 없음이 모두 통과했고 Python/Node 구문 검사와 설정 모델 단위 테스트 5개도 통과했다. 수정된 `build_team_map.cjs`를 정확한 원본에 다시 실행한 재생성 스모크 테스트도 같은 팀 슬롯 검사에 통과했다. SC2 에디터가 띄운 기존 게임 프로세스와 API 포트 실행이 충돌하여 새 파일의 별도 엔진 검증은 기존 게임 종료 후 다시 수행해야 한다. 이전 `fixed-starts` 파일의 고정 시작점·랠리·자원·동맹 엔진 검증 결과는 그대로 유효하며, 이번 변경은 로비 Attributes와 검증용 종족 구성에 한정된다.

## 19. Changeling 연동용 1대1 전체 시야 테스트 맵

외부 ProBot 첫 연동 대상으로 VersusAI 패키지에 포함된 `changeling`을 사용하기로 결정했다. Changeling이 상황에 따라 공중 유닛을 생산하는 것은 허용하며, 이 봇에는 지상전 전용 제한을 적용하지 않는다.

Changeling의 행동을 사람이 직접 관찰할 수 있도록 기존 7대7 최종본을 입력으로 별도 1대1 테스트 맵을 생성했다. 기존 7대7 게시용 파일은 변경하지 않았다.

```text
maps/generated/europe-melee-2-Pro-Bot_test.SC2Map
```

- 한국어 맵 이름: `유럽 섬멸전 Pro Bot_test`
- 영어 맵 이름: `Europe Melee Pro Bot_test`
- 섬멸전 1대1 로비: P1과 P2만 개방
- P1 사람: 서쪽 `(10.5, 144.5)`
- P2 Pro Bot: 동쪽 `(200.5, 129.5)`
- P3~P14: MapInfo에서 `None`으로 닫음
- P1과 P2: 상호 적대
- P1만 전장 전체를 영구적으로 볼 수 있음
- P2에는 별도의 추가 시야를 제공하지 않음
- 기존의 풍부한 광물·가스 50,000과 일꾼 보급 비용 0 유지

전체 시야는 맵 스크립트에서 다음 네이티브 호출로 적용한다.

```galaxy
VisRevealArea(1, RegionEntireMap(), 0.0, false);
```

지속 시간 `0.0`은 게임 전체에 걸친 영구 공개를 의미한다. 재생성 도구는 다음과 같다.

```powershell
node tools/build_pro_bot_test_map.cjs `
  maps/generated/europe-melee-2-7v7-rich-50000-fixed-teams.SC2Map `
  maps/generated/europe-melee-2-Pro-Bot_test.SC2Map
```

검증 도구:

```powershell
.\.venv\Scripts\python.exe -u verification\verify_pro_bot_test_map.py
```

SC2 5.0.16.97425 실제 엔진에서 사람 Participant 1명과 프로토스 내장 AI 1명으로 게임 루프 102까지 검증했다. API의 안개 해제 옵션을 사용하지 않은 `disable_fog=False` 관측에서도 P1이 동쪽 P2 시작 유닛 9기를 확인했다.

```text
Human full-map vision: PASS (disable_fog=False)
1v1 fixed starts and enemy relation: PASS
Worker supply 0 and resources 50000: PASS
```

생성 파일 SHA-256:

```text
4394C09B7244B9476C6D63525E8BD6E0BC2F14334C84F6C7E9C97A5129C78C93
```

이 시점에는 맵과 내장 AI를 이용한 전체 시야 검증까지 완료했으며, 이후 실제 Changeling 연동 결과는 아래 20~21절에 이어서 기록한다.

## 20. 유럽 섬멸전 테스트 맵의 Changeling 비호환 확인

`europe-melee-2-Pro-Bot_test.SC2Map`에 실제 Changeling을 연결해 게임 참가까지는 성공했지만, 봇의 `MapAnalyzer`가 이 14인용 지형에서 램프를 분석하는 도중 종료됐다.

```text
map_analyzer.constructs.MDRamp.set_regions
IndexError: list index out of range
```

유럽 섬멸전 지형에는 Changeling이 감지한 램프 중 인접 지역이 하나도 연결되지 않는 램프가 있고, 봇에 포함된 MapAnalyzer 구현은 모든 램프에 최소 한 개의 인접 지역이 있다고 가정한다. 따라서 이 오류는 API 포트나 런처 문제가 아니라 폐쇄 배포된 Changeling 실행 파일과 해당 지형의 호환 문제다. `europe-melee-2-Pro-Bot_test.SC2Map`은 맵/전체 시야 실험 파일로 보존하지만 Changeling 전용 런처에서는 사용하지 않는다.

## 21. 사람 대 Changeling 로컬 1대1 완성

VersusAI 패키지에 포함된 공식 ProBot용 `TorchesLE.SC2Map`을 기반으로 Changeling 호환 테스트 맵을 별도로 생성했다.

```text
maps/generated/torches-le-Pro-Bot_test.SC2Map
```

- 표시 이름: `Torches LE Pro Bot_test`
- 섬멸전 1대1, 시작 위치 2개
- P1 사람에게만 전장 전체 영구 시야 제공
- 광물·가스 오브젝트 186개를 풍부한 자원으로 변환
- 광물·가스 오브젝트 186개 모두 자원량 50,000
- 일꾼(건설로봇, 탐사정, 일벌레) 보급 비용 0
- SHA-256: `6A9C0A4C92EBFB0AD03F71AB2117FDD6C725C6DF770401020E766E5F7E71D42B`

재생성 명령:

```powershell
node tools/build_changeling_test_map.cjs `
  "vendor/SC2AIApp_2025_S1/Humans vs Probots Maps/TorchesLE.SC2Map" `
  "maps/generated/torches-le-Pro-Bot_test.SC2Map"
```

전용 GUI 런처도 완성했다.

```text
start_pro_bot_test.cmd
app/play_changeling.py
```

`start_pro_bot_test.cmd`를 실행하면 P1 사람 종족과 P2 Changeling 종족을 고르는 창이 열린다. Changeling은 선택 종족에 따라 저그 Eris, 프로토스 Deimos, 테란 Phobos 로직을 사용한다. 게임 중 `runtime/changeling.log`에서 봇의 빌드 선택과 동작 로그를 확인할 수 있으며, 종료 시 수정했던 Changeling `config.yml`은 원래 내용으로 복구된다.

멀티 클라이언트 안정화 과정에서 다음 두 가지도 수정했다.

- 각 SC2 프로세스에 공식 런처와 같은 `-dataDir` 및 고유 `-tempDir` 적용
- SC2가 지원하지 않는 WebSocket 자동 ping을 비활성화

두 번째 수정 전에는 WebSocket 라이브러리가 연결 20초 후 ping 프레임을 보내면서 SC2 API 소켓이 끊겼다. 게임 생성과 맵 로딩 시간을 제외하면 게임 시작 약 12초 뒤 끊기는 현상으로 보였다. 수정 후 다음 검증을 통과했다.

```text
일반 API 참가자 2명: 30초 유지, 게임 루프 585
P1 사람(테란) vs P2 Changeling(무작위): 30초 유지
P1 전체 시야에서 Changeling 소유 유닛 14기 관측
Changeling 로그에서 HatchPoolHatchGas 빌드와 첫 Overlord 생산 확인
```

CLI 재검증 명령:

```powershell
.\.venv\Scripts\python.exe -u app\play_changeling.py `
  --cli --human-race Terran --bot-race Random --test-seconds 30
```

이 구성은 로컬 SC2 API 전용이다. 맵 자체는 Battle.net에 게시할 수 있지만 `changeling.exe`와 로컬 런처는 Battle.net 커스텀 게임 안에서 실행되지 않는다. Battle.net 게시본에서는 사람과 스타크래프트 II 내장 AI만 사용할 수 있다.

## 22. Changeling 테란·프로토스 및 일꾼 인구 0 호환 수정

최초 연동본에서는 저그 Eris만 정상적으로 빌드를 수행하고 프로토스 Deimos와 테란 Phobos는 일꾼 생산 이후 정지하거나 일부 건물만 반복해서 시도했다. 조사 결과 하나의 문제가 아니라 다음 호환 문제가 겹쳐 있었다.

1. 통합 `changeling.exe`가 Deimos/Phobos 클래스로 전환하기 전에 Ares 기본 관리자를 먼저 초기화했다.
2. Torches 원본은 8일꾼 시작이지만 현재 Changeling 빌드는 12일꾼 시작을 전제로 한다.
3. 맵의 일꾼 보급 비용 0 때문에 API의 `food_used`가 일꾼 수를 포함하지 않았다.
4. 이 맵의 연결체는 구형 보급량 13을 사용하지만 Deimos는 현대식 연결체 보급량 15와 첫 파일런 14 타이밍을 전제로 한다.
5. 꿀가스 건물은 일반 건물이 아니라 `RefineryRich=1943`, `AssimilatorRich=1994`, `ExtractorRich=1995`로 생성된다. 봇의 빌드 완료 검사는 일반 건물 ID만 인식했다.
6. 꿀광 수입으로 광물 950에 일찍 도달하면 Deimos의 비정상 빌드 탈출 조건이 정상 오프닝을 강제 종료했다.

적용한 수정:

- 원본 `changeling.exe`는 보존하고 `changeling-fixed.exe`를 생성했다.
- 종족 전환 후 Deimos/Phobos 전용 관리자를 초기화하도록 실행 파일의 `bot.main`을 수정했다.
- Deimos의 광물 950 오프닝 중단 조건을 꿀광 환경에서 발동하지 않도록 수정했다.
- 게임 참가 직후 양쪽의 시작 일꾼을 12기까지 보충한다.
- `sc2team/worker_supply_proxy.py`가 Changeling에게 전달되는 관측에만 실제 일꾼 수를 사용 인구로 더한다.
- 완성된 연결체마다 봇에게 보이는 최대 인구에 2를 더해 구형 13을 현대식 15로 보정한다.
- 봇에게 보이는 풍부한 가스 건물 ID를 일반 정제소·동화소·추출장 ID로 변환한다.
- 실제 맵의 일꾼 인구 0, 꿀광, 꿀가스, 자원량 50,000은 변경하지 않았다.

실행 파일 재생성 도구:

```powershell
.\.venv\Scripts\python.exe tools\patch_changeling.py
```

현재 런처가 사용하는 실행 파일:

```text
vendor/SC2AIApp_2025_S1/SC2AIApp_2025_S1/Bots/changeling/changeling-fixed.exe
SHA-256: EB32EB2A87BBD06C6E26933895FD2F6ABE13AB5A619ECD3E02BFF5D3F71EB156
```

SC2 5.0.16.97425 실제 엔진 검증 결과:

```text
프로토스 105초:
  프로브 21, 연결체 1, 파일런 2, 관문 1, 인공제어소 1,
  풍부한 동화소 2
  빌드 로그: 파일런 -> 관문 -> 시간 증폭 -> 동화소 -> 일꾼 정찰

테란 80초:
  SCV 14, 사령부 2, 병영 1, 내려간 보급고 1,
  풍부한 정제소 1
```

보급 계측에서는 프로토스의 실제 `food_used=0`이 봇에게 `21`로 보정되고, 실제 연결체+파일런 최대 인구 `21`이 봇에게 현대식 `23`으로 전달되는 것을 확인했다. 단위 테스트 `tests/test_worker_supply_proxy.py` 2개도 통과했다. `--test-seconds` 검증 종료 시 나타나는 Changeling의 연결 종료 traceback은 제한 시간이 끝나 런처가 테스트용 SC2를 의도적으로 닫은 뒤 발생하는 종료 로그이며 게임 중 크래시가 아니다.

## 23. 외부 ProBot 다대다 실험 종료와 구조 변경

Changeling을 2대2로 직접 참가시키는 실험에서 SC2 엔진이 게임 생성을 다음 오류로
거부했다.

```text
Only 1v1 is supported when using multiple agents
```

외부 API Participant 4명뿐 아니라 Participant 2명과 Computer 2명의 조합도 같은
제한에 걸렸다. 반면 Participant 1명과 Computer 3명은 정상적으로 생성됐다. 따라서
외부 ProBot 프로세스를 여러 개 붙이는 `app/play_changeling_2v2.py` 방식은 최종 구조로
사용하지 않는다.

확정한 로컬 다대다 구조는 다음과 같다.

1. 사람 한 명만 SC2 API Participant로 참가한다.
2. P1~P14 중 선택한 나머지 AI 슬롯은 맵 내부 Computer 플레이어로 만든다.
3. 실행 맵에서는 `MeleeInitAI()`를 제거해 Blizzard 내장 AI를 시작하지 않는다.
4. 로컬 Python 전략 제어기가 맵/Galaxy 명령 브리지를 통해 각 AI를 독립 제어한다.

전략 명령 브리지는 아직 완성되지 않았다. `RequestMapCommand`는 프로토콜에 구현했지만
Galaxy 함수 이름만 추가한 맵에서는 `Doesn't exist in current map`으로 거부됐다.
에디터의 외부 호출 가능 트리거 메타데이터를 등록하거나 동등한 브리지를 구현해야 한다.

