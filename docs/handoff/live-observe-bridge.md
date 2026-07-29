# 핸드오프 — 라이브 관측 브리지 (Live Observe Bridge)

발신 세션 `startcraft2/fb10399d` → 수신 세션 `startcraft2/f63c3229`
작성일 2026-07-26. 브랜치 `agent/v3-custom-ai-expansion-fix`.

---

## 1. 무엇을 만드는가

사용자가 **런처로 직접 플레이 중인 SC2 게임**에, 에이전트가 실시간으로 붙어서
관측할 수 있게 하는 채널.

사용 시나리오는 이렇게 굴러가야 한다.

> 사용자: "지금이야. 지금 P8 본진에 있는 저글링 몇 기가 패널이 고장났어."
> 에이전트: (그 즉시 라이브 게임을 조회) "P8 본진 좌표 근처 저글링 34기 중
>            9기가 X 필드가 다릅니다. 총 유닛 3128, 게임시간 21분 40초."

즉 **사용자가 눈으로 본 것을 말하는 순간, 에이전트가 같은 시점의 수치를 뜬다.**

---

## 2. 왜 필요한가 — 이게 지금 유일한 길이다

추적 중인 버그가 있다. 장시간 6v6 + 야생저그 플레이에서 **유닛 패널이 비고
공격도 못 하는 유닛**이 나타난다. 불곰·시즈탱크·SCV·프로브·드론·저글링·바퀴 —
세 종족의 순정 유닛 전반에 걸쳐 나타났다.

지금까지 기각된 가설 두 개:

| 가설 | 기각 근거 |
| --- | --- |
| 캠페인 로스터 데이터 결함 | 증상 유닛이 전부 우리가 안 건드린 블리자드 순정 유닛 |
| 맵 유닛 수 천장(≈4700) 초과 | 천장에 도달해도 생성이 거부될 뿐, 기존 유닛은 멀쩡. 게다가 실플레이 총량이 천장보다 훨씬 낮음 |

**그리고 결정적으로 — 이 증상은 raw observation으로 볼 수 없다.**
패널·초상화·명령카드는 액터(actor)/UI 계층이고, `raw_data.units`에는 시뮬레이션
필드(`health_max`, `radius`, `unit_type` 등)만 담긴다. 액터가 통째로 날아가도
raw는 정상으로 보인다. 실제로 앞선 세션이 천장 프로브로 3773기를 검사해
"멀쩡하다"고 결론냈는데, **그건 증상을 검출할 수 없는 방법으로 본 것이었다.**

헤드리스 프로브로는 재현도 관측도 안 된다. 사람이 플레이하다가 증상을 보는
그 순간에 붙는 것 말고는 방법이 없다. 그래서 이 브리지가 필요하다.

---

## 3. 현재 구조 — 코드 읽어서 확인한 사실

### 런처 실행 경로

```
start_custom_ai_v3.cmd
  → app/play_custom_ai_v3.py         (tkinter GUI, APP_VERSION 3.2.0)
      PORT = 14180                    (app/play_custom_ai_v3.py:50)
      run_v3_game()                   (app/play_custom_ai_v3.py:91)
```

`run_v3_game()`이 하는 일 (`app/play_custom_ai_v3.py:106-166`):

1. `build_v3_map(...)` — 맵 + `SC2TeamV3AI.SC2Mod` 빌드
2. `install_v3_mod(...)` — SC2 데이터 폴더에 mod 설치
3. `launch_sc2(executable, PORT, 0, width=1280, height=720, fullscreen=...)`
4. `Sc2Connection.open(PORT)` — **런처가 API 연결을 잡는다**
5. `create_game_with_setups(..., realtime=True)`
6. `join_game(...)` — 사람 슬롯으로 참가. 또는 옵저버 모드면 `join_as_observer()`
7. 폴링 루프:
   ```python
   while not cancel_event.is_set() and process.poll() is None:
       observation = await connection.observation(disable_fog=True)
       if observation.player_result:
           return "V3 게임이 종료되었습니다."
       await asyncio.sleep(1.0)
   ```

