# 확장 중복·좌표 강제 배치 적대적 검증 프롬프트

당신은 이 프로젝트의 구현자를 신뢰하지 않는 독립 검증자다. 아래 주장들을 코드 문자열만 보고 통과시키지 말고, 맵 아카이브의 실제 `MapScript.galaxy`, SC2 엔진 컴파일, 장시간 실게임 관측 데이터로 반증을 시도하라. 실패를 발견하면 원인을 특정하고 최소 수정한 뒤 반드시 릴리스 맵까지 다시 빌드하고 같은 검증을 반복하라.

작업 경로:

`C:\Users\cbkjh\OneDrive\바탕 화면\M\Play\startcraft2`

현재 문제 상황:

- 커스텀 확장 트리거가 이미 타운홀이 있는 같은 장소 주변에 연결체/사령부/해처리를 계속 추가했다.
- 과거 구현은 `AIExpand(player, requestedPoint, townHallType)`에 좌표를 넘겼지만, 밀리 AI가 그 좌표를 강제점으로 사용하지 않고 기존 안전지대 주변에 지어도 전체 타운홀 수 증가만 보고 성공 처리했다.
- 그 결과 한 자원기지에 같은 플레이어의 타운홀이 여러 채 둘러서고, 정작 광물·가스 후보는 점유되지 않았다.
- Voronoi식 후보 귀속 검사만으로는 이 현상을 막지 못했다.

현재 구현자가 주장하는 수정:

- `tools/build/production.cjs`에서 확장 배치를 `AIExpand`에 위임하지 않는다.
- `sc2team_TryBuildExpansionAt`이 SCV/Probe/Drone에 각각 `TerranBuild/ProtossBuild/ZergBuild` command 0을 사용해 검증 후보 좌표에 직접 본진 건설 명령을 내린다.
- 후보를 선택할 때 `gv_sc2team_ExpansionRequestedCandidate[player]`에 후보 ID를 저장한다.
- 단순 타운홀 수 증가가 아니라 `sc2team_ExpansionCandidateOwnedByPlayer(requestedCandidate, player)`가 참이고 완성 타운홀 수가 증가해야 성공 처리한다.
- 어떤 타운홀이든 후보 중심 14 이내에 있으면 해당 후보는 닫힌다.
- 직접 명령을 받은 일꾼은 custom value 22로 추적하며, 명령 종료 또는 180초 만료 시 script-controlled 상태가 해제된다.
- `AIExpand`와 `AISetStockExpand`는 생성된 확장 제어 코드에 없어야 한다.

반드시 먼저 읽을 파일:

- `HANDOFF.md`와 최신 관련 문서
- `tools/build/production.cjs`
- `tools/build/verify.cjs`
- `tools/build/expansion-layout.json`
- `verification/analyze_expansion_layout.py`
- `runtime/custom_ai_settings.json`

적대적 검증 요구사항:

1. 현재 작업 트리의 사용자 변경을 보존하고, 관련 diff를 먼저 파악하라.
2. 생성된 Galaxy에서 세 종족 직접 건설 command index 0이 실제 데이터/엔진에서 올바른 본진 건설 명령인지 확인하라. 문자열 존재만으로 통과시키지 마라.
3. 릴리스 맵 내부 `MapScript.galaxy`를 직접 추출해 다음을 확인하라.
   - 확장 경로에 `AIExpand`와 `AISetStockExpand`가 없음
   - 요청 후보 ID 저장, 후보 실제 점유 성공 판정, 14 거리 중복 차단이 모두 있음
   - 밀리 AI가 켜진 운영 빌드이며 `strategy_bridge=true`, `campaign_units_pilot=true`, `wild_zerg=false` 조건으로 빌드됨
4. SC2가 사용 중이면 기존 세션을 종료하거나 방해하지 말고 사용자에게 알린 뒤 기다려라. 사용 가능할 때 엔진 로드/컴파일 검증을 수행하라.
5. 사용자 참여 1명 + AI 12명, 7 대 6 조건으로 최소 20게임분 실시간 실행하라. 사람은 움직이지 않는다. 야생 저그는 비활성화한다.
6. 최소 10초 간격으로 모든 플레이어의 타운홀에 대해 다음을 기록하라.
   - 생성/완성 시각, 플레이어, 종족, 실제 `(x,y)`
   - 가장 가까운 확장 후보 ID와 거리
   - 동일 플레이어의 다른 타운홀과의 최소 거리
   - 해당 후보의 광물/가스 및 지형 높이 관계
