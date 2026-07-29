# 문서 색인

목적별로 나눠져 있다. 새 담당자가 연대기 작업 로그를 읽고 현재 동작을 추론하지 않아도 되게.

진입점은 [`../CLAUDE.md`](../CLAUDE.md)(Claude) / [`../AGENTS.md`](../AGENTS.md)(Codex)다.

## 권위 순서

문서끼리 어긋나면 이 순서를 따른다.

1. 실행되는 소스와 테스트
2. [`HANDOFF.md`](HANDOFF.md) — 현재 상태
3. 아래 영역 문서
4. `README.md` — 사용자용 일반 정보
5. 작업 로그 — [`../v3/docs/status.md`](../v3/docs/status.md)(V3), [`latest_status.md`](latest_status.md)(V1 §58+), [`history/`](history/)(그 이전)

작업 로그는 실패한 시도와 폐기된 주장을 일부러 남겨둔다. 가장 최근 섹션이 이기지만,
현재 동작은 언제나 코드가 authoritative다.

## 하네스

| 문서 | 언제 |
| --- | --- |
| [`harness.md`](harness.md) | 역할 분담, Codex 위임 규약, 검증 게이트, 진단 규율 |
| [`ownership.md`](ownership.md) | 커스텀 AI 담당 / 야생 저그 담당의 소유 경계와 공유 자산 |
| [`handoff/custom-ai-agent.md`](handoff/custom-ai-agent.md) | 커스텀 AI 담당 에이전트에게 넘길 핸드오프 프롬프트 |
| [`handoff/wild-zerg-agent.md`](handoff/wild-zerg-agent.md) | 야생 저그 담당 에이전트에게 넘길 핸드오프 프롬프트 |

## 현재 시스템 (V3)

| 문서 | 언제 |
| --- | --- |
| [`../v3/docs/overlay-rules.md`](../v3/docs/overlay-rules.md) | 커스텀 AI 슬롯 6빌드를 고칠 때 |
| [`../v3/docs/wild-zerg.md`](../v3/docs/wild-zerg.md) | 야생 저그(P15, build 315)를 고칠 때 |
| [`../v3/docs/architecture.md`](../v3/docs/architecture.md) | V3 실행 흐름과 데이터 계약 |
| [`../v3/docs/build-integration.md`](../v3/docs/build-integration.md) | mod/맵 빌드 파이프라인 |
| [`../v3/docs/upstream-ai-call-flow.md`](../v3/docs/upstream-ai-call-flow.md) | 블리자드 멜리 AI 호출 흐름 |
| [`../v3/docs/references.md`](../v3/docs/references.md) | 업스트림 소스 참조 |
| [`../v3/docs/status.md`](../v3/docs/status.md) | V3 작업 로그 |

## 공용 계층

| 문서 | 언제 |
| --- | --- |
| [`rules/map-layer.md`](rules/map-layer.md) | 맵, MapInfo, 슬롯, 팀, 보급 상한, 캠페인 유닛 카탈로그 (**V3도 적용**) |
| [`decisions/known-constraints.md`](decisions/known-constraints.md) | 이미 반증된 접근을 다시 시도하지 않기 |
| [`verify/verification-guide.md`](verify/verification-guide.md) | 테스트 tier 고르기 |
| [`verify/engine-tests.md`](verify/engine-tests.md) | 가속 SC2 테스트와 그 한계 |
| [`operations/local-runbook.md`](operations/local-runbook.md) | 설치, 실행, 중지, 문제 해결 |
| [`modify/campaign-units.md`](modify/campaign-units.md) | 캠페인 유닛·프로토스 종족 프리셋 추가·밸런스 |

## 비활성 (V1)

V1 런처(`start_custom_ai.cmd`)의 **AI 계층은 현재 플레이에 쓰이지 않는다.** 맵 빌더 계층은
V3가 계속 쓰므로 위 `rules/map-layer.md`에 있다.

| 문서 | 내용 |
| --- | --- |
| [`history/v1-ai-rules.md`](history/v1-ai-rules.md) | V1 MapScript AI 규율 전체 (§60–§104) |
| [`architecture/system-overview.md`](architecture/system-overview.md) | V1 시스템 구조 (외부 컨트롤러·비콘 브릿지) |
| [`modify/runtime-map.md`](modify/runtime-map.md) | V1 런타임 맵 수정 절차 |
| [`modify/strategy-controller.md`](modify/strategy-controller.md) | V1 Python 전략 컨트롤러 |
| [`latest_status.md`](latest_status.md) | V1 작업 로그 §58–§108 |
| [`history/`](history/) | §1–57 및 버전별 아카이브 |
| [`audit/`](audit/), [`reference/`](reference/) | 단발 감사·설계 문서 |

## 문서 유지 규칙

- **복사하지 않는다.** 같은 내용이 두 파일에 있으면 반드시 어긋난다. 한 곳에 두고 링크한다.
- 진입점(`CLAUDE.md`/`AGENTS.md`)은 라우터다. 규율 본문을 넣지 않는다.
- 지속되는 설계·절차는 해당 영역 문서에, 실험과 엔진 증거는 작업 로그에 **덧붙인다**.
- 문서를 옮기면 `.\.venv\Scripts\python.exe verification\check_doc_links.py`를 돌린다
  (오프라인 tier 포함). 진입점이 없는 파일을 가리킨 적이 있다.
- 새 버전을 낼 때는 Python 앱 버전, CJS 로컬라이즈 맵 이름, 출력 파일명, 핸드오프, 사용자
  문서를 같이 갱신한다.
