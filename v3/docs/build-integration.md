# V3 빌드 통합

`build_v3_map()`은 공통 빌더로 임시 맵을 만든 뒤 plan을 사용해 V3 mod와 맵을
함께 만든다.

1. `build_v3_ai_mod.cjs`가 upstream manifest의 54개 SHA-256을 검증한다.
2. 종족 root 세 곳에 V3 include와 Open/Mid/Late dispatcher를 생성한다.
3. overlay manifest의 V3 파일 9개를 검증하여 mod에 패키징한다.
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
