"""7v6 확장 좌표 적대적 검증 (비실시간 step 모드).

사용법: .venv\\Scripts\\python.exe verification\\verify_expansion_coordinates.py [게임분]

SC2 API를 realtime=False로 만들고 connection.step(224)로 호출당 게임시간 10초를
진행한다. 사람 참가자는 아무 명령도 내리지 않는다. 매 샘플마다 모든 커스텀 AI의
타운홀과 일꾼을 추적해 다음을 기록/판정한다.

  - 타운홀 생성/완성 시각, 소유 플레이어, 종족, 실제 (x, y)
  - 가장 가까운 검증 후보 ID와 거리, 그 후보의 광물/가스
  - 동일 플레이어 타운홀 사이의 최소 거리
  - 같은 후보에 같은 플레이어의 타운홀이 2채 이상 생겼는지
  - 실패 후 같은 빈 땅에 반복 발주했는지
  - 확장 일꾼이 180초 넘게 정지해 있는지
  - 도달 가능한 후보가 있는데 7분/12분까지 기지 수가 모자란지
  - 종족별로 사령부/연결체/해처리가 모두 작동하는지
"""

from __future__ import annotations

import asyncio
import json
import math
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from s2clientprotocol import sc2api_pb2 as sc_pb

from sc2team.custom_config import CustomLauncherConfig
from sc2team.custom_runtime import RACE_VALUES, build_runtime_map, player_setups
from sc2team.process import discover_sc2_executable, launch_sc2, stop_process
from sc2team.protocol import Sc2Connection
from sc2team.strategy_controller import GAME_LOOPS_PER_SECOND, StrategyController
from verification.analyze_expansion_layout import EXPECTED_STARTS

BASE_MAP = PROJECT_ROOT / "map/source/europe-melee-2-7v7-rich-50000-fixed-teams.SC2Map"
PROBE_MAP = PROJECT_ROOT / "runtime/maps/expansion-coordinate-probe.SC2Map"
CONFIG_PATH = PROJECT_ROOT / "runtime/custom_ai_settings.json"
LAYOUT_PATH = PROJECT_ROOT / "tools/build/expansion-layout.json"
FULL_LAYOUT_PATH = PROJECT_ROOT / "runtime/reports/expansion-layout.json"
REPORT_PATH = PROJECT_ROOT / "runtime/reports/expansion-coordinate-runtime.json"
SHOT_DIR = PROJECT_ROOT / "runtime/reports/expansion-shots"
PORT = 14171

TOWN_HALL_TYPES = {18, 59, 86, 100, 101, 130, 132}
WORKER_TYPES = {45: "SCV", 84: "Probe", 104: "Drone"}
SAMPLE_LOOPS = 224  # 게임시간 10초

NEW_HALL_FROM_START = 15.0   # 이보다 멀면 시작 본진이 아니라 새 확장이다
OFF_CANDIDATE_DISTANCE = 8.0  # 요청 후보에서 이보다 벗어나면 실패
MIN_HALL_SEPARATION = 14.0    # 타운홀 중심 간 최소 거리
STUCK_SECONDS = 180.0         # 일꾼 정지 판정
STUCK_MOVE_EPSILON = 1.0
REPEAT_SPOT_RADIUS = 6.0


def distance(left, right) -> float:
    return math.hypot(left[0] - right[0], left[1] - right[1])


async def move_camera(connection: Sc2Connection, x: float, y: float) -> None:
    request = sc_pb.Request()
    action = request.action.actions.add()
    action.action_raw.camera_move.center_world_space.x = x
    action.action_raw.camera_move.center_world_space.y = y
    await connection.request(request)


def grab_window(path: Path) -> bool:
    """launch_sc2(index=0)의 창 위치(40,40) 800x450을 그대로 캡처한다."""
    try:
        from PIL import ImageGrab

        path.parent.mkdir(parents=True, exist_ok=True)
        ImageGrab.grab(bbox=(40, 40, 40 + 800, 40 + 450)).save(path)
        return True
    except Exception as error:  # 캡처 실패가 계측을 죽이면 안 된다
        print(f"SCREENSHOT_FAILED {path.name}: {error}", flush=True)
        return False


