from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
import tkinter as tk
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from s2clientprotocol import debug_pb2 as debug_pb
from s2clientprotocol import sc2api_pb2 as sc_pb

from sc2team.custom_config import (
    CONTROLLERS,
    DEFAULT_BUILD_BY_RACE,
    GROUND_BUILDS,
    MELEE_BUILDS,
    PROTOSS_FACTIONS,
    RACES,
    CustomLauncherConfig,
    SlotConfig,
    build_key,
    default_custom_config,
)
from sc2team.custom_runtime import (
    RACE_VALUES,
    build_runtime_map,
    load_stock_targets,
    player_setups,
    runtime_player_id,
)
from sc2team.process import discover_sc2_executable, launch_sc2, stop_process
from sc2team.protocol import Sc2Connection
from sc2team.strategy_controller import StrategyController


APP_VERSION = "1.25.0"
BASE_MAP_FILE = (
    PROJECT_ROOT
    / "map"
    / "source"
    / "europe-melee-2-7v7-rich-50000-fixed-teams.SC2Map"
)
RUNTIME_MAP_FILE = (
    PROJECT_ROOT / "runtime" / "maps" / f"europe-melee-custom-ai-v{APP_VERSION}.SC2Map"
)
# Test mode forces full vision, which is baked into the map at build time, so it
# must never write over the release map that start_custom_ai.cmd plays.
TEST_MAP_FILE = (
    PROJECT_ROOT / "runtime" / "maps" / f"europe-melee-custom-ai-v{APP_VERSION}-test.SC2Map"
)
SETTINGS_FILE = PROJECT_ROOT / "runtime" / "custom_ai_settings.json"
REPLAY_DIR = PROJECT_ROOT / "runtime" / "replays"
# API로 만든 게임은 클라이언트가 리플레이를 자동 저장하지 않는다. 런처가
# RequestSaveReplay로 직접 받아 저장하며, 진행 중에도 이 주기(초)마다 같은
# 파일에 덮어써서 SC2 창이 강제로 닫혀도 최근본까지는 남긴다.
REPLAY_SNAPSHOT_SECONDS = 60

# Measured, not assumed: one all_resources call grants a fixed 5000 minerals and
# 5000 vespene rather than switching on an unlimited state, so the test launcher
# tops the bank back up whenever it falls below this floor. The separate
# `minerals` and `gas` cheats were unreliable in the same probe -- gas did not
# move at all -- so all_resources is the one used.
TEST_RESOURCE_FLOOR = 5_000
# Two grants on join so the opening bank already sits above the floor; one grant
# lands at 5050/5000 and would trip the top-up on the very first tick.
TEST_RESOURCE_GRANTS_ON_JOIN = 2
# 배속(테스트 전용): 배속 >1이면 게임을 비실시간(스텝) 모드로 만들고 런처가
# 시뮬레이션을 벽시계보다 빠르게 밀어준다 — 클라이언트 리플레이 8배속과 같은
# 원리다. Faster 기준 게임은 초당 22.4루프이므로 N배속은 초당 22.4×N루프를
# 민다. 16배속 등 높은 배속에서 실제 속도는 CPU가 따라오는 만큼만 나온다.
GAME_LOOPS_PER_SECOND = 22.4
STEP_TICK_SECONDS = 0.5
TEST_SPEED_CHOICES = (1, 2, 4, 8, 16)

# §95 진단 경로. 둘 다 환경 변수로만 켜지므로 릴리스 동작(더블클릭 실행)은
# 아무 영향을 받지 않는다 — 외부 전략 제어기는 기본으로 계속 켜져 있다.
#
#   SC2TEAM_DISABLE_STRATEGY=1   전략 제어기를 만들지 않는다. 주기적 프레임
#                                끊김이 맵 트리거 쪽인지 SC2 API 관측 쪽인지
#                                가르는 A/B 대조군이다. 이 상태에서는 출격·
#                                긴급지원이 멜레 AI 자체 판단에 맡겨진다.
#   SC2TEAM_TICK_LOG=<파일>      틱마다 관측/전략/전체 소요를 JSONL로 남기고
#                                종료 시 평균·p95·최대를 요약한다.
DISABLE_STRATEGY_ENV = "SC2TEAM_DISABLE_STRATEGY"
TICK_LOG_ENV = "SC2TEAM_TICK_LOG"


