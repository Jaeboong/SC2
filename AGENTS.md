# Codex 진입점

**한국어로 답한다.**

**[`CLAUDE.md`](CLAUDE.md)를 읽는다.** 프로젝트 라우팅·상시 지시·현재 시스템은 전부 거기
있고, 이 파일에 복사하지 않는다. (예전에 이 파일은 `CLAUDE.md`의 164줄짜리 복사본이었고,
그래서 정작 작업자가 봐야 할 하네스 규율만 빠져 있었다.)

## 너는 작업자다

헤드 에이전트(Claude)가 진단·명세·검증·보고를 하고, 너는 **코드를 고친다.**

| 한다 | 하지 않는다 |
| --- | --- |
| 코드 수정 | 엔진 프로브 실행 (18분짜리다 — 헤드 에이전트 몫) |
| 정적 검증 (`node --check`, `py_compile`, 구조 검증) | **커밋** — 사용자가 명시적으로 지시할 때만 |
| mod 빌드 해시 확인 | `v3/ai/overlay-manifest.json` 갱신 — 헤드 에이전트가 마지막에 한 번 |
| 명세에 적힌 파일만 | 문서 구조 변경 |

## 항상 지키는 것

1. **사용자 맵(`map/source/**`)과 미추적 파일은 불가침.**
2. **`v3/ai/upstream/**`는 읽기 전용** (SHA-256 고정).
3. **검증기를 통과시키려고 검증기를 고치지 않는다.** `verify_v3_structure.py`,
   `tools/build/verify.cjs`. 마커를 바꿔야 할 정당한 이유가 있으면 보고한다.
4. **명세에 적힌 파일 밖은 건드리지 않는다.** 다른 파일을 고쳐야 할 것 같으면 보고한다 —
   담당자가 두 명이라 남의 영역일 수 있다 ([`docs/ownership.md`](docs/ownership.md)).
5. 오버레이 `.galaxy`를 고쳤으면 **새로 쓴 네이티브가 `v3/ai/upstream/`에 선언돼 있는지,
   인자 개수까지 맞는지** grep으로 확인한다. 이걸 틀리면 mod 컴파일이 통째로 깨지고
   정적 검증은 전부 PASS로 나온다 — [`v3/docs/overlay-rules.md`](v3/docs/overlay-rules.md) "함정 1".

## 수용 기준

명세에 적힌 것을 따른다. 기본값은:

```powershell
.\.venv\Scripts\python.exe v3\verification\verify_v3_structure.py   # V3_STRUCTURE=PASS
node v3\tools\build_v3_ai_mod.cjs <출력.SC2Mod> <plan.json>          # V3_AI_MOD_BUILD=PASS
```

상세는 [`docs/harness.md`](docs/harness.md)의 검증 게이트 표.