**이 루프가 이미 1초마다 전체 관측을 뜨고 있고 그냥 버린다.** `disable_fog=True`도
이미 켜져 있어서 전 플레이어가 보인다. 브리지가 붙을 자리가 이미 있는 셈이다.

### SC2 프로세스 인자 (`sc2team/process.py:41-53`)

```
-listen 127.0.0.1  -port <PORT>  -dataDir ...  -tempDir ...  -displayMode 0|1
```

### 조인 시 인터페이스 옵션 (`sc2team/protocol.py:212-217`)

```python
options = sc_pb.InterfaceOptions(
    raw=True,
    score=True,
    show_cloaked=True,
    show_burrowed_shadows=True,
)
```

**`feature_layer`도 `render`도 꺼져 있다.** 이게 뒤에 나오는 핵심 제약이다.

---

## 4. 핵심 제약 — 별도 프로세스로 "붙는" 건 아마 안 된다

SC2의 `-listen/-port`는 `ws://127.0.0.1:14180/sc2api` 웹소켓 하나를 연다.
**런처가 이미 그 연결을 점유하고 게임에 참가(join)한 상태다.**

내 이해로는 SC2 API 포트는 사실상 단일 클라이언트다 — 두 번째 연결이 거부되거나,
붙더라도 게임 참가 상태를 공유하지 못한다. 다만 **이건 내가 실측한 게 아니다.
첫 번째 할 일이 이 검증이다** (§6-A).

만약 단일 클라이언트가 맞다면 설계가 정해진다:

> **관측 채널은 런처 프로세스 안에 살아야 한다.**
> 외부 스크립트가 14180에 붙는 방식은 불가능하고, 대신 런처가 이미 가진 연결에서
> 뽑은 데이터를 로컬 사이드카로 내보내야 한다.

---

## 5. 계측 표면 — 패널 상태에 실제로 닿는 세 가지

우선순위 순. **1번이 가장 싸고 지금 인터페이스로 바로 된다.**

### (1) `Unit.is_selected` — 지금 raw 인터페이스로 즉시 가능 ★추천 출발점

`raw_data.units`의 각 유닛에 `is_selected` 불리언이 있다. 사용자가 게임 안에서
고장난 저글링을 **드래그로 선택**하고 "지금"이라고 말하면, 에이전트는
`is_selected == True`인 유닛만 뽑으면 된다. 좌표를 설명할 필요조차 없다.

프로토콜 변경 0, 인터페이스 옵션 변경 0. **이것만으로도 사용자 시나리오가 성립한다.**

그다음이 진짜 분석이다 — 선택된(고장난) 유닛과, **같은 타입의 정상 유닛**의
모든 raw 필드를 나란히 놓고 차이를 찾는다. 볼 만한 필드:
`unit_type`, `health/health_max`, `shield_max`, `energy_max`, `radius`,
`build_progress`, `is_active`, `is_on_screen`, `cloak`, `is_blip`,
`weapon_cooldown`, `buff_ids`, `orders`, `passengers`, `display_type`, `alliance`.

`weapon_cooldown`과 `orders`는 "공격을 못 한다"에 직결된다.

### (2) `observation.ui_data` + `observation.abilities` — 패널 그 자체

이게 문자 그대로 명령카드/선택패널이다.

- `ResponseObservation.observation.ui_data` — `single`(단일 선택 패널),
  `multi`(다중 선택 패널), `production`, `cargo` 등
- `ResponseObservation.observation.abilities` — 현재 선택에 사용 가능한 능력 목록
  = **명령카드에 실제로 떠 있는 버튼들**

"패널이 비었다"를 수치로 확정하려면 이게 필요하다. 정상 저글링은 abilities에
이동/공격/정지/잠복이 뜨고, 고장난 저글링은 비어 있을 것이다 — 가설이지만
이걸로 참·거짓이 갈린다.