class _TickTimings:
    """런처 틱 소요 시간 수집기(진단 전용)."""

    def __init__(self, log_path: Path | None) -> None:
        self._log_path = log_path
        self._handle = None
        self.observation: list[float] = []
        self.strategy: list[float] = []
        self.total: list[float] = []
        if log_path is not None:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            self._handle = log_path.open("w", encoding="utf-8")

    @property
    def enabled(self) -> bool:
        return self._handle is not None

    def record(
        self,
        game_loop: int,
        observation: float,
        strategy: float,
        total: float,
    ) -> None:
        if self._handle is None:
            return
        self.observation.append(observation)
        self.strategy.append(strategy)
        self.total.append(total)
        self._handle.write(
            json.dumps(
                {
                    "game_loop": game_loop,
                    "observation_ms": round(observation * 1000, 3),
                    "strategy_ms": round(strategy * 1000, 3),
                    "tick_ms": round(total * 1000, 3),
                },
            )
            + "\n"
        )

    @staticmethod
    def _summary(samples: list[float]) -> dict[str, float]:
        if not samples:
            return {"n": 0, "mean_ms": 0.0, "p95_ms": 0.0, "max_ms": 0.0}
        ordered = sorted(samples)
        # 최근접 순위법. 표본이 적어도 정의가 흔들리지 않는다.
        index = min(len(ordered) - 1, max(0, round(0.95 * len(ordered)) - 1))
        return {
            "n": len(ordered),
            "mean_ms": round(sum(ordered) / len(ordered) * 1000, 3),
            "p95_ms": round(ordered[index] * 1000, 3),
            "max_ms": round(ordered[-1] * 1000, 3),
        }

    def close(self, *, strategy_enabled: bool) -> str:
        if self._handle is None:
            return ""
        summary = {
            "strategy_controller": "on" if strategy_enabled else "off",
            "observation": self._summary(self.observation),
            "strategy_update": self._summary(self.strategy),
            "launcher_tick": self._summary(self.total),
        }
        self._handle.write(json.dumps({"summary": summary}) + "\n")
        self._handle.close()
        self._handle = None
        tick = summary["launcher_tick"]
        obs = summary["observation"]
        return (
            f" 틱 계측 {self._log_path.name}: "
            f"관측 평균 {obs['mean_ms']:.1f}ms/p95 {obs['p95_ms']:.1f}ms/최대 {obs['max_ms']:.1f}ms, "
            f"전체 평균 {tick['mean_ms']:.1f}ms/p95 {tick['p95_ms']:.1f}ms/최대 {tick['max_ms']:.1f}ms"
        )


