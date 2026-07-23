# V3 빌드 통합

`build_v3_map()`은 공통 빌더로 임시 맵을 만든 뒤 plan을 사용해 V3 mod와 맵을
함께 만든다.

1. `build_v3_ai_mod.cjs`가 upstream manifest의 54개 SHA-256을 검증한다.
2. 종족 root 세 곳에 V3 include와 Open/Mid/Late dispatcher를 생성한다.
3. overlay manifest의 V3 파일 10개를 검증하여 mod에 패키징한다.
4. `patch_v3_ai.cjs`가 맵에 mod dependency와 build ID 142를 삽입한다.
5. 성공한 맵·mod·plan만 최종 경로로 원자적으로 승격한다.

출력은 `.SC2Map`, `SC2TeamV3AI.SC2Mod`, 재현용 `.v3plan.json`이다. 맵의
`DocumentInfo`와 `DocumentHeader`에는 `file:Mods/SC2TeamV3AI.SC2Mod` dependency가
한 번만 들어간다. 런처는 게임 시작 전에 mod를 SC2 데이터 폴더에 설치한다.

런처는 완성된 맵 바이트로 게임을 만들고 Participant 또는 Observer로 접속한다.
그 이후 Python/Node가 AI 명령을 보내는 경로는 없다.

검증 명령:

```powershell
node --check v3/tools/build_v3_ai_mod.cjs
node --check v3/tools/patch_v3_ai.cjs
.\.venv\Scripts\python.exe -m py_compile v3/sc2team_v3/runtime.py app/play_custom_ai_v3.py
.\.venv\Scripts\python.exe v3/verification/verify_v3_structure.py
.\.venv\Scripts\python.exe v3/verification/probe_v3_ground_builds.py --duration 540
```

## 함정: 오버레이 galaxy의 네이티브 스코프는 map galaxy와 다르다

**V3 AI mod 오버레이(`overlay/Base.SC2Data/TriggerLibs/V3/*.galaxy`)가 컴파일되는
include 컨텍스트는 런타임 map galaxy(`tools/galaxy/*.galaxy`)와 다르다.** map galaxy에
있는 일반 트리거 네이티브가 AI mod에는 **미정의**일 수 있고, 그런 심볼을 오버레이에서
참조하면 **V3 mod galaxy 전체 컴파일이 깨진다**. 이 커스텀 맵은 mod dependency에
의존하므로, mod가 안 뜨면 **로비 플레이어 1~N이 시작 유닛도 없이 스폰 실패한다**
(관전 시 owner 15=야생저그·16=중립만 남고 1~N은 유닛 0).

- **실제 사례 (2026-07-24):** 302 직접-테크 함수에 컴파일 깨는 galaxy 이슈가 **둘**
  동시에 있어 모든 미러 프로브가 플레이어 0으로 실패했다. 하나를 고쳐도 나머지가
  남아 계속 깨졌다:
  1. `PointWithOffsetPolar`(map galaxy P15 코드엔 있음) 사용 — 이 네이티브는 다른
     오버레이 0번 사용 + `v3/ai/upstream/`에 정의 없음.
  2. 전역 배열을 C 스타일 `fixed gv_x[16];`로 선언 — Galaxy는 **`fixed[16] gv_x;`**
     (`type[size] name`) 구문만 허용한다. 관례는 HomeDefense.galaxy의
     `fixed[16] gv_v3HomeDefenseNextOrder;` 참고.
- **배치점 계산이 필요하면** map 전용 `PointWithOffsetPolar` 대신 AI 네이티브
  **`AIGetBuildingPlacement(player, center, aliasUnitType, c_makeNoFlags)`** 를 쓴다
  (upstream `AI.galaxy` 선언, 컴파일 안전, melee AI 자체 배치 로직).
- **전역 배열은 `type[size] name;`** 구문으로 선언한다 (C 스타일 `type name[size];` 금지).
- **오버레이에 네이티브를 새로 추가하기 전** 그게 다른 오버레이에서 이미 쓰이는지,
  또는 `v3/ai/upstream/`에 선언돼 있는지 grep으로 먼저 확인한다. "map galaxy(P15)에서
  됐으니 오버레이에서도 된다"는 가정은 금물.

### 이 컴파일 에러는 구조 검증으로 안 잡힌다 — 진단법

`verify_v3_structure.py`와 `build_v3_ai_mod.cjs`는 파일 목록·SHA-256·주입 구조만
검사하므로 **galaxy 컴파일 에러를 못 잡는다**(둘 다 PASS로 나온다). 프로브의
`GROUND_COMPILE=PASS`도 "맵 로드 + 카탈로그 읽힘"만 뜻하지 트리거 컴파일 성공을
보장하지 않는다. SC2 galaxy 에러 로그도 이 환경에는 남지 않는다.

- **격리 진단:** `probe_v3_ground_builds.py --upstream-timing`(V3 mod을 설치하지 않고
  블리자드 순정 AI로 같은 맵 구동). 이게 **정상 스폰이면 범인은 V3 mod**, 여전히
  플레이어 0이면 맵/환경 문제다. 5초 시점 `RAW_OWNERS` 한 줄로 판별된다.