**대가:** `ui_data`/`abilities`는 `InterfaceOptions`에 `feature_layer`(또는
`render`)가 설정돼 있어야 채워진다. `sc2team/protocol.py:212`를 고쳐야 한다.

### (3) `render` 인터페이스 — 화면 픽셀

최후 수단. 실제 렌더 화면을 받는다. 비싸고, 사람이 이미 보고 있는 걸 중복으로
받는 것이라 우선순위 낮다. 다만 스크린샷으로 증거를 남겨야 할 때는 유용하다.

저장소에 `verify_campaign_render.py` 선례가 있으니 참고.

---

## 6. 작업 순서 — 이 순서대로 해라

### A. 먼저 검증: 두 번째 연결이 가능한가 (30분)

게임을 하나 띄운 상태에서 별도 프로세스로 `ws://127.0.0.1:14180/sc2api`에 붙어
`ping` → `observation`을 시도한다. 세 가지 결과가 가능하다:

| 결과 | 함의 |
| --- | --- |
| 연결도 관측도 됨 | **최상.** 런처를 아예 안 건드리고 외부 attach 스크립트만 만들면 된다 |
| 연결은 되나 관측이 빔/에러 | 게임 참가 상태가 연결별. 사이드카 방식으로 간다 |
| 연결 거부 / 기존 연결 끊김 | 사이드카 방식 확정. **기존 연결이 끊기면 사용자 게임이 죽으니, 이 실험은 실플레이가 아니라 버려도 되는 테스트 게임에서 해라** |

이 결과가 아래 설계를 결정한다. **추측하지 말고 측정해라.**

### B. 사이드카 구현 (A에서 외부 attach가 안 될 경우)

`run_v3_game()`의 폴링 루프 안에 로컬 조회 서버를 붙인다.

권장: `127.0.0.1`에 작은 HTTP 서버(예: 포트 14181). `aiohttp`를 새로 들이기
싫으면 표준 라이브러리 `asyncio.start_server`로 최소 HTTP를 직접 쳐도 된다 —
엔드포인트 서너 개면 충분하다.

- `GET /health` — 게임 진행 중인가, game_loop, 실시간 경과
- `GET /snapshot` — 소유자별 유닛 수, 총 유닛 수, 보급, game_loop
- `GET /selected` — **핵심.** `is_selected` 유닛 전체 필드 덤프 + (가능하면)
  `ui_data`/`abilities`
- `GET /compare` — `is_selected` 유닛 vs 같은 타입 비선택 유닛의 필드 차이만 출력

설계 요건:

- **완전 읽기 전용.** 액션·debug 명령 절대 금지. 사용자의 실제 게임이다.
- 폴링 루프의 1초 주기 관측을 **재사용**해라. 요청마다 새 관측을 뜨지 마라 —
  realtime 게임에서 관측 요청은 공짜가 아니다.
- 관측 실패·소켓 에러가 **게임 루프를 죽이면 안 된다.** 사이드카 예외는 잡아서
  로그만 남기고 삼킨다(이건 예외적으로 정당한 swallow다 — 이유를 주석에 남겨라).
- 런처 체크박스로 on/off. **기본은 off.** 평소 플레이는 지금과 100% 동일해야 한다.

### C. `feature_layer` 켜기 — 측정하고 결정

`sc2team/protocol.py:212`의 `InterfaceOptions`에 `feature_layer`를 추가하는 건
`join_game`을 쓰는 **모든 프로브에 영향을 준다.** 기본값을 바꾸지 말고
**파라미터로 받아서 런처만 켜라.**

그리고 **켠 상태와 끈 상태의 프레임 비용을 실측해라.** realtime 게임에
관측 부하가 늘면 사용자 플레이가 끊긴다. 관측 왕복 지연을 재는 정도면 충분하다.
비용이 유의미하면 (1)의 raw-only 경로만 남기고 (2)는 포기한다.