async def run_layout_test(
    config: CustomLauncherConfig,
    cancel_event: threading.Event,
    status: Callable[[str], None],
    *,
    test_mode: bool = False,
    speed: int = 1,
    observer: bool = False,
) -> str:
    # 배속·옵저버는 테스트 런처 전용이다(배속은 비실시간 스텝 구동 필요,
    # 옵저버는 사람 슬롯을 AI가 대신 플레이).
    if not test_mode:
        speed = 1
        observer = False
    if observer:
        # 옵저버 모드에서 사람 슬롯은 멜레 AI+커스텀 규칙이 플레이하므로
        # 종족에 유효한 빌드가 필요하다. GUI의 사람 행은 빌드 선택이 꺼져
        # 있어 이전 값이 남을 수 있고, 안 맞으면 종족 기본 빌드로 바꾼다.
        human = config.human
        if human.build not in GROUND_BUILDS[human.race]:
            fixed = replace(human, build=DEFAULT_BUILD_BY_RACE[human.race])
            config = replace(
                config,
                slots=tuple(
                    fixed if slot.slot == human.slot else slot
                    for slot in config.slots
                ),
            )
    if test_mode:
        # Full vision is a map build-time setting, so it is forced on the copy
        # used for this run only. The user's saved choice is left alone.
        config = replace(config, full_vision=True)
    config.validate()
    if not BASE_MAP_FILE.is_file():
        raise FileNotFoundError(f"기준 맵을 찾을 수 없습니다: {BASE_MAP_FILE}")

    status("선택한 슬롯으로 실행용 맵을 생성하는 중…")
    runtime_map = build_runtime_map(
        PROJECT_ROOT,
        BASE_MAP_FILE,
        TEST_MAP_FILE if test_mode else RUNTIME_MAP_FILE,
        config,
        strategy_bridge=True,
        campaign_units_pilot=True,
        observer_mode=observer,
        active_config_file=(
            TEST_MAP_FILE.with_suffix(".json") if test_mode else None
        ),
    )
    executable = discover_sc2_executable()
    process = launch_sc2(
        executable, 14100, 0, width=1280, height=720, fullscreen=config.fullscreen
    )
    connection: Sc2Connection | None = None
    result_text = "전략 AI 게임이 종료되었습니다."

    try:
        status("SC2 API 연결을 기다리는 중…")
        connection = await Sc2Connection.open(14100)
        version = await connection.ping()
        active = ", ".join(f"P{slot.slot}" for slot in config.active_slots)
        status(f"SC2 {version.game_version} 연결 — 슬롯 {active} 생성 중…")
        await connection.create_game_with_setups(
            runtime_map.name,
            runtime_map.read_bytes(),
            player_setups(config, observer=observer),
            realtime=speed <= 1,
        )
        if observer:
            await connection.join_as_observer()
        else:
            player_id = await connection.join_game(
                RACE_VALUES[config.human.race],
                f"P{config.human.slot} Local Human",
                None,
            )
            expected_player_id = runtime_player_id(config, config.human.slot)
            if player_id != expected_player_id:
                raise RuntimeError(
                    f"사람 슬롯 매핑 실패: 위치 P{config.human.slot}은 게임 내부에서 "
                    f"P{expected_player_id}여야 하지만 P{player_id}로 참가했습니다."
                )
        if test_mode:
            speed_note = f", {speed}배속(스텝 구동)" if speed > 1 else ""
            if observer:
                # 관전 연결은 디버그 치트를 걸 참가자가 없다. 시야는 게임 안
                # 옵저버 UI(시야 메뉴)로 고른다.
                status(
                    f"[테스트·옵저버] P{config.human.slot} 슬롯까지 전부 AI가 "
                    f"플레이합니다{speed_note}. 관전 중…"
                )
            else:
                # fast_build finishes structures instantly and cuts unit
                # production to roughly a thirteenth of its normal time. food
                # lifts the supply block that instant production would
                # otherwise hit immediately.
                await connection.debug_game_state(debug_pb.fast_build)
                await connection.debug_game_state(debug_pb.food)
                await connection.debug_game_state(debug_pb.show_map)
                for _ in range(TEST_RESOURCE_GRANTS_ON_JOIN):
                    await connection.debug_game_state(debug_pb.all_resources)
                status(
                    f"[테스트] 위치 P{config.human.slot} 배치 성공 (게임 내부 P{player_id}). "
                    f"자원 무한, 즉시 생산, 전체 시야{speed_note}가 적용되었습니다."
                )
        else:
            status(
                f"위치 P{config.human.slot} 배치 성공 (게임 내부 P{player_id}). "
                + (
                    "정예 경제 AI, 지상군 생산 유도, 자동 출격 제어기가 작동 중입니다."
                    if config.unit_control
                    else "정예 경제 AI, 지상군 생산 유도가 작동 중입니다 (출격은 밀레 AI 자율)."
                )
            )

        # Full raw state is controller-only and does not reveal the human UI.
        # It lets both teams' AIs notice damage to their own allies.
        # §66 옵저버 게임은 관전 연결이라 유닛 명령이 불가능하므로 전략
        # 제어기(비콘 브리지)를 만들지 않는다. 출격은 멜레 AI 자체 공세,
        # 생산·구매·연구는 맵 안 Galaxy 트리거가 그대로 담당한다.
        strategy: StrategyController | None = None
        # §95 진단: 환경 변수로 외부 제어기를 끌 수 있다. 끄면 관측만 남으므로
        # 끊김의 출처를 맵 트리거 / API 관측으로 가를 수 있다. 조용히 켜지지
        # 않도록 상태 표시줄에 반드시 알린다.
        strategy_disabled = os.environ.get(DISABLE_STRATEGY_ENV) == "1"
        if strategy_disabled:
            status(
                "[진단] 외부 전략 제어기를 끈 상태로 실행합니다 "
                f"({DISABLE_STRATEGY_ENV}=1). 출격·긴급지원은 멜레 AI가 맡습니다."
            )
        # §105: 유닛 제어 모듈이 꺼진 맵에는 비컨 브리지가 없으므로 파이썬
        # 제어기를 만들면 안 된다(initialize가 비컨을 못 찾아 즉시 실패).
        # 병력 지휘는 밀레 AI 자율이고 생산·보급·확장 보조는 맵 Galaxy가 담당.
        if not observer and not config.unit_control:
            status(
                "유닛 제어 모듈 꺼짐 — 출격·지원·본진방어는 밀레 AI가 스스로 "
                "결정합니다. 생산·보급·확장 보조는 맵 트리거가 담당합니다."
            )
        if not observer and not strategy_disabled and config.unit_control:
            first_observation = await connection.observation(disable_fog=True)
            strategy = StrategyController(connection, config)
            data_request = sc_pb.Request()
            data_request.data.CopyFrom(sc_pb.RequestData(unit_type_id=True))
            game_data = (await connection.request(data_request)).data
            custom_combat_supply = {
                "HotSTorrasque": 6.0,
                "SC2TeamAberration": 3.0,
                "SC2TeamGoliath": 2.0,
                "SC2TeamMedic": 1.0,
                "SC2TeamPredator": 3.0,
            }
            units_by_name = {unit.name: unit for unit in game_data.units}
            for unit_name, supply in custom_combat_supply.items():
                unit = units_by_name.get(unit_name)
                if unit is None or not unit.available or unit.ability_id == 0:
                    raise RuntimeError(
                        f"캠페인 유닛 생산 데이터를 찾지 못했습니다: {unit_name}"
                    )
                strategy.register_ground_combat_unit(unit.unit_id, supply)
            # 빌더가 남긴 목표 재고 사이드카를 유닛 이름→동적 ID로 변환해
            # 주입한다. 재고 표가 있는 슬롯은 출격 문턱이 목표재고 달성률로
            # 바뀐다.
            for entry in load_stock_targets(runtime_map):
                stock_by_id: dict[int, tuple[float, float]] = {}
                for unit_name, spec in entry["stock"].items():
                    unit = units_by_name.get(unit_name)
                    if unit is None:
                        raise RuntimeError(
                            f"목표 재고 유닛 데이터를 찾지 못했습니다: {unit_name}"
                        )
                    stock_by_id[unit.unit_id] = (
                        float(spec["count"]),
                        float(spec["perExpansion"]),
                    )
                if stock_by_id:
                    strategy.set_stock_targets(entry["logical_slot"], stock_by_id)
            strategy.initialize(first_observation)

        REPLAY_DIR.mkdir(parents=True, exist_ok=True)
        replay_file = REPLAY_DIR / (
            f"custom-ai-v{APP_VERSION}"
            + ("-test" if test_mode else "")
            + f"-{datetime.now():%Y%m%d-%H%M%S}.SC2Replay"
        )

        async def save_replay_snapshot(reason: str) -> bool:
            try:
                replay_file.write_bytes(await connection.save_replay())
                return True
            except Exception as error:
                # 저장 실패가 게임 루프를 멈추면 안 되지만, 조용히 삼키지도 않는다.
                status(f"리플레이 저장 실패({reason}): {error}")
                return False

        clock = asyncio.get_running_loop().time
        tick_log = os.environ.get(TICK_LOG_ENV)
        timings = _TickTimings(Path(tick_log) if tick_log else None)
        if timings.enabled:
            status(f"[진단] 틱 계측을 {tick_log}에 기록합니다.")
        next_snapshot = clock() + REPLAY_SNAPSHOT_SECONDS
        loops_per_batch = max(
            1, round(GAME_LOOPS_PER_SECOND * speed * STEP_TICK_SECONDS)
        )
        while not cancel_event.is_set() and process.poll() is None:
            tick_started = clock()
            if speed > 1:
                # 스텝 모드에서 시뮬레이션은 이 호출로만 전진하므로 여기서
                # 배속이 결정된다. 전략 제어기 판단은 게임 시간 기준이라
                # 틱당 게임 시간이 늘어나도 그대로 동작한다.
                await connection.step(loops_per_batch)
            observation_started = clock()
            observation = await connection.observation(disable_fog=True)
            observation_seconds = clock() - observation_started
            if observation.player_result:
                result_text = "SC2 게임이 종료되었습니다."
                if await save_replay_snapshot("게임 종료"):
                    result_text += f" 리플레이: {replay_file.name}"
                break
            if test_mode and not observer:
                # all_resources is a one-off 5000/5000 grant, so spending outruns
                # it unless the bank is topped up as the game runs.
                bank = observation.observation.player_common
                if min(bank.minerals, bank.vespene) < TEST_RESOURCE_FLOOR:
                    await connection.debug_game_state(debug_pb.all_resources)
            strategy_seconds = 0.0
            if strategy is not None:
                strategy_started = clock()
                strategy_update = await strategy.update(observation)
                strategy_seconds = clock() - strategy_started
                if strategy_update.supports:
                    details = ", ".join(
                        f"P{helper}→P{victim}"
                        for helper, victim in strategy_update.supports
                    )
                    status(f"긴급 지원 출동: {details}")
                elif strategy_update.attack_slots:
                    details = []
                    for slot in strategy_update.attack_slots:
                        power, required, producers = strategy.army_readiness(
                            observation, slot
                        )
                        details.append(
                            f"P{slot} 전투력 {power:g}/{required:g}·생산 {producers}"
                        )
                    status(f"전략 제어기 출격: {', '.join(details)}")
            # 리플레이 저장(60초 주기)은 틱 계측에서 제외한다 — 디스크 I/O가
            # 섞이면 관측·전략 비용을 읽을 수 없다.
            timings.record(
                observation.observation.game_loop,
                observation_seconds,
                strategy_seconds,
                clock() - tick_started,
            )
            if clock() >= next_snapshot:
                next_snapshot = clock() + REPLAY_SNAPSHOT_SECONDS
                await save_replay_snapshot("주기 저장")
            wait = (STEP_TICK_SECONDS if speed > 1 else 1.0) - (clock() - tick_started)
            await asyncio.sleep(max(0.02, wait))
        if cancel_event.is_set():
            result_text = "사용자가 전략 AI 게임을 종료했습니다."
            if await save_replay_snapshot("사용자 종료"):
                result_text += f" 리플레이: {replay_file.name}"
        elif process.poll() is not None:
            # SC2 창이 먼저 닫히면 API 연결도 함께 죽어 최종 저장은 불가능하다.
            # 주기 스냅숏이 남긴 최근본이 그대로 최종본이 된다.
            result_text = "SC2 창이 닫혔습니다."
        result_text += timings.close(strategy_enabled=strategy is not None)
        return result_text
    finally:
        if connection is not None:
            await connection.quit()
            await connection.close()
        stop_process(process)


