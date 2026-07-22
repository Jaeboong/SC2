"""주기적 프레임 끊김 A/B 계측.

사용자 보고: "게임 중 약 5초 간격으로 1초가량 멈춘다(7vs6, 12 AI, 초중반부터)".

SC2 API는 클라이언트의 프레임률을 알려주지 않는다. 대신 **시뮬레이션 스레드가
막혔는지**를 두 가지로 관측한다. 둘 다 직접 계측값이며, 프레임률 자체는 추론이다.

1. 관측 왕복 시간. `RequestObservation` 은 게임 시뮬레이션 스레드가 응답한다.
   맵 Galaxy 트리거가 그 스레드를 붙잡고 있는 동안에는 응답이 그만큼 늦다.
   즉 왕복 시간의 꼬리(p99/최대)가 곧 "그 순간 게임이 멈춰 있던 시간"이다.
2. 시뮬레이션 진행률. 실시간 게임에서 game_loop 는 벽시계 초당 22.4 로 는다.
   멈춘 구간에서는 이 비율이 떨어진다.

주의: 이 스크립트 자신도 100ms 마다 관측을 요청하므로 부하를 만든다. 그 부하는
모든 실행 조건에서 같으므로 **조건 간 비교**는 유효하지만, 절대값을 "게임을
가만히 둘 때의 성능"으로 읽으면 안 된다.

    python verification/measure_stutter.py <맵파일> <초> [--no-strategy] [--label 이름]

사람 슬롯은 아무것도 하지 않는다(가만히 서 있는 참가자). 부하는 12 AI 가 만든다.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sc2team.custom_config import CustomLauncherConfig
from sc2team.custom_runtime import (
    RACE_VALUES,
    load_stock_targets,
    player_setups,
    runtime_player_id,
)
from sc2team.custom_runtime import runtime_slots
from sc2team.process import discover_sc2_executable, launch_sc2, stop_process
from sc2team.protocol import Sc2Connection
from sc2team.strategy_controller import TOWN_HALL_TYPES, StrategyController

from s2clientprotocol import sc2api_pb2 as sc_pb


PORT = 14210
POLL_SECONDS = 0.1
GAME_LOOPS_PER_SECOND = 22.4
# 사용자가 "멈췄다"고 느끼는 하한. 60fps 기준 15프레임이다.
HITCH_SECONDS = 0.25
SETTINGS_FILE = PROJECT_ROOT / "runtime" / "custom_ai_settings.json"
# 라이브 상태 줄 간격(벽시계 초).
LIVE_SECONDS = 5.0


def base_counts(observation, player_count: int) -> dict[int, int]:
    """런타임 플레이어별 완성 타운홀 수. 확장 진행/실패를 눈으로 보기 위한 것."""

    counts = {runtime: 0 for runtime in range(1, player_count + 1)}
    for unit in observation.observation.raw_data.units:
        owner = getattr(unit, "owner", 0)
        if not 1 <= owner <= player_count:
            continue
        if getattr(unit, "build_progress", 1.0) < 0.99:
            continue
        if unit.unit_type in TOWN_HALL_TYPES:
            counts[owner] += 1
    return counts


def percentile(ordered: list[float], fraction: float) -> float:
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, max(0, round(fraction * len(ordered)) - 1))
    return ordered[index]


def report(label: str, roundtrips: list[float], rates: list[float], seconds: float) -> dict:
    ordered = sorted(roundtrips)
    hitches = [value for value in roundtrips if value >= HITCH_SECONDS]
    summary = {
        "label": label,
        "samples": len(roundtrips),
        "wall_seconds": round(seconds, 1),
        "observation_ms": {
            "mean": round(sum(ordered) / len(ordered) * 1000, 1) if ordered else 0.0,
            "p50": round(percentile(ordered, 0.50) * 1000, 1),
            "p95": round(percentile(ordered, 0.95) * 1000, 1),
            "p99": round(percentile(ordered, 0.99) * 1000, 1),
            "max": round(ordered[-1] * 1000, 1) if ordered else 0.0,
        },
        "hitches": {
            "threshold_ms": HITCH_SECONDS * 1000,
            "count": len(hitches),
            "per_minute": round(len(hitches) / (seconds / 60.0), 2) if seconds else 0.0,
            "worst_ms": round(max(hitches) * 1000, 1) if hitches else 0.0,
            "total_stalled_ms": round(sum(hitches) * 1000, 1),
            "stalled_fraction": round(sum(hitches) / seconds, 4) if seconds else 0.0,
        },
        "sim_loops_per_second": {
            "mean": round(sum(rates) / len(rates), 2) if rates else 0.0,
            "min": round(min(rates), 2) if rates else 0.0,
        },
    }
    print(f"\n=== {label} ===")
    obs = summary["observation_ms"]
    print(
        f"  관측 왕복  평균 {obs['mean']}ms  p50 {obs['p50']}ms  "
        f"p95 {obs['p95']}ms  p99 {obs['p99']}ms  최대 {obs['max']}ms"
    )
    hit = summary["hitches"]
    print(
        f"  끊김(>={int(HITCH_SECONDS * 1000)}ms)  {hit['count']}회  "
        f"분당 {hit['per_minute']}회  최악 {hit['worst_ms']}ms  "
        f"정지 시간 비율 {hit['stalled_fraction'] * 100:.2f}%"
    )
    sim = summary["sim_loops_per_second"]
    print(f"  시뮬 진행  평균 {sim['mean']} loops/s (기준 22.4)")
    return summary


async def main() -> None:
    if len(sys.argv) < 3:
        print(__doc__)
        raise SystemExit(2)
    map_file = Path(sys.argv[1]).resolve()
    seconds = float(sys.argv[2])
    use_strategy = "--no-strategy" not in sys.argv
    label = "새 맵"
    if "--label" in sys.argv:
        label = sys.argv[sys.argv.index("--label") + 1]
    label += " / 전략제어기 " + ("ON" if use_strategy else "OFF")
    if not map_file.is_file():
        raise FileNotFoundError(f"맵을 찾을 수 없습니다: {map_file}")

    # 저장된 설정은 읽기만 한다. 프로브는 절대 이 파일을 쓰지 않는다.
    config = CustomLauncherConfig.from_dict(
        json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    )

    process = launch_sc2(discover_sc2_executable(), PORT, 0, width=1280, height=720)
    connection: Sc2Connection | None = None
    roundtrips: list[float] = []
    rates: list[float] = []
    try:
        connection = await Sc2Connection.open(PORT, timeout=120.0)
        await connection.create_game_with_setups(
            map_file.name,
            map_file.read_bytes(),
            player_setups(config),
            realtime=True,
        )
        player_id = await connection.join_game(
            RACE_VALUES[config.human.race], "Stutter Probe", None
        )
        expected = runtime_player_id(config, config.human.slot)
        if player_id != expected:
            raise RuntimeError(f"사람 슬롯 매핑 실패: {player_id} != {expected}")

        strategy: StrategyController | None = None
        if use_strategy:
            first = await connection.observation(disable_fog=True)
            strategy = StrategyController(connection, config)
            data_request = sc_pb.Request()
            data_request.data.CopyFrom(sc_pb.RequestData(unit_type_id=True))
            game_data = (await connection.request(data_request)).data
            units_by_name = {unit.name: unit for unit in game_data.units}
            for unit_name, supply in {
                "HotSTorrasque": 6.0, "SC2TeamAberration": 3.0,
                "SC2TeamGoliath": 2.0, "SC2TeamMedic": 1.0, "SC2TeamPredator": 3.0,
            }.items():
                unit = units_by_name.get(unit_name)
                if unit is not None and unit.available and unit.ability_id:
                    strategy.register_ground_combat_unit(unit.unit_id, supply)
            for entry in load_stock_targets(map_file):
                stock = {
                    units_by_name[name].unit_id: (
                        float(spec["count"]), float(spec["perExpansion"])
                    )
                    for name, spec in entry["stock"].items()
                    if name in units_by_name
                }
                if stock:
                    strategy.set_stock_targets(entry["logical_slot"], stock)
            strategy.initialize(first)

        slots = runtime_slots(config)
        player_count = len(slots)
        labels = {
            index + 1: f"P{slot.slot}" for index, slot in enumerate(slots)
        }
        print(
            f"\n라이브 모니터링 시작 ({label}) — {seconds:.0f}초\n"
            f"  끊김은 {int(HITCH_SECONDS * 1000)}ms 이상 정지할 때마다 즉시 찍는다.\n"
            f"  기지 = 완성 타운홀 수(확장 성공 여부가 여기서 보인다).\n",
            flush=True,
        )
        clock = asyncio.get_running_loop().time
        started = clock()
        deadline = started + seconds
        next_strategy = started
        previous_loop: int | None = None
        previous_wall: float | None = None
        last_report = started
        peak_bases: dict[int, int] = {}
        while clock() < deadline:
            before = clock()
            try:
                observation = await connection.observation(disable_fog=True)
            except Exception as error:
                # SC2 창/웹소켓이 먼저 죽어도 지금까지의 계측을 버리지 않는다.
                # 종전에는 10분 넘게 모은 hitch 표본이 traceback과 함께 전부
                # 사라져 A/B를 다시 처음부터 돌려야 했다.
                print(
                    f"  [연결 종료] t={clock() - started:6.1f}s: "
                    f"{type(error).__name__}: {error}",
                    flush=True,
                )
                break
            after = clock()
            roundtrips.append(after - before)
            game_loop = observation.observation.game_loop
            if after - before >= HITCH_SECONDS:
                print(
                    f"  [끊김] t={after - started:6.1f}s  게임 "
                    f"{game_loop / GAME_LOOPS_PER_SECOND:6.1f}s  "
                    f"정지 {(after - before) * 1000:7.1f}ms",
                    flush=True,
                )
            if previous_loop is not None and after - previous_wall > 0:
                rates.append((game_loop - previous_loop) / (after - previous_wall))
            previous_loop, previous_wall = game_loop, after
            if observation.player_result:
                print("게임이 먼저 끝났습니다.", flush=True)
                break
            # 전략 제어기는 런처와 같은 1Hz 로만 돌린다(계측 폴링은 100ms).
            if strategy is not None and after >= next_strategy:
                next_strategy = after + 1.0
                await strategy.update(observation)
            if after - last_report >= LIVE_SECONDS:
                last_report = after
                bases = base_counts(observation, player_count)
                for runtime, count in bases.items():
                    peak_bases[runtime] = max(peak_bases.get(runtime, 0), count)
                # 최고치보다 줄어든 슬롯은 확장이 깨졌거나 기지를 잃은 것이다.
                shown = " ".join(
                    f"{labels[runtime]}:{count}"
                    + ("!" if count < peak_bases[runtime] else "")
                    for runtime, count in bases.items()
                )
                hitches = [value for value in roundtrips if value >= HITCH_SECONDS]
                print(
                    f"  t={after - started:6.1f}s 게임 "
                    f"{game_loop / GAME_LOOPS_PER_SECOND:6.1f}s | "
                    f"끊김 {len(hitches):3d}회 최악 "
                    f"{max(hitches) * 1000 if hitches else 0:6.1f}ms | 기지 {shown}",
                    flush=True,
                )
            await asyncio.sleep(max(0.0, POLL_SECONDS - (clock() - before)))
        summary = report(label, roundtrips, rates, clock() - started)
        out = PROJECT_ROOT / "runtime" / "stutter" / f"{map_file.stem}-{'on' if use_strategy else 'off'}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  저장: {out}")
    finally:
        if connection is not None:
            try:
                await asyncio.wait_for(connection.quit(), timeout=5.0)
            except Exception:
                pass
            await connection.close()
        stop_process(process)


if __name__ == "__main__":
    asyncio.run(main())
    print("MEASURE_STUTTER=DONE")