### D. 에이전트 사용법 문서화

다음 세션이 "지금 조회해"를 어떻게 하는지 한 줄로 알 수 있게. `curl` 한 방이면
좋다. `docs/operations/local-runbook.md`에 절차를 남겨라.

---

## 7. 하지 말 것

- **`map/source/**` 절대 수정 금지.** 사용자 자산이다.
- **`v3/ai/upstream/**` 읽기 전용.** SHA-256으로 고정돼 있다.
- **`v3/ai/overlay/**`, `v3/ai/overlay-manifest.json`, `tools/campaign_data/**`
  손대지 마라.** 지금 내 세션(fb10399d)이 커밋 안 된 변경을 잔뜩 들고 있다.
  특히 매니페스트는 galaxy 10개 해시를 전부 담고 있어서 충돌하면 아프다.
- **검증기를 통과시키려고 검증기를 고치지 마라.**
- **커밋하지 마라.** 사용자가 명시적으로 지시할 때만 커밋한다.
- SC2는 배타적이다. 게임을 띄우기 전과 종료한 뒤에 A2A로 통보해라.

---

## 8. 소유 경계

이 작업이 건드릴 파일 — 전부 **현재 아무도 안 잡고 있다**:

- `app/play_custom_ai_v3.py`
- `sc2team/protocol.py`
- `sc2team/process.py` (아마 불필요)
- 새 파일: 사이드카 모듈, 외부 조회 스크립트
- `docs/operations/local-runbook.md`

내 세션(fb10399d)이 잡고 있는 것 — **겹치지 않는다**:

- `v3/ai/overlay/Base.SC2Data/TriggerLibs/V3/ZergRoachHydraUltra.galaxy`
- `v3/ai/overlay-manifest.json`
- `tools/campaign_data/roster/UnitData.xml`
- `tools/campaign_data/torrasque/UpgradeData.xml`
- `v3/docs/status.md`

---

## 9. 성공 기준

사용자가 라이브 게임에서 고장난 유닛을 선택하고 "지금"이라고 말했을 때,
에이전트가 **10초 안에** 다음을 답할 수 있으면 완료다:

1. 선택된 유닛의 종류·수·좌표·소유자
2. 그 유닛들의 전체 raw 필드
3. 같은 타입 정상 유닛과의 필드 차이
4. 그 시점의 총 유닛 수와 게임 시간

(2)~(3)에서 차이가 하나도 안 나오면 그 자체가 결론이다 — 증상이 시뮬레이션
계층이 아니라 순수 클라이언트 액터/UI 계층에 있다는 뜻이고, 그러면 (2)번
계측 표면(`ui_data`/`abilities`)이나 렌더로 올라가야 한다.

---

## 10. 참고 — 아직 안 풀린 인접 문제

같은 원인일 수도 있어서 남긴다. 확정된 연결은 아니다.

**18분 생산 정지.** 12슬롯 미러 프로브에서 11/12 슬롯이 동시에 멈췄다.
알(Egg)이 3.2 → 18.7로 늘고 라바가 33.2 → 17.6으로 정확히 상쇄되며 줄었다.
오버로드도 멈췄고 P1~12 총 유닛이 1996 → 2001에 고정됐다. 유닛 천장(≈4690)
때문은 아니다(당시 총 2997). 6빌드 혼합에서는 야생저그 유무와 무관하게
재현되지 않는다.

두 현상 다 **후반부·전역·raw로 잘 안 보임**이라는 성질을 공유한다. 라이브
브리지가 생기면 정지 시점에 사람이 직접 보면서 조회할 수 있다.

기존 프로브 계측 결함도 같이 적어둔다:
`v3/verification/probe_v3_ground_builds.py`는 `player_result`를 아예 확인하지
않고(게임 종료를 못 봄), `supply_cap`/`army_supply` 열이 서로 모순된다
(모든 슬롯 모든 시점에서 used > provided).