class SlotRow:
    def __init__(
        self,
        app: "CustomLauncherApp",
        parent: tk.Widget,
        slot: SlotConfig,
        row: int,
    ) -> None:
        self.app = app
        self.slot_id = slot.slot
        self.build_id = slot.build
        self._changing = False
        side_label = "서쪽" if slot.slot <= 7 else "동쪽"
        side_color = "#78aef8" if slot.slot <= 7 else "#ff8b83"
        team_label = "1팀" if slot.team == 1 else "2팀"

        self.slot_label = tk.Label(
            parent, text=f"P{slot.slot}", bg="#111a28", fg="#f4f7fb",
            font=("Malgun Gothic", 10, "bold"), width=5,
        )
        self.slot_label.grid(row=row, column=0, padx=(7, 3), pady=4, sticky="ew")
        tk.Label(
            parent, text=f"{side_label} · {team_label}", bg="#111a28",
            fg=side_color, font=("Malgun Gothic", 9, "bold"), width=13,
        ).grid(row=row, column=1, padx=3, pady=4, sticky="ew")

        self.controller_var = tk.StringVar(value=CONTROLLERS[slot.controller])
        self.controller_box = ttk.Combobox(
            parent, textvariable=self.controller_var,
            values=list(CONTROLLERS.values()), state="readonly", width=14,
        )
        self.controller_box.grid(row=row, column=2, padx=3, pady=4, sticky="ew")

        self.race_var = tk.StringVar(value=RACES[slot.race])
        self.race_box = ttk.Combobox(
            parent, textvariable=self.race_var,
            values=list(RACES.values()), state="readonly", width=13,
        )
        self.race_box.grid(row=row, column=3, padx=3, pady=4, sticky="ew")

        self.build_var = tk.StringVar()
        self.build_box = ttk.Combobox(
            parent, textvariable=self.build_var, state="readonly", width=28,
        )
        self.build_box.grid(row=row, column=4, padx=3, pady=4, sticky="ew")

        # 밀레 AI 빌드 분류 직접 지정. "자동"이면 지상군 빌드 이름에서 매핑한다.
        # 세부 빌드 62종은 로비 속성이라 API로 못 넘긴다 — 넘길 수 있는 건 6개
        # 분류까지이고, 그 안에서 무엇이 나올지는 밀레 AI가 정한다.
        self.melee_build_id = slot.melee_build
        self.melee_var = tk.StringVar()
        self.melee_box = ttk.Combobox(
            parent, textvariable=self.melee_var, state="readonly", width=15,
            values=list(MELEE_BUILDS.values()),
        )
        self.melee_box.grid(row=row, column=5, padx=(3, 7), pady=4, sticky="ew")

        self.controller_box.bind("<<ComboboxSelected>>", self._controller_changed)
        self.race_box.bind("<<ComboboxSelected>>", self._race_changed)
        self.build_box.bind("<<ComboboxSelected>>", self._build_changed)
        self.melee_box.bind("<<ComboboxSelected>>", self._melee_changed)
        self.set_slot(slot)

    @property
    def controller(self) -> str:
        display = self.controller_var.get()
        return next(key for key, label in CONTROLLERS.items() if label == display)

    @property
    def race(self) -> str:
        display = self.race_var.get()
        return next(key for key, label in RACES.items() if label == display)

    def _controller_changed(self, _event: object | None = None) -> None:
        if self._changing:
            return
        self.app.on_controller_changed(self)
        self._refresh_enabled()

    def _race_changed(self, _event: object | None = None) -> None:
        if self._changing:
            return
        self.build_id = DEFAULT_BUILD_BY_RACE[self.race]
        self._refresh_builds()

    def _build_changed(self, _event: object | None = None) -> None:
        if self.controller == "custom_ai":
            self.build_id = build_key(self.race, self.build_var.get())

    def _melee_changed(self, _event: object | None = None) -> None:
        display = self.melee_var.get()
        self.melee_build_id = next(
            key for key, label in MELEE_BUILDS.items() if label == display
        )

    def _refresh_builds(self) -> None:
        builds = GROUND_BUILDS[self.race]
        if self.build_id not in builds:
            self.build_id = DEFAULT_BUILD_BY_RACE[self.race]
        self.build_box.configure(values=list(builds.values()))
        self.build_var.set(builds[self.build_id])
        self._refresh_enabled()

    def _refresh_enabled(self) -> None:
        active = self.controller != "empty"
        self.race_box.configure(state="readonly" if active else "disabled")
        ai_slot = self.controller == "custom_ai"
        self.build_box.configure(state="readonly" if ai_slot else "disabled")
        self.melee_box.configure(state="readonly" if ai_slot else "disabled")

    def set_controller(self, controller: str) -> None:
        self._changing = True
        try:
            self.controller_var.set(CONTROLLERS[controller])
            self._refresh_enabled()
        finally:
            self._changing = False

    def to_slot(self) -> SlotConfig:
        return SlotConfig(
            slot=self.slot_id,
            controller=self.controller,
            team=1 if self.slot_id <= 7 else 2,
            race=self.race,
            build=self.build_id,
            melee_build=self.melee_build_id,
        )

    def set_slot(self, slot: SlotConfig) -> None:
        self._changing = True
        try:
            self.controller_var.set(CONTROLLERS[slot.controller])
            self.race_var.set(RACES[slot.race])
            self.build_id = slot.build
            self.melee_build_id = slot.melee_build
            self.melee_var.set(MELEE_BUILDS[slot.melee_build])
            self._refresh_builds()
        finally:
            self._changing = False

    def set_enabled(self, enabled: bool) -> None:
        self.controller_box.configure(state="readonly" if enabled else "disabled")
        if enabled:
            self._refresh_enabled()
        else:
            self.race_box.configure(state="disabled")
            self.build_box.configure(state="disabled")
            self.melee_box.configure(state="disabled")


