# Claude 진입점

**한국어로 답한다.**

이 파일은 라우터다. 규율 본문을 여기 넣지 않는다.

## 시작하기 전에

1. [`docs/HANDOFF.md`](docs/HANDOFF.md) — 현재 상태와 열린 항목
2. [`docs/harness.md`](docs/harness.md) — 내 역할, Codex 위임 규약, 검증 게이트, 진단 규율
3. 아래 라우팅 표에서 이번 작업에 해당하는 규율 문서

## 상시 지시

**우리 계층은 보조(補助)이고 블리자드 멜리 AI가 주(主)다.** 우리 코드가 하는 일은 셋뿐이다 —
산출을 끌어올리고, 설정된 빌드로 유도하고, 특정 유닛을 금지한다. 멜리 AI가 실제로 내리는
결정을 뺏는 것은 범위 밖이며 사용자 승인이 필요하다.

**게임 동작을 바꾸는 진단은 수정 전에 먼저 보고하고 동의를 받는다.**

## 현재 시스템

| | |
| --- | --- |
| 플레이 대상 | **V3 임베디드 AI mod** (`v3/ai/overlay` → `SC2TeamV3AI.SC2Mod`) |
| 버전 | 앱 `3.2.0` / AI `V3.16` |
| 진입점 | `start_custom_ai_v3.cmd` → `app/play_custom_ai_v3.py` → `v3/sc2team_v3/` |
| 맵 선택 | 런처가 `map/source/*.SC2Map` 을 훑어 고른다. 프리뷰는 `map/img/<맵이름>/` |
| 기본 맵 | `map/source/europe-melee-2-7v7-rich-50000-fixed-teams.SC2Map` |
| 생성 산출물 | `runtime/maps/v3-<맵이름>.SC2Map`, `runtime/mods/SC2TeamV3AI.SC2Mod`, `.v3plan.json` |
| 작업 로그 | [`v3/docs/status.md`](v3/docs/status.md) |

V3는 자체 맵 빌더가 없다. `build_runtime_map(..., melee_only=True)`로 V1의 맵 계층을 그대로
쓴다. 그래서 맵·MapInfo·보급·캠페인 데이터 규율은 **V3에도 적용된다.**

**V1 런처(`start_custom_ai.cmd`)의 AI 계층은 현재 플레이에 쓰이지 않는다.** 그 규율은
[`docs/history/v1-ai-rules.md`](docs/history/v1-ai-rules.md)에 보존돼 있다.

## 라우팅

| 무엇을 하려는가 | 문서 |
| --- | --- |
| 역할·위임·검증 게이트·진단 규율 | [`docs/harness.md`](docs/harness.md) |
| 담당자 두 명의 소유 경계와 공유 자산 | [`docs/ownership.md`](docs/ownership.md) |
| 커스텀 AI 슬롯(테란/프로토스/저그 6빌드) 수정 | [`v3/docs/overlay-rules.md`](v3/docs/overlay-rules.md) |
| 야생 저그(P15, build 315) 수정 | [`v3/docs/wild-zerg.md`](v3/docs/wild-zerg.md) |
| 맵·MapInfo·슬롯·보급·캠페인 유닛 카탈로그 | [`docs/rules/map-layer.md`](docs/rules/map-layer.md) |
| V3 실행 흐름과 데이터 계약 | [`v3/docs/architecture.md`](v3/docs/architecture.md) |
| V3 빌드 파이프라인 | [`v3/docs/build-integration.md`](v3/docs/build-integration.md) |
| 업스트림 AI 호출 흐름 | [`v3/docs/upstream-ai-call-flow.md`](v3/docs/upstream-ai-call-flow.md) |
| 이미 반증된 접근을 다시 시도하지 않기 | [`docs/decisions/known-constraints.md`](docs/decisions/known-constraints.md) |
| 테스트 tier 고르기 | [`docs/verify/verification-guide.md`](docs/verify/verification-guide.md) |
| 설치·실행·문제 해결 | [`docs/operations/local-runbook.md`](docs/operations/local-runbook.md) |
| 전체 문서 색인 | [`docs/README.md`](docs/README.md) |

## 최소 검증

`.galaxy`를 한 줄이라도 고쳤으면 **6분 스모크 프로브가 필수다.** 정적 검증 4종은 galaxy
컴파일 에러를 하나도 잡지 못하고, 그 상태로 전 슬롯이 죽은 사례가 두 번 있었다.
게이트 전체는 [`docs/harness.md`](docs/harness.md).