7. 다음 실패 조건을 자동 판정하라.
   - 같은 플레이어가 같은 후보에 타운홀 2채 이상 보유
   - 시작 선배치 예외를 제외하고 타운홀 중심 간 거리 14 미만
   - 직접 요청된 후보에서 실제 건설점이 유의미하게 벗어남
   - 건설 실패 후 같은 빈 땅/기존 기지 주변에 반복 발주
   - 확장 일꾼이 180초 뒤에도 영구 script-controlled 또는 멈춤 상태
   - 지상 도달 가능한 정상 후보가 있는데 7분까지 2기지 미만, 12분까지 3기지 미만
   - 연결체/사령부/해처리 중 한 종족만 작동하거나 Zerg Drone 소비 후 pending 상태가 깨짐
8. 가까운 별도 자원기지, 서로 다른 언덕, 지상 도달 불가 언덕/섬 후보를 따로 공격하라. 14 차단이 정당한 두 기지를 하나로 오인하지 않는지, 직접 일꾼 명령이 수송이 필요한 후보에서 영구 정지하지 않는지 확인하라.
9. 카메라 스크린샷과 좌표 로그를 `runtime/reports/`에 남겨라. 성공 사례만 고르지 말고 모든 중복/실패 후보를 포함하라.
10. 정적 검증, 맵 빌드, 엔진 컴파일, 실게임 계측 결과를 각각 PASS/FAIL로 분리해서 보고하라. 엔진을 실제로 돌리지 않았다면 절대 “검증 완료”라고 하지 마라.

릴리스 빌드는 단독 Node 빌더 기본값으로 만들지 마라. 저장 JSON에는 `strategy_bridge`가 없어서 그 방식은 밀리 AI를 꺼버릴 수 있다. 기존 Python 래퍼 `sc2team.custom_runtime.build_runtime_map(...)`를 사용해 명시적으로 `strategy_bridge=True`, `campaign_units_pilot=True`를 전달하고, 출력은 다음 릴리스 맵에 적용하라.

`runtime/maps/europe-melee-custom-ai-v1.25.0.SC2Map`

최종 보고에는 재현 여부, 정확한 원인, 변경 파일, 릴리스 SHA-256, 각 검증 명령과 결과, 남은 위험을 포함하라. 구현자의 설명과 검증기가 같은 잘못된 가정을 공유할 수 있으므로, 기존 `verify.cjs` 통과만으로 결론내리지 마라.

## SC2 고속 계측 방식 — 반드시 준수

“20게임분 계측이 20분 동안 화면을 점유한다”는 전제는 틀렸다. 이 저장소의 프로토콜 계측은 실시간 관전이 아니라 SC2 API의 비실시간 step 모드로 돌린다.

- `create_game_with_setups(..., realtime=False)`를 사용하라.
- `realtime=True`, `time.sleep`, UI 게임 속도 버튼, 사람이 화면을 보며 기다리는 방식은 사용하지 마라.
- `await connection.step(224)`는 22.4 loop/s 기준 게임 시간 10초를 한 번에 진행한다. 관측과 `StrategyController.update(observation)`는 각 step 뒤에 호출한다.
- 20게임분 종료 loop는 `int(20 * 60 * GAME_LOOPS_PER_SECOND)`다. 벽시계 20분이 아니라 엔진이 허용하는 최대 속도로 진행되므로 일반적으로 훨씬 빨리 끝난다. 사용자가 말하는 “20배속”은 별도 UI 배속이 아니라 이 `realtime=False` + API step 실행을 뜻한다.
- 창은 뜰 수 있지만 계측은 API가 자동 진행한다. 화면을 사람이 계속 점유하거나 관찰할 필요가 없다. `fullscreen=False`로 만들고 백그라운드에서 좌표 로그를 수집하라.
- 기존 구현 예시는 `verification/verify_expansion_7v6.py`와 `verification/verify_expansion_coordinates.py`다. 둘 다 이미 `realtime=False`와 `connection.step(224)`를 사용한다.
- 전체 적대적 좌표 계측을 붙인 뒤 20게임분 실행하라. 단순히 8분 실시간 실행으로 축소하지 마라.

기본 실행 형태:

`.venv\Scripts\python.exe verification\verify_expansion_coordinates.py 20`

단, 현재 스크립트의 단순 거리 검사만으로 끝내지 말고 위 요구사항의 후보별 중복, 동일 플레이어 타운홀 간 최소 거리, 생성 시각, 실제 요청 후보, 일꾼 정지 여부를 먼저 계측하도록 확장한 다음 실행하라.