class CustomLauncherApp:
    def __init__(self, root: tk.Tk, *, test_mode: bool = False) -> None:
        self.root = root
        self.test_mode = test_mode
        suffix = " [테스트 모드]" if test_mode else ""
        self.root.title(f"SC2 Custom AI v{APP_VERSION}{suffix}")
        self.root.geometry("1080x900")
        self.root.minsize(930, 720)
        self.root.configure(bg="#08101d")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.rows: list[SlotRow] = []
        self.running = False
        self.close_requested = False
        self.cancel_event = threading.Event()
        self.worker: threading.Thread | None = None
        self._configure_style()
        self._build_ui(self._load_config())

    def _configure_style(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(
            "TCombobox", fieldbackground="#17243a", background="#17243a",
            foreground="#f4f7fb", arrowcolor="#8ec5ff", bordercolor="#34506f",
            lightcolor="#34506f", darkcolor="#34506f", padding=5,
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", "#17243a"), ("disabled", "#101827")],
            foreground=[("readonly", "#f4f7fb"), ("disabled", "#6e7c90")],
        )

    def _build_ui(self, config: CustomLauncherConfig) -> None:
        header = tk.Frame(self.root, bg="#08101d")
        header.pack(fill="x", padx=22, pady=(18, 10))
        tk.Label(
            header, text=f"유럽 섬멸전 Custom AI v{APP_VERSION}", bg="#08101d", fg="#f6fbff",
            font=("Malgun Gothic", 21, "bold"),
        ).pack(anchor="w")
        if self.test_mode:
            tk.Label(
                header,
                text=(
                    "테스트 모드 — 자원 무한 · 즉시 생산 · 전체 시야가 사람 플레이어에게 "
                    "적용됩니다. 실제 밸런스 확인용이 아닙니다."
                ),
                bg="#3a1d0c", fg="#ffcf8a", font=("Malgun Gothic", 10, "bold"),
                anchor="w", padx=10, pady=6,
            ).pack(fill="x", pady=(8, 0))
        tk.Label(
            header,
            text="P1~P7 서쪽 1팀 · P8~P14 동쪽 2팀 · 사람 1명은 어느 슬롯으로든 이동 가능",
            bg="#08101d", fg="#90a4bf", font=("Malgun Gothic", 10),
        ).pack(anchor="w", pady=(2, 0))

        table = tk.Frame(
            self.root, bg="#111a28", highlightbackground="#2b4667", highlightthickness=1,
        )
        table.pack(fill="both", expand=True, padx=22, pady=6)
        headings = ["슬롯", "위치·팀", "플레이어", "종족", "지상군 빌드", "밀레 빌드"]
        widths = [5, 13, 14, 13, 28, 15]
        for column, (heading, width) in enumerate(zip(headings, widths)):
            tk.Label(
                table, text=heading, width=width, bg="#1a2a40", fg="#bcd7f5",
                font=("Malgun Gothic", 9, "bold"), pady=8,
            ).grid(row=0, column=column, padx=(1, 0), pady=(1, 4), sticky="ew")
            table.grid_columnconfigure(column, weight=2 if column == 4 else 1)
        for index, slot in enumerate(config.slots, start=1):
            self.rows.append(SlotRow(self, table, slot, index))

        options = tk.Frame(self.root, bg="#08101d")
        options.pack(fill="x", padx=24, pady=(6, 2))
        self.full_vision_var = tk.BooleanVar(value=config.full_vision)
        self.support_air_var = tk.BooleanVar(value=config.allow_support_air)
        self.wild_zerg_var = tk.BooleanVar(value=config.wild_zerg)
        self.unit_control_var = tk.BooleanVar(value=config.unit_control)
        self.fullscreen_var = tk.BooleanVar(value=config.fullscreen)
        self.protoss_faction_var = tk.StringVar(
            value=PROTOSS_FACTIONS[config.protoss_faction]
        )
        tk.Checkbutton(
            options, text="사람에게 전체 지도 시야 제공 (테스트)",
            variable=self.full_vision_var, bg="#08101d", fg="#d6e3f3",
            selectcolor="#17243a", activebackground="#08101d", activeforeground="#ffffff",
            font=("Malgun Gothic", 9),
        ).pack(side="left")
        tk.Checkbutton(
            options, text="수송·탐지 지원 공중 유닛 허용", variable=self.support_air_var,
            bg="#08101d", fg="#d6e3f3", selectcolor="#17243a",
            activebackground="#08101d", activeforeground="#ffffff",
            font=("Malgun Gothic", 9),
        ).pack(side="left", padx=(20, 0))
        # §93: 야생 저그(P15) 활성화. 해제하면 선배치된 저그가 자원만 채취하고
        # 아무것도 생산하지 않는다.
        tk.Checkbutton(
            options, text="야생 저그 활성화 (해제 시 채취만)",
            variable=self.wild_zerg_var, bg="#08101d", fg="#d6e3f3",
            selectcolor="#17243a", activebackground="#08101d",
            activeforeground="#ffffff", font=("Malgun Gothic", 9),
        ).pack(side="left", padx=(20, 0))
        tk.Label(
            options, text="프로토스 전역 진영", bg="#08101d", fg="#d6e3f3",
            font=("Malgun Gothic", 9),
        ).pack(side="left", padx=(22, 6))
        self.protoss_faction_box = ttk.Combobox(
            options, textvariable=self.protoss_faction_var,
            values=list(PROTOSS_FACTIONS.values()), state="readonly", width=13,
        )
        self.protoss_faction_box.pack(side="left")
        # §105: 유닛 제어 모듈(출격·지원·본진방어)은 자기 줄에 둔다 — 위 옵션
        # 줄은 §93 때 이미 창 너비 한계에 닿았고, pack(side="left")는 넘치면
        # 그리지 않는다(옵저버 체크박스 실종 사고의 재발 방지).
        options2 = tk.Frame(self.root, bg="#08101d")
        options2.pack(fill="x", padx=24, pady=(0, 2))
        tk.Checkbutton(
            options2,
            text="유닛 제어 모듈 (팀 동시 출격·지원·본진방어 — 끄면 밀레 AI 자율)",
            variable=self.unit_control_var, bg="#08101d", fg="#d6e3f3",
            selectcolor="#17243a", activebackground="#08101d",
            activeforeground="#ffffff", font=("Malgun Gothic", 9),
        ).pack(side="left")
        self.speed_box: ttk.Combobox | None = None
        self.observer_var = tk.BooleanVar(value=False)
        if self.test_mode:
            # 테스트 전용 컨트롤은 **자기 줄**에 둔다. 위 옵션 줄은 §93에서
            # 야생 저그 체크박스가 들어오면서 기본 창 너비(1080)를 넘겼고,
            # pack(side="left")는 넘치면 줄바꿈이 아니라 그리지 않으므로 줄
            # 맨 끝의 옵저버 체크박스가 통째로 보이지 않았다(사용자 보고).
            test_options = tk.Frame(self.root, bg="#08101d")
            test_options.pack(fill="x", padx=24, pady=(2, 2))
            tk.Label(
                test_options, text="배속", bg="#08101d", fg="#ffcf8a",
                font=("Malgun Gothic", 9, "bold"),
            ).pack(side="left", padx=(0, 6))
            self.speed_var = tk.StringVar(value="1배속")
            self.speed_box = ttk.Combobox(
                test_options, textvariable=self.speed_var,
                values=[f"{s}배속" for s in TEST_SPEED_CHOICES],
                state="readonly", width=7,
            )
            self.speed_box.pack(side="left")
            tk.Checkbutton(
                test_options, text="옵저버(내 슬롯도 AI가 플레이)",
                variable=self.observer_var, bg="#08101d", fg="#ffcf8a",
                selectcolor="#17243a", activebackground="#08101d",
                activeforeground="#ffffff", font=("Malgun Gothic", 9, "bold"),
            ).pack(side="left", padx=(16, 0))

        tk.Label(
            self.root,
            text="빠른 첫 확장 + 경제 연동 생산·확장 + 인구 상한 600 + 아군 지원",
            bg="#08101d", fg="#e6aa66", font=("Malgun Gothic", 9),
        ).pack(anchor="w", padx=25, pady=(2, 2))

        footer = tk.Frame(self.root, bg="#08101d")
        footer.pack(fill="x", padx=22, pady=(5, 16))
        self.status_var = tk.StringVar(value="슬롯을 설정한 뒤 전략 AI 게임을 실행할 수 있습니다.")
        tk.Label(
            footer, textvariable=self.status_var, bg="#08101d", fg="#9fb0c7",
            font=("Malgun Gothic", 9), anchor="w",
        ).pack(side="left", fill="x", expand=True)

        buttons = [
            ("프리셋 불러오기", self._load_preset, "#26364d"),
            ("프리셋 저장", self._save_preset, "#26364d"),
            ("기본 4대4", self._reset_defaults, "#26364d"),
        ]
        self.option_buttons: list[tk.Button] = []
        for text, command, color in buttons:
            button = tk.Button(
                footer, text=text, command=command, bg=color, fg="#e6edf7",
                relief="flat", padx=11, pady=8, cursor="hand2",
            )
            button.pack(side="right", padx=(6, 0))
            self.option_buttons.append(button)
        self.stop_button = tk.Button(
            footer, text="테스트 종료", command=self._stop_game, state="disabled",
            bg="#713a3a", fg="#ffffff", disabledforeground="#776b6b",
            relief="flat", padx=12, pady=8, cursor="hand2",
        )
        self.stop_button.pack(side="right", padx=(8, 0))
        self.start_button = tk.Button(
            footer, text="전략 AI 게임 시작", command=self._start_game,
            bg="#1674b9", fg="#ffffff", activebackground="#228bd4",
            activeforeground="#ffffff", relief="flat",
            font=("Malgun Gothic", 9, "bold"), padx=17, pady=8, cursor="hand2",
        )
        self.start_button.pack(side="right", padx=(12, 0))
        self.exit_button = tk.Button(
            footer, text="런처 종료", command=self._on_close,
            bg="#3d4654", fg="#ffffff", activebackground="#515d6e",
            activeforeground="#ffffff", relief="flat",
            padx=12, pady=8, cursor="hand2",
        )
        self.exit_button.pack(side="right", padx=(8, 0))

    def on_controller_changed(self, changed: SlotRow) -> None:
        if changed.controller == "human":
            for row in self.rows:
                if row is not changed and row.controller == "human":
                    row.set_controller("empty")
            self.status_var.set(f"사람 플레이어를 P{changed.slot_id}로 이동했습니다.")

    def _current_config(self) -> CustomLauncherConfig:
        config = CustomLauncherConfig(
            version=1,
            slots=tuple(row.to_slot() for row in self.rows),
            full_vision=self.full_vision_var.get(),
            allow_support_air=self.support_air_var.get(),
            wild_zerg=self.wild_zerg_var.get(),
            unit_control=self.unit_control_var.get(),
            protoss_faction=next(
                key for key, label in PROTOSS_FACTIONS.items()
                if label == self.protoss_faction_var.get()
            ),
        )
        config.validate()
        return config

    def _apply_config(self, config: CustomLauncherConfig) -> None:
        config.validate()
        for row, slot in zip(self.rows, config.slots):
            row.set_slot(slot)
        self.full_vision_var.set(config.full_vision)
        self.support_air_var.set(config.allow_support_air)
        self.wild_zerg_var.set(config.wild_zerg)
        self.unit_control_var.set(config.unit_control)
        self.protoss_faction_var.set(PROTOSS_FACTIONS[config.protoss_faction])

    def _load_config(self) -> CustomLauncherConfig:
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            return CustomLauncherConfig.from_dict(data)
        except (FileNotFoundError, OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            return default_custom_config()

    @staticmethod
    def _write_config(path: Path, config: CustomLauncherConfig) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(config.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _save_preset(self) -> None:
        try:
            config = self._current_config()
        except ValueError as error:
            messagebox.showerror("설정 오류", str(error), parent=self.root)
            return
        selected = filedialog.asksaveasfilename(
            parent=self.root, title="Custom AI 프리셋 저장", defaultextension=".json",
            filetypes=[("JSON 프리셋", "*.json")], initialdir=PROJECT_ROOT / "presets",
        )
        if selected:
            self._write_config(Path(selected), config)
            self.status_var.set(f"프리셋을 저장했습니다: {Path(selected).name}")

    def _load_preset(self) -> None:
        selected = filedialog.askopenfilename(
            parent=self.root, title="Custom AI 프리셋 불러오기",
            filetypes=[("JSON 프리셋", "*.json")], initialdir=PROJECT_ROOT / "presets",
        )
        if not selected:
            return
        try:
            config = CustomLauncherConfig.from_dict(
                json.loads(Path(selected).read_text(encoding="utf-8"))
            )
            self._apply_config(config)
            self.status_var.set(f"프리셋을 불러왔습니다: {Path(selected).name}")
        except Exception as error:
            messagebox.showerror("프리셋 오류", str(error), parent=self.root)

    def _reset_defaults(self) -> None:
        self._apply_config(default_custom_config())
        self.status_var.set("기본 4대4 설정을 복원했습니다.")

    def _set_controls_enabled(self, enabled: bool) -> None:
        for row in self.rows:
            row.set_enabled(enabled)
        for button in self.option_buttons:
            button.configure(state="normal" if enabled else "disabled")
        self.start_button.configure(state="normal" if enabled else "disabled")
        self.stop_button.configure(state="disabled" if enabled else "normal")
        self.protoss_faction_box.configure(
            state="readonly" if enabled else "disabled"
        )
        if self.speed_box is not None:
            self.speed_box.configure(state="readonly" if enabled else "disabled")

    def _start_game(self) -> None:
        if self.running:
            return
        try:
            config = self._current_config()
            self._write_config(SETTINGS_FILE, config)
        except Exception as error:
            messagebox.showerror("설정 오류", str(error), parent=self.root)
            return
        speed = 1
        if self.speed_box is not None:
            speed = int(self.speed_var.get().replace("배속", ""))
        observer = self.test_mode and self.observer_var.get()
        self.running = True
        self.cancel_event.clear()
        self._set_controls_enabled(False)
        self.status_var.set("전략 AI 게임 준비 중…")

        def status(message: str) -> None:
            self.root.after(0, self.status_var.set, message)

        def worker() -> None:
            try:
                result = asyncio.run(
                    run_layout_test(
                        config, self.cancel_event, status,
                        test_mode=self.test_mode, speed=speed, observer=observer,
                    )
                )
                self.root.after(0, self._game_finished, result, None)
            except Exception as error:
                self.root.after(0, self._game_finished, "전략 AI 게임 실행 실패", error)

        self.worker = threading.Thread(target=worker, name="sc2-layout-test", daemon=True)
        self.worker.start()

    def _stop_game(self) -> None:
        if self.running:
            self.status_var.set("SC2 테스트를 종료하는 중…")
            self.cancel_event.set()
            self.stop_button.configure(state="disabled")

    def _game_finished(self, result: str, error: Exception | None) -> None:
        self.running = False
        if self.close_requested:
            self.root.destroy()
            return
        self._set_controls_enabled(True)
        self.status_var.set(result if error is None else f"실행 실패: {error}")
        if error is not None:
            messagebox.showerror("SC2 실행 실패", str(error), parent=self.root)

    def _on_close(self) -> None:
        if self.close_requested:
            return
        if self.running:
            if not messagebox.askyesno(
                "테스트 종료", "실행 중인 SC2 테스트를 종료하고 런처를 닫을까요?",
                parent=self.root,
            ):
                return
            self.close_requested = True
            self.status_var.set("SC2를 종료한 뒤 런처를 닫는 중…")
            self.cancel_event.set()
            self.stop_button.configure(state="disabled")
            self.exit_button.configure(state="disabled")
            return
        self.close_requested = True
        self.root.destroy()


def main() -> None:
    # start_custom_ai_test.cmd passes --test. Test mode is a separate entry point
    # rather than a checkbox so a cheated game can never be started by accident
    # from the normal launcher, and so it can use its own map file.
    test_mode = "--test" in sys.argv[1:]
    root = tk.Tk()
    CustomLauncherApp(root, test_mode=test_mode)
    root.mainloop()


if __name__ == "__main__":
    main()
