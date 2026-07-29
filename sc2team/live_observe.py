"""라이브 관측 브리지 — 사람이 플레이 중인 게임을 읽기 전용으로 조회한다.

왜 사이드카인가: SC2의 `-listen/-port`가 여는 `ws://127.0.0.1:<port>/sc2api`는
단일 클라이언트다. 런처가 이미 붙어 있으면 두 번째 프로세스는 TCP 연결까지만
되고 WebSocket 핸드셰이크가 끝나지 않는다(실측 §6-A). 그래서 외부에서 붙는
방식은 불가능하고, **이미 연결을 가진 런처가 자기 관측을 로컬로 내보내는** 수밖에
없다.

이 모듈은 SC2 연결을 만지지 않는다. 런처 폴링 루프가 이미 1초마다 뜨고 버리던
관측을 `publish()`로 넘겨주면, 그 스냅샷만 HTTP로 서빙한다. 따라서
  - 관측 요청이 추가로 발생하지 않는다(realtime 게임에서 공짜가 아니다)
  - 액션·debug를 보낼 경로가 아예 없다. GET 외의 메서드는 405로 거절한다

용도: 패널이 비고 공격도 못 하는 유닛 버그. 사용자가 게임 안에서 증상 유닛을
드래그로 선택하면 `Unit.is_selected`로 그것만 뽑아, 같은 타입 정상 유닛과 전
필드를 비교한다.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import Counter, deque
from typing import Any, Callable
from urllib.parse import parse_qs, urlsplit

from google.protobuf.json_format import MessageToDict
from s2clientprotocol import sc2api_pb2 as sc_pb


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 14181

# SC2 "Faster" 게임 속도의 초당 게임 루프 수.
LOOPS_PER_SECOND = 22.4

# 같은 타입의 건강한 유닛 둘 사이에서도 당연히 다른 필드들. 진단 신호를 묻어버리기
# 때문에 /compare 의 차이 목록에서 뺀다. (원본은 /selected 가 그대로 다 준다.)
#   tag/pos/facing — 유닛마다 다른 게 정상
#   orders         — 하나는 이동 중이고 하나는 대기 중인 게 정상. 대신 아래에서
#                    ability_id 요약을 따로 낸다
#   is_on_screen   — 카메라 위치에 종속. 선택한 유닛은 화면 안, 비교군은 대체로 밖
#   is_selected    — 두 집단을 가르는 기준 그 자체. 항상 다르므로 정보가 없다
_DIFF_IGNORED = frozenset(
    {"tag", "pos", "facing", "orders", "is_on_screen", "is_selected"}
)

# /compare 는 유닛마다 protobuf→dict 변환을 한다. 이 서버는 사용자가 플레이 중인
# 게임의 이벤트 루프를 공유하므로, 저글링 400기짜리 비교군을 통째로 변환하면 그
# 동안 폴링 루프가 멈춘다. 비교군은 여기서 자르고, 잘랐다는 사실을 응답에 적는다.
_REFERENCE_SAMPLE_CAP = 120


class LiveObserveBridge:
    """런처 안에서 도는 읽기 전용 로컬 조회 서버."""

    def __init__(
        self,
        *,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        log: Callable[[str], None] | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._log = log if log is not None else (lambda message: None)
        self._server: asyncio.AbstractServer | None = None
        self._response: sc_pb.ResponseObservation | None = None
        self._published_at: float | None = None
        self._roundtrip_ms: deque[float] = deque(maxlen=120)
        self._started_at: float | None = None
        self._requests = 0

    @property
    def url(self) -> str:
        return f"http://{self._host}:{self._port}"

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle, self._host, self._port)
        self._started_at = time.monotonic()
        self._log(f"라이브 관측 브리지 시작: {self.url}")

    async def stop(self) -> None:
        server, self._server = self._server, None
        if server is None:
            return
        server.close()
        try:
            await server.wait_closed()
        except Exception as error:  # noqa: BLE001 - 종료 경로는 게임을 방해하지 않는다
            self._log(f"라이브 관측 브리지 종료 중 무시한 오류: {error!r}")

    def publish(
        self,
        response: sc_pb.ResponseObservation,
        *,
        roundtrip_ms: float | None = None,
    ) -> None:
        """폴링 루프가 방금 뜬 관측을 넘겨준다. 저장만 하므로 비용이 없다."""

        self._response = response
        self._published_at = time.monotonic()
        if roundtrip_ms is not None:
            self._roundtrip_ms.append(roundtrip_ms)

    # ------------------------------------------------------------------ HTTP

    async def _handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            request_line = await asyncio.wait_for(reader.readline(), timeout=5.0)
            if not request_line:
                return
            parts = request_line.decode("latin-1").split()
            if len(parts) < 2:
                await self._respond(writer, 400, {"error": "malformed request"})
                return
            method, target = parts[0], parts[1]
            while True:  # 헤더를 비운다. 본문은 읽지 않는다 — GET만 받는다.
                header = await asyncio.wait_for(reader.readline(), timeout=5.0)
                if header in (b"\r\n", b"\n", b""):
                    break
            if method != "GET":
                await self._respond(
                    writer, 405, {"error": "this bridge is read-only; use GET"}
                )
                return
            self._requests += 1
            split = urlsplit(target)
            status, payload = self._payload(
                split.path, parse_qs(split.query)
            )
            await self._respond(writer, status, payload)
        except Exception as error:  # noqa: BLE001
            # 의도적인 삼킴이다. 이 서버는 사용자가 실제로 플레이 중인 게임의
            # 프로세스 안에서 돈다. 잘못된 curl 한 방이나 소켓 에러가 게임 루프를
            # 죽이면 안 된다. 관측 자체는 여기서 하지 않으므로, 여기서 잃는 것은
            # 조회 응답 하나뿐이다.
            self._log(f"라이브 관측 요청 실패(무시): {error!r}")
        finally:
            try:
                writer.close()
            except Exception:  # noqa: BLE001
                pass

    async def _respond(
        self, writer: asyncio.StreamWriter, status: int, payload: Any
    ) -> None:
        reason = {
            200: "OK",
            400: "Bad Request",
            404: "Not Found",
            405: "Method Not Allowed",
            503: "Service Unavailable",
        }.get(status, "OK")
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        head = (
            f"HTTP/1.1 {status} {reason}\r\n"
            "Content-Type: application/json; charset=utf-8\r\n"
            f"Content-Length: {len(body)}\r\n"
            "Cache-Control: no-store\r\n"
            "Connection: close\r\n\r\n"
        ).encode("latin-1")
        writer.write(head + body)
        await writer.drain()

    # --------------------------------------------------------------- payload

    def _payload(self, path: str, query: dict[str, list[str]]) -> tuple[int, Any]:
        routes = {
            "/health": self._health,
            "/snapshot": self._snapshot,
            "/selected": self._selected,
            "/compare": self._compare,
        }
        handler = routes.get(path.rstrip("/") or "/health")
        if handler is None:
            return 404, {"error": f"unknown endpoint {path}", "endpoints": sorted(routes)}
        if path.rstrip("/") not in ("", "/health") and self._response is None:
            return 503, {"error": "아직 관측이 없습니다. 게임이 시작되었는지 확인하세요."}
        return 200, handler(query)

    def _age_seconds(self) -> float | None:
        if self._published_at is None:
            return None
        return round(time.monotonic() - self._published_at, 3)

    def _clock(self) -> dict[str, Any]:
        assert self._response is not None
        observation = self._response.observation
        loop = observation.game_loop
        return {
            "game_loop": loop,
            "game_time_seconds": round(loop / LOOPS_PER_SECOND, 1),
            "game_time": _format_clock(loop / LOOPS_PER_SECOND),
            "snapshot_age_seconds": self._age_seconds(),
        }

    def _health(self, _query: dict[str, list[str]]) -> dict[str, Any]:
        samples = list(self._roundtrip_ms)
        payload: dict[str, Any] = {
            "bridge": "live-observe",
            "url": self.url,
            "uptime_seconds": (
                None
                if self._started_at is None
                else round(time.monotonic() - self._started_at, 1)
            ),
            "requests_served": self._requests,
            "has_observation": self._response is not None,
            "observation_roundtrip_ms": {
                "samples": len(samples),
                "last": round(samples[-1], 2) if samples else None,
                "mean": round(sum(samples) / len(samples), 2) if samples else None,
                "max": round(max(samples), 2) if samples else None,
            },
        }
        if self._response is not None:
            observation = self._response.observation
            payload.update(self._clock())
            payload["units_total"] = len(observation.raw_data.units)
            payload["game_over"] = bool(self._response.player_result)
            # feature_layer 를 켜야만 채워지는 표면들.
            # ui_data/abilities 는 "현재 선택"에 달려 있어서, 선택이 없으면(옵저버
            # 참가가 그렇다) 인터페이스가 제대로 붙었어도 빈다. 반면
            # feature_layer_data 는 선택과 무관하게 채워지므로, spatial 인터페이스가
            # 실제로 붙었는지는 이쪽으로 판별해야 한다.
            payload["has_feature_layer_data"] = observation.HasField("feature_layer_data")
            payload["has_ui_data"] = observation.HasField("ui_data")
            payload["abilities_available"] = len(observation.abilities)
        return payload

    def _snapshot(self, _query: dict[str, list[str]]) -> dict[str, Any]:
        assert self._response is not None
        observation = self._response.observation
        units = observation.raw_data.units
        by_owner: Counter[int] = Counter(unit.owner for unit in units)
        common = observation.player_common
        return {
            **self._clock(),
            "units_total": len(units),
            "units_by_owner": {str(owner): count for owner, count in sorted(by_owner.items())},
            "selected_count": sum(1 for unit in units if unit.is_selected),
            "viewing_player_id": common.player_id,
            "viewing_player": {
                "minerals": common.minerals,
                "vespene": common.vespene,
                "food_used": common.food_used,
                "food_cap": common.food_cap,
                "food_army": common.food_army,
                "food_workers": common.food_workers,
                "army_count": common.army_count,
            },
            "game_over": bool(self._response.player_result),
        }

    def _selected_units(self) -> list:
        assert self._response is not None
        return [
            unit
            for unit in self._response.observation.raw_data.units
            if unit.is_selected
        ]

    def _selected(self, query: dict[str, list[str]]) -> dict[str, Any]:
        assert self._response is not None
        observation = self._response.observation
        limit = _int_param(query, "limit", 60)
        selected = self._selected_units()
        payload: dict[str, Any] = {
            **self._clock(),
            "units_total": len(observation.raw_data.units),
            "selected_count": len(selected),
            "returned": min(len(selected), limit),
            "types": {
                str(unit_type): count
                for unit_type, count in sorted(
                    Counter(unit.unit_type for unit in selected).items()
                )
            },
            "owners": sorted({unit.owner for unit in selected}),
            "units": [_unit_dict(unit) for unit in selected[:limit]],
        }
        if not selected:
            payload["hint"] = (
                "게임 안에서 증상 유닛을 드래그로 선택한 뒤 다시 호출하세요. "
                "선택은 1초 폴링 주기 안에 반영됩니다."
            )
        # 명령카드 그 자체. feature_layer 가 꺼져 있으면 비어 있다.
        payload["ui_data"] = (
            MessageToDict(observation.ui_data, preserving_proto_field_name=True)
            if observation.HasField("ui_data")
            else None
        )
        payload["abilities"] = [
            MessageToDict(ability, preserving_proto_field_name=True)
            for ability in observation.abilities
        ]
        if payload["ui_data"] is None and not payload["abilities"]:
            payload["ui_note"] = (
                "ui_data/abilities 가 비었습니다. 런처의 '명령카드 계측' 옵션"
                "(feature_layer)을 켜고 게임을 다시 시작해야 채워집니다."
            )
        return payload

    def _compare(self, query: dict[str, list[str]]) -> dict[str, Any]:
        assert self._response is not None
        units = list(self._response.observation.raw_data.units)
        selected = [unit for unit in units if unit.is_selected]
        limit = _int_param(query, "limit", 40)
        result: dict[str, Any] = {
            **self._clock(),
            "selected_count": len(selected),
            "groups": [],
        }
        if not selected:
            result["hint"] = "선택된 유닛이 없습니다. 게임 안에서 증상 유닛을 선택하세요."
            return result

        for unit_type in sorted({unit.unit_type for unit in selected}):
            group = [unit for unit in selected if unit.unit_type == unit_type]
            owners = {unit.owner for unit in group}
            reference = [
                unit
                for unit in units
                if unit.unit_type == unit_type
                and not unit.is_selected
                and unit.owner in owners
            ]
            reference_scope = "same_owner"
            if not reference:
                reference = [
                    unit
                    for unit in units
                    if unit.unit_type == unit_type and not unit.is_selected
                ]
                reference_scope = "any_owner"
            sample = reference[:_REFERENCE_SAMPLE_CAP]
            group_payload: dict[str, Any] = {
                "unit_type": unit_type,
                "selected": len(group),
                "reference": len(reference),
                "reference_sampled": len(sample),
                "reference_scope": reference_scope if reference else "none",
                "owners": sorted(owners),
                "orders_summary": {
                    "selected": _order_summary(group),
                    "reference": _order_summary(sample),
                },
            }
            if len(sample) < len(reference):
                group_payload["reference_truncated"] = (
                    f"비교군 {len(reference)}기 중 앞 {len(sample)}기만 비교했습니다 "
                    f"(게임 루프 점유를 막기 위한 상한 {_REFERENCE_SAMPLE_CAP})."
                )
            if not reference:
                group_payload["note"] = (
                    "같은 타입의 비선택 유닛이 없어 비교할 기준이 없습니다."
                )
                group_payload["differences"] = {}
            else:
                group_payload["differences"] = _field_differences(
                    group, sample, limit=limit
                )
                if not group_payload["differences"]:
                    group_payload["note"] = (
                        "raw 필드 차이가 없습니다 — 증상이 시뮬레이션 계층이 아니라 "
                        "클라이언트 액터/UI 계층에 있다는 뜻입니다."
                    )
            result["groups"].append(group_payload)
        return result


# ------------------------------------------------------------------ helpers


def _format_clock(seconds: float) -> str:
    minutes, remainder = divmod(int(seconds), 60)
    return f"{minutes}:{remainder:02d}"


def _int_param(query: dict[str, list[str]], name: str, default: int) -> int:
    values = query.get(name)
    if not values:
        return default
    try:
        return max(1, int(values[0]))
    except ValueError:
        return default


def _unit_dict(unit) -> dict[str, Any]:
    return MessageToDict(unit, preserving_proto_field_name=True)


def _order_summary(units) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for unit in units:
        if not unit.orders:
            counter["idle"] += 1
            continue
        for order in unit.orders:
            counter[str(order.ability_id)] += 1
    return dict(sorted(counter.items()))


def _field_differences(group, reference, *, limit: int) -> dict[str, Any]:
    """선택 유닛 집합과 기준 유닛 집합에서 값 집합이 다른 필드만 뽑는다."""

    selected_values = _value_sets(group)
    reference_values = _value_sets(reference)
    differences: dict[str, Any] = {}
    for field in sorted(set(selected_values) | set(reference_values)):
        mine = selected_values.get(field, set())
        theirs = reference_values.get(field, set())
        if mine == theirs:
            continue
        differences[field] = {
            "selected": _sorted_sample(mine, limit),
            "reference": _sorted_sample(theirs, limit),
            "only_in_selected": _sorted_sample(mine - theirs, limit),
            "only_in_reference": _sorted_sample(theirs - mine, limit),
        }
    return differences


def _value_sets(units) -> dict[str, set]:
    values: dict[str, set] = {}
    for unit in units:
        for field, value in _unit_dict(unit).items():
            if field in _DIFF_IGNORED:
                continue
            values.setdefault(field, set()).add(_hashable(value))
    return values


def _hashable(value: Any) -> Any:
    if isinstance(value, list):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value


def _sorted_sample(values: set, limit: int) -> list:
    return sorted(values, key=repr)[:limit]