def draw_overlay(records, candidates_by_id, starts, path: Path) -> bool:
    try:
        from PIL import Image, ImageDraw

        size, scale = 256, 3
        image = Image.new("RGB", (size * scale, size * scale), "#11161b")
        draw = ImageDraw.Draw(image)

        def point(x, y):
            return round(x * scale), round((size - y) * scale)

        for candidate in candidates_by_id.values():
            x, y = point(*candidate["point"])
            color = "#7f8c98" if candidate["covered"] else "#4aa8ff"
            draw.ellipse((x - 6, y - 6, x + 6, y + 6), outline=color, width=2)
            draw.text((x + 7, y - 6), str(candidate["id"]), fill="#8fa0ad")
        for logical, start in starts.items():
            x, y = point(*start)
            draw.rectangle((x - 5, y - 5, x + 5, y + 5), outline="#ff5f57", width=2)
            draw.text((x + 6, y + 3), f"P{logical}", fill="#ffb0aa")
        for record in records:
            x, y = point(*record["position"])
            color = "#ff4d4d" if record["off_candidate"] else "#4ee07a"
            draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill=color)
            draw.text((x + 5, y - 5), f"P{record['slot']}", fill=color)
        draw.text((8, 8), "green=on-candidate  red=off-candidate  blue=candidate  red box=start", fill="#c8d0d8")
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(path)
        return True
    except Exception as error:
        print(f"OVERLAY_FAILED: {error}", flush=True)
        return False


async def main(minutes: float) -> None:
    config = CustomLauncherConfig.from_dict(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
    layout = json.loads(LAYOUT_PATH.read_text(encoding="utf-8"))
    enrichment = {}
    if FULL_LAYOUT_PATH.exists():
        for candidate in json.loads(FULL_LAYOUT_PATH.read_text(encoding="utf-8"))["candidates"]:
            enrichment[candidate["id"]] = {
                "minerals": candidate["minerals"],
                "gases": candidate["gases"],
            }

    print(f"EXPANSION_ADVERSARIAL_BUILDING minutes={minutes}", flush=True)
    build_runtime_map(
        PROJECT_ROOT,
        BASE_MAP,
        PROBE_MAP,
        config,
        strategy_bridge=True,
        campaign_units_pilot=True,
    )
    process = launch_sc2(discover_sc2_executable(), PORT, 0)
    connection: Sc2Connection | None = None
    try:
        connection = await Sc2Connection.open(PORT)
        print("EXPANSION_ADVERSARIAL_CREATING_GAME", flush=True)
        await connection.create_game_with_setups(
            PROBE_MAP.name, PROBE_MAP.read_bytes(), player_setups(config), realtime=False
        )
        await connection.join_game(RACE_VALUES["Terran"], "Expansion adversarial probe", None)
        observation = await connection.observation(disable_fog=True)

        runtime_starts: dict[int, tuple[float, float]] = {}
        for unit in observation.observation.raw_data.units:
            if (
                1 <= unit.owner <= 14
                and unit.unit_type in TOWN_HALL_TYPES
                and unit.build_progress >= 1.0
                and unit.owner not in runtime_starts
            ):
                runtime_starts[unit.owner] = (unit.pos.x, unit.pos.y)
        unused = set(EXPECTED_STARTS)
        runtime_to_logical: dict[int, int] = {}
        for runtime, actual in sorted(runtime_starts.items()):
            logical = min(unused, key=lambda slot: distance(actual, EXPECTED_STARTS[slot]))
            runtime_to_logical[runtime] = logical
            unused.remove(logical)
        print(f"RUNTIME_TO_LOGICAL={runtime_to_logical}", flush=True)

        slot_by_runtime = {}
        for runtime, logical in runtime_to_logical.items():
            slot = next((s for s in config.slots if s.slot == logical), None)
            if slot is not None and slot.controller == "custom_ai" and slot.race != "Random":
                slot_by_runtime[runtime] = slot

        # 슬롯 종족별 허용 후보(시작지점이 덮지 않은 것만)
        allowed_by_race: dict[str, list[tuple[int, tuple[float, float]]]] = {}
        for race in ("Terran", "Protoss", "Zerg"):
            allowed_by_race[race] = [
                (candidate["id"], tuple(candidate["race_positions"][race]))
                for candidate in layout["candidates"]
                if not candidate["covered_by_starts"] and race in candidate["race_positions"]
            ]
        reachable_by_logical: dict[int, int] = {}
        for runtime, slot in slot_by_runtime.items():
            reachable_by_logical[slot.slot] = sum(
                1
                for candidate in layout["candidates"]
                if not candidate["covered_by_starts"]
                and slot.race in candidate["race_positions"]
                and float(candidate["pathing"].get(str(slot.slot), 0) or 0) > 0
            )

        candidates_by_id = {}
        for candidate in layout["candidates"]:
            position = candidate["race_positions"].get("Terran") or next(
                iter(candidate["race_positions"].values()), None
            )
            if position:
                candidates_by_id[candidate["id"]] = {
                    "id": candidate["id"],
                    "point": tuple(position),
                    "covered": bool(candidate["covered_by_starts"]),
                }

        controller = StrategyController(connection, config)
        controller.initialize(observation)
        limit = int(minutes * 60 * GAME_LOOPS_PER_SECOND)

        halls: dict[int, dict] = {}    # unit tag -> record
        workers: dict[int, dict] = {}  # unit tag -> stationary tracking
        base_timeline: list[dict] = []
        next_print = 0.0
        next_dump = 60.0
        elapsed = 0.0

        def dump_partial(status: str) -> None:
            REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
            REPORT_PATH.write_text(
                json.dumps(
                    {
                        "status": status,
                        "minutes_requested": minutes,
                        "elapsed_game_seconds": round(elapsed, 1),
                        "mode": "realtime=False step(224)",
                        "halls": list(halls.values()),
                        "base_timeline": base_timeline,
                    },
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

        while True:
            await connection.step(SAMPLE_LOOPS)
            observation = await connection.observation(disable_fog=True)
            # 게임이 끝난 뒤 컨트롤러가 명령을 보내면 "Game has already ended"로
            # 죽어 최종 리포트를 잃는다. 종료를 먼저 확인하고, 그래도 남는
            # 경합은 삼키되 계측은 계속한다.
            if not observation.player_result:
                try:
                    await controller.update(observation)
                except Exception as error:
                    print(f"CONTROLLER_UPDATE_SKIPPED: {error}", flush=True)
            elapsed = observation.observation.game_loop / GAME_LOOPS_PER_SECOND

            seen_workers = set()
            for unit in observation.observation.raw_data.units:
                runtime = unit.owner
                if runtime not in slot_by_runtime:
                    continue
                position = (round(unit.pos.x, 2), round(unit.pos.y, 2))
                if unit.unit_type in TOWN_HALL_TYPES:
                    record = halls.get(unit.tag)
                    if record is None:
                        slot = slot_by_runtime[runtime]
                        start = runtime_starts[runtime]
                        record = {
                            "tag": unit.tag,
                            "slot": slot.slot,
                            "race": slot.race,
                            "runtime": runtime,
                            "first_seen": round(elapsed, 1),
                            "first_position": list(position),
                            "position": list(position),
                            "completed_at": None,
                            "is_start_hall": distance(position, start) <= NEW_HALL_FROM_START
                            and elapsed <= 1.0,
                        }
                        halls[unit.tag] = record
                    record["position"] = list(position)
                    record["last_seen"] = round(elapsed, 1)
                    if record["completed_at"] is None and unit.build_progress >= 1.0:
                        record["completed_at"] = round(elapsed, 1)
                elif unit.unit_type in WORKER_TYPES:
                    seen_workers.add(unit.tag)
                    tracked = workers.get(unit.tag)
                    if tracked is None:
                        workers[unit.tag] = {
                            "runtime": runtime,
                            "slot": slot_by_runtime[runtime].slot,
                            "position": position,
                            "since": elapsed,
                            "max_stationary": 0.0,
                            "stuck_position": list(position),
                        }
                    else:
                        if distance(position, tracked["position"]) > STUCK_MOVE_EPSILON:
                            tracked["position"] = position
                            tracked["since"] = elapsed
                        else:
                            span = elapsed - tracked["since"]
                            if span > tracked["max_stationary"]:
                                tracked["max_stationary"] = span
                                tracked["stuck_position"] = list(position)

            completed = {}
            for record in halls.values():
                if record.get("completed_at") is not None and record.get("last_seen") == round(elapsed, 1):
                    completed[record["slot"]] = completed.get(record["slot"], 0) + 1
            base_timeline.append({"t": round(elapsed, 1), "bases": completed})

            if elapsed >= next_print:
                summary = " ".join(
                    f"P{slot}={completed.get(slot, 0)}"
                    for slot in sorted(s.slot for s in slot_by_runtime.values())
                )
                print(f"t={elapsed:6.0f}s bases {summary}", flush=True)
                next_print += 60.0
            if elapsed >= next_dump:
                dump_partial("running")
                next_dump += 60.0

            if observation.player_result or observation.observation.game_loop >= limit:
                break

        print(f"EXPANSION_ADVERSARIAL_LOOP_DONE elapsed={elapsed:.0f}s", flush=True)

        # ---------------- 사후 판정 ----------------
        failures: list[dict] = []
        records: list[dict] = []
        per_slot_halls: dict[int, list[dict]] = {}

        for record in halls.values():
            slot_id = record["slot"]
            per_slot_halls.setdefault(slot_id, []).append(record)

        for slot_id, slot_halls in sorted(per_slot_halls.items()):
            race = slot_halls[0]["race"]
            runtime = slot_halls[0]["runtime"]
            start = runtime_starts[runtime]
            allowed = allowed_by_race[race]
            positions = [tuple(item["position"]) for item in slot_halls]

            # 동일 플레이어 타운홀 사이 최소 거리
            min_separation = None
            closest_pair = None
            for i in range(len(positions)):
                for j in range(i + 1, len(positions)):
                    d = distance(positions[i], positions[j])
                    if min_separation is None or d < min_separation:
                        min_separation = d
                        closest_pair = (positions[i], positions[j])
            if min_separation is not None and min_separation < MIN_HALL_SEPARATION:
                failures.append({
                    "type": "town_halls_closer_than_14",
                    "slot": slot_id,
                    "race": race,
                    "distance": round(min_separation, 2),
                    "pair": [list(closest_pair[0]), list(closest_pair[1])],
                })

            by_candidate: dict[int, list[dict]] = {}
            new_positions: list[tuple[tuple[float, float], dict]] = []
            for record in slot_halls:
                position = tuple(record["position"])
                if distance(position, start) <= NEW_HALL_FROM_START:
                    continue  # 시작 본진(및 그 자리 재건)
                nearest_distance, nearest_id = min(
                    (distance(position, point), candidate_id)
                    for candidate_id, point in allowed
                )
                entry = {
                    "slot": slot_id,
                    "race": race,
                    "position": list(position),
                    "first_seen": record["first_seen"],
                    "completed_at": record["completed_at"],
                    "nearest_candidate": nearest_id,
                    "distance_to_candidate": round(nearest_distance, 2),
                    "candidate_minerals": enrichment.get(nearest_id, {}).get("minerals"),
                    "candidate_gases": enrichment.get(nearest_id, {}).get("gases"),
                    "min_distance_to_own_hall": round(min_separation, 2) if min_separation else None,
                    "off_candidate": nearest_distance > OFF_CANDIDATE_DISTANCE,
                }
                records.append(entry)
                by_candidate.setdefault(nearest_id, []).append(entry)
                new_positions.append((position, entry))
                if entry["off_candidate"]:
                    failures.append({"type": "built_off_requested_candidate", **entry})

            for candidate_id, entries in by_candidate.items():
                if len(entries) >= 2:
                    failures.append({
                        "type": "duplicate_town_halls_on_one_candidate",
                        "slot": slot_id,
                        "race": race,
                        "candidate": candidate_id,
                        "count": len(entries),
                        "positions": [entry["position"] for entry in entries],
                    })

            # 실패 후 같은 빈 땅 반복 발주
            for i in range(len(new_positions)):
                for j in range(i + 1, len(new_positions)):
                    left, right = new_positions[i], new_positions[j]
                    if (
                        left[1]["off_candidate"]
                        and right[1]["off_candidate"]
                        and distance(left[0], right[0]) <= REPEAT_SPOT_RADIUS
                    ):
                        failures.append({
                            "type": "repeated_orders_same_empty_spot",
                            "slot": slot_id,
                            "race": race,
                            "positions": [list(left[0]), list(right[0])],
                        })

        # 확장 속도 게이트
        def bases_at(slot_id: int, seconds: float) -> int:
            best = 0
            for sample in base_timeline:
                if sample["t"] <= seconds:
                    best = max(best, sample["bases"].get(slot_id, 0))
            return best

        for runtime, slot in sorted(slot_by_runtime.items(), key=lambda item: item[1].slot):
            if reachable_by_logical.get(slot.slot, 0) <= 0:
                continue
            if elapsed >= 420 and bases_at(slot.slot, 420) < 2:
                failures.append({
                    "type": "fewer_than_2_bases_by_7min",
                    "slot": slot.slot, "race": slot.race,
                    "bases": bases_at(slot.slot, 420),
                })
            if elapsed >= 720 and bases_at(slot.slot, 720) < 3:
                failures.append({
                    "type": "fewer_than_3_bases_by_12min",
                    "slot": slot.slot, "race": slot.race,
                    "bases": bases_at(slot.slot, 720),
                })

        # 종족별 작동 여부
        race_success: dict[str, int] = {}
        for entry in records:
            if not entry["off_candidate"]:
                race_success[entry["race"]] = race_success.get(entry["race"], 0) + 1
        active_races = {slot.race for slot in slot_by_runtime.values()}
        for race in sorted(active_races):
            if race_success.get(race, 0) == 0:
                failures.append({"type": "race_never_expanded_on_candidate", "race": race})

        # 정지 일꾼
        stuck = []
        for tag, tracked in workers.items():
            if tracked["max_stationary"] <= STUCK_SECONDS:
                continue
            slot_id = tracked["slot"]
            own = [tuple(item["position"]) for item in per_slot_halls.get(slot_id, [])]
            spot = tuple(tracked["stuck_position"])
            if own and min(distance(spot, hall) for hall in own) <= 12.0:
                continue  # 본진 근처에서 논 것은 확장 일꾼 정지가 아니다
            stuck.append({
                "slot": slot_id,
                "position": list(spot),
                "stationary_seconds": round(tracked["max_stationary"], 1),
            })
        for item in sorted(stuck, key=lambda x: -x["stationary_seconds"])[:20]:
            failures.append({"type": "expansion_worker_stuck_over_180s", **item})

        starts_by_logical = {
            runtime_to_logical[runtime]: list(position)
            for runtime, position in runtime_starts.items()
            if runtime in runtime_to_logical
        }
        payload = {
            "status": "complete",
            "mode": "realtime=False step(224)",
            "minutes_requested": minutes,
            "elapsed_game_seconds": round(elapsed, 1),
            "runtime_to_logical": runtime_to_logical,
            "reachable_candidates_by_slot": reachable_by_logical,
            "new_town_halls": records,
            "all_halls": list(halls.values()),
            "base_timeline": base_timeline,
            "race_success_counts": race_success,
            "failures": failures,
        }
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"EXPANSION_REPORT={REPORT_PATH}", flush=True)

        draw_overlay(records, candidates_by_id, starts_by_logical, SHOT_DIR / "expansion-overlay.png")

        # 실패 지점 카메라 스크린샷 (성공 사례만 고르지 않는다)
        shot_targets = [(f.get("slot"), f.get("position") or (f.get("positions") or [None])[0], f["type"])
                        for f in failures if f.get("position") or f.get("positions")]
        if not shot_targets:
            shot_targets = [(entry["slot"], entry["position"], "on_candidate") for entry in records[:3]]
        for index, (slot_id, position, kind) in enumerate(shot_targets[:6]):
            if not position:
                continue
            try:
                await move_camera(connection, float(position[0]), float(position[1]))
                await connection.step(8)
                await connection.observation(disable_fog=True)
                grab_window(SHOT_DIR / f"{index:02d}_P{slot_id}_{kind}.png")
            except Exception as error:
                print(f"SHOT_SKIPPED {index}: {error}", flush=True)

        by_type: dict[str, int] = {}
        for failure in failures:
            by_type[failure["type"]] = by_type.get(failure["type"], 0) + 1
        print(f"EXPANSION_NEW_TOWN_HALLS={len(records)}")
        print(f"EXPANSION_RACE_SUCCESS={race_success}")
        print(f"EXPANSION_FAILURE_COUNTS={by_type}")
        if failures:
            print("EXPANSION_COORDINATE_TEST=FAIL")
        else:
            print("EXPANSION_COORDINATE_TEST=PASS")
    finally:
        if connection is not None:
            try:
                await connection.quit()
            except Exception:
                pass
            await connection.close()
        stop_process(process)


if __name__ == "__main__":
    asyncio.run(main(float(sys.argv[1]) if len(sys.argv) > 1 else 7.0))
