"""SC2 Custom AI V2 런처.

V1 과의 차이는 하나다: **밀레 AI 가 게임을 맡고 우리는 보조만 한다.**

빠진 것 (V1 에서 의도적으로 들어냄)
  - 유닛 제어: 출격 브로드캐스트·지원 파견·본진 방어·파이썬 전략 제어기
  - 빌드 강제: `AIBuild` 직접 발주, 생산 규칙, 목표 재고, 캠페인 구매, 연구 트리거
  - 캠페인 유닛 로스터 (구매 Galaxy 가 없으면 밀레 AI 는 모르는 ID 를 무시한다)

남은 것
  - 슬롯·종족·팀 편성, 밀레 빌드 분류, 프로토스 진영, 전체 시야, 야생 저그
  - 인구 상한, 프리셋 저장/불러오기, 리플레이 자동 저장
  - 테스트 모드: 자원 무한 · 즉시 생산 · 전체 시야 · 배속 · 옵저버

더해진 것 (V2 보조 — 각각 껐다 켤 수 있고, 끄면 순수 밀레 AI 다)
  - 확장 보조 `AIExpand`
  - 병력 보조 `AISetStockArmyDefaultScale`
"""

from __future__ import annotations

import asyncio
import json
import sys
import threading
import tkinter as tk
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable

PROJECT_ROOT = Path(__file__).resolve().parents[2]
for extra in (PROJECT_ROOT, PROJECT_ROOT / "v2"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from s2clientprotocol import debug_pb2 as debug_pb

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
from sc2team.custom_runtime import RACE_VALUES, player_setups, runtime_player_id
from sc2team.process import discover_sc2_executable, launch_sc2, stop_process
from sc2team.protocol import Sc2Connection
from sc2team_v2.config import (
    ARMY_SCALE_CHOICES,
    EXPANSION_CAP_CHOICES,
    HOLD_RELEASE_CHOICES,
    PRODUCTION_SCALE_CHOICES,
    V2Assist,
)
from sc2team_v2.runtime import build_v2_map


APP_VERSION = "2.0.0"
BASE_MAP_FILE = (
    PROJECT_ROOT
    / "maps"
    / "generated"
    / "europe-melee-2-7v7-rich-50000-fixed-teams.SC2Map"
)
RUNTIME_MAP_FILE = (
    PROJECT_ROOT / "runtime" / "maps" / f"europe-melee-custom-ai-v{APP_VERSION}.SC2Map"
)
# 테스트 모드는 전체 시야를 맵에 구워 넣으므로 실전 맵을 덮어쓰면 안 된다.
TEST_MAP_FILE = (
    PROJECT_ROOT
    / "runtime"
    / "maps"
    / f"europe-melee-custom-ai-v{APP_VERSION}-test.SC2Map"
)
# V1 의 runtime/custom_ai_settings.json 과 **별도 파일**이다. V2 런처가 V1
# 설정을 덮어쓰면 안 된다.
SETTINGS_FILE = PROJECT_ROOT / "runtime" / "custom_ai_v2_settings.json"
REPLAY_DIR = PROJECT_ROOT / "runtime" / "replays"
REPLAY_SNAPSHOT_SECONDS = 60

# 테스트 치트 상수는 V1 과 같다(실측값이라 바꿀 이유가 없다).
TEST_RESOURCE_FLOOR = 5_000
TEST_RESOURCE_GRANTS_ON_JOIN = 2
GAME_LOOPS_PER_SECOND = 22.4
STEP_TICK_SECONDS = 0.5
TEST_SPEED_CHOICES = (1, 2, 4, 8, 16)

PORT = 14100


async def run_v2_game(
    config: CustomLauncherConfig,
    assist: V2Assist,
    cancel_event: threading.Event,
    status: Callable[[str], None],
    *,
    test_mode: bool = False,
    speed: int = 1,
    observer: bool = False,
) -> str:
    if not test_mode:
        speed = 1
        observer = False
    if observer:
        # 옵저버 모드에서 사람 슬롯은 컴퓨터가 되므로 종족에 유효한 빌드가
        # 필요하다(빌드 이름 → 밀레 빌드 분류 매핑에 쓰인다).
        human = config.human
        if human.build not in GROUND_BUILDS[human.race]:
            fixed = replace(human, build=DEFAULT_BUILD_BY_RACE[human.race])
            config = replace(
                config,
                slots=tuple(
                    fixed if slot.slot == human.slot else slot for slot in config.slots
                ),
            )
    if test_mode:
        config = replace(config, full_vision=True)
    config.validate()
    assist.validate()
    if not BASE_MAP_FILE.is_file():
        raise FileNotFoundError(f"기준 맵을 찾을 수 없습니다: {BASE_MAP_FILE}")

    status("선택한 슬롯으로 V2 실행용 맵을 생성하는 중…")
    output_map = TEST_MAP_FILE if test_mode else RUNTIME_MAP_FILE
    runtime_map = build_v2_map(
        PROJECT_ROOT,
        BASE_MAP_FILE,
        output_map,
        config,
        assist,
        observer_mode=observer,
        active_config_file=output_map.with_suffix(".json"),
    )

    executable = discover_sc2_executable()
    process = launch_sc2(
        executable, PORT, 0, width=1280, height=720, fullscreen=config.fullscreen
    )
    connection: Sc2Connection | None = None
    result_text = "V2 게임이 종료되었습니다."

    try:
        status("SC2 API 연결을 기다리는 중…")
        connection = await Sc2Connection.open(PORT)
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
                status(
                    f"[테스트·옵저버] P{config.human.slot} 슬롯까지 전부 AI가 "
                    f"플레이합니다{speed_note}. {assist.summary()}. 관전 중…"
                )
            else:
                await connection.debug_game_state(debug_pb.fast_build)
                await connection.debug_game_state(debug_pb.food)
                await connection.debug_game_state(debug_pb.show_map)
                for _ in range(TEST_RESOURCE_GRANTS_ON_JOIN):
                    await connection.debug_game_state(debug_pb.all_resources)
                status(
                    f"[테스트] 위치 P{config.human.slot} 배치 성공 (게임 내부 "
                    f"P{player_id}). 자원 무한, 즉시 생산, 전체 시야{speed_note}. "
                    f"{assist.summary()}."
                )
        else:
            status(
                f"위치 P{config.human.slot} 배치 성공 (게임 내부 P{player_id}). "
                f"밀레 AI가 게임을 맡고 있습니다 — {assist.summary()}."
            )

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
                status(f"리플레이 저장 실패({reason}): {error}")
                return False

        clock = asyncio.get_running_loop().time
        next_snapshot = clock() + REPLAY_SNAPSHOT_SECONDS
        loops_per_batch = max(
            1, round(GAME_LOOPS_PER_SECOND * speed * STEP_TICK_SECONDS)
        )
        while not cancel_event.is_set() and process.poll() is None:
            tick_started = clock()
            if speed > 1:
                await connection.step(loops_per_batch)
            observation = await connection.observation(disable_fog=True)
            if observation.player_result:
                result_text = "SC2 게임이 종료되었습니다."
                if await save_replay_snapshot("게임 종료"):
                    result_text += f" 리플레이: {replay_file.name}"
                break
            if test_mode and not observer:
                # all_resources 는 5000/5000 일회성 지급이라 소비가 앞서면
                # 바닥난다. 바닥 아래로 떨어질 때마다 다시 채운다.
                bank = observation.observation.player_common
                if min(bank.minerals, bank.vespene) < TEST_RESOURCE_FLOOR:
                    await connection.debug_game_state(debug_pb.all_resources)
            if clock() >= next_snapshot:
                next_snapshot = clock() + REPLAY_SNAPSHOT_SECONDS
                await save_replay_snapshot("주기 저장")
            wait = (STEP_TICK_SECONDS if speed > 1 else 1.0) - (clock() - tick_started)
            await asyncio.sleep(max(0.02, wait))

        if cancel_event.is_set():
            result_text = "사용자가 V2 게임을 종료했습니다."
            if await save_replay_snapshot("사용자 종료"):
                result_text += f" 리플레이: {replay_file.name}"
        elif process.poll() is not None:
            result_text = "SC2 창이 닫혔습니다."
        return result_text
    finally:
        if connection is not None:
            await connection.quit()
            await connection.close()
        stop_process(process)


class SlotRow:
    def __init__(
        self,
        app: "V2LauncherApp",
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

        # V2 는 이 빌드로 생산을 강제하지 않는다. 밀레 빌드가 "자동"일 때
        # 어느 분류(러시/타이밍/…)를 로비에 넘길지 정하는 데만 쓰인다.
        self.build_var = tk.StringVar()
        self.build_box = ttk.Combobox(
            parent, textvariable=self.build_var, state="readonly", width=28,
        )
        self.build_box.grid(row=row, column=4, padx=3, pady=4, sticky="ew")

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


class V2LauncherApp:
    def __init__(self, root: tk.Tk, *, test_mode: bool = False) -> None:
        self.root = root
        self.test_mode = test_mode
        suffix = " [테스트 모드]" if test_mode else ""
        self.root.title(f"SC2 Custom AI V2 v{APP_VERSION}{suffix}")
        # 보조 줄이 두 개라 V1 보다 세로가 더 필요하다. 아래쪽 우선 배치와
        # 함께 두 겹으로 막는다.
        self.root.geometry("1120x1000")
        self.root.minsize(960, 700)
        self.root.configure(bg="#08101d")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.rows: list[SlotRow] = []
        self.running = False
        self.close_requested = False
        self.cancel_event = threading.Event()
        self.worker: threading.Thread | None = None
        self._configure_style()
        config, assist = self._load_settings()
        self._build_ui(config, assist)

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

    def _build_ui(self, config: CustomLauncherConfig, assist: V2Assist) -> None:
        header = tk.Frame(self.root, bg="#08101d")
        header.pack(fill="x", padx=22, pady=(18, 10))
        tk.Label(
            header, text=f"유럽 섬멸전 Custom AI V2 v{APP_VERSION}",
            bg="#08101d", fg="#f6fbff", font=("Malgun Gothic", 21, "bold"),
        ).pack(anchor="w")
        tk.Label(
            header,
            text=(
                "V2 — 블리자드 밀레 AI가 게임을 맡습니다. 우리 레이어는 확장·병력 "
                "보조만 하고, 유닛 제어와 빌드 강제는 없습니다."
            ),
            bg="#08101d", fg="#8fd0a4", font=("Malgun Gothic", 10),
        ).pack(anchor="w", pady=(4, 0))
        if self.test_mode:
            tk.Label(
                header,
                text=(
                    "테스트 모드 — 자원 무한 · 즉시 생산 · 전체 시야가 사람 "
                    "플레이어에게 적용됩니다. 실제 밸런스 확인용이 아닙니다."
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
            self.root, bg="#111a28", highlightbackground="#2b4667",
            highlightthickness=1,
        )
        # table.pack 은 이 함수 끝에서 한다. pack 은 공간이 모자라면 **나중에
        # packed 된 위젯부터** 찌그러뜨리므로, 하단 옵션·버튼을 먼저 자리잡게 하고
        # 표가 남은 공간을 먹어야 창이 작아도 버튼이 안 깨진다(사용자 보고).
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

        # ── 공통 옵션 ─────────────────────────────────────────────────
        options = tk.Frame(self.root, bg="#08101d")
        self.full_vision_var = tk.BooleanVar(value=config.full_vision)
        self.support_air_var = tk.BooleanVar(value=config.allow_support_air)
        self.wild_zerg_var = tk.BooleanVar(value=config.wild_zerg)
        self.fullscreen_var = tk.BooleanVar(value=config.fullscreen)
        self.protoss_faction_var = tk.StringVar(
            value=PROTOSS_FACTIONS[config.protoss_faction]
        )
        tk.Checkbutton(
            options, text="사람에게 전체 지도 시야 제공 (테스트)",
            variable=self.full_vision_var, bg="#08101d", fg="#d6e3f3",
            selectcolor="#17243a", activebackground="#08101d",
            activeforeground="#ffffff", font=("Malgun Gothic", 9),
        ).pack(side="left")
        tk.Checkbutton(
            options, text="수송·탐지 지원 공중 유닛 허용",
            variable=self.support_air_var, bg="#08101d", fg="#d6e3f3",
            selectcolor="#17243a", activebackground="#08101d",
            activeforeground="#ffffff", font=("Malgun Gothic", 9),
        ).pack(side="left", padx=(20, 0))
        tk.Checkbutton(
            options, text="야생 저그 활성화", variable=self.wild_zerg_var,
            bg="#08101d", fg="#d6e3f3", selectcolor="#17243a",
            activebackground="#08101d", activeforeground="#ffffff",
            font=("Malgun Gothic", 9),
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

        # ── V2 보조 ───────────────────────────────────────────────────
        # 자기 줄에 둔다. pack(side="left")는 창 너비를 넘치면 줄바꿈이 아니라
        # 아예 그리지 않으므로(V1 §93 옵저버 체크박스 실종 사고) 줄을 나눈다.
        assist_frame = tk.Frame(
            self.root, bg="#0d1a2b", highlightbackground="#27506d",
            highlightthickness=1,
        )
        tk.Label(
            assist_frame, text="V2 보조", bg="#0d1a2b", fg="#8fd0a4",
            font=("Malgun Gothic", 9, "bold"),
        ).pack(side="left", padx=(10, 14), pady=7)

        self.expansion_var = tk.BooleanVar(value=assist.expansion_assist)
        tk.Checkbutton(
            assist_frame, text="확장 보조", variable=self.expansion_var,
            bg="#0d1a2b", fg="#d6e3f3", selectcolor="#17243a",
            activebackground="#0d1a2b", activeforeground="#ffffff",
            font=("Malgun Gothic", 9),
        ).pack(side="left")
        tk.Label(
            assist_frame, text="기지 상한", bg="#0d1a2b", fg="#9fb0c7",
            font=("Malgun Gothic", 9),
        ).pack(side="left", padx=(8, 5))
        self.expansion_cap_var = tk.StringVar(value=str(assist.expansion_cap))
        self.expansion_cap_box = ttk.Combobox(
            assist_frame, textvariable=self.expansion_cap_var,
            values=[str(c) for c in EXPANSION_CAP_CHOICES],
            state="readonly", width=4,
        )
        self.expansion_cap_box.pack(side="left")

        self.army_var = tk.BooleanVar(value=assist.army_assist)
        tk.Checkbutton(
            assist_frame, text="병력 보조", variable=self.army_var,
            bg="#0d1a2b", fg="#d6e3f3", selectcolor="#17243a",
            activebackground="#0d1a2b", activeforeground="#ffffff",
            font=("Malgun Gothic", 9),
        ).pack(side="left", padx=(24, 0))
        tk.Label(
            assist_frame, text="배율", bg="#0d1a2b", fg="#9fb0c7",
            font=("Malgun Gothic", 9),
        ).pack(side="left", padx=(8, 5))
        self.army_scale_var = tk.StringVar(value=f"{assist.army_scale:g}")
        self.army_scale_box = ttk.Combobox(
            assist_frame, textvariable=self.army_scale_var,
            values=[f"{s:g}" for s in ARMY_SCALE_CHOICES],
            state="readonly", width=5,
        )
        self.army_scale_box.pack(side="left")

        # 생산건물 보조. 배율 형태는 아직 실측 전이라 기본 꺼짐이다.
        self.production_var = tk.BooleanVar(value=assist.production_assist)
        tk.Checkbutton(
            assist_frame, text="생산건물 보조", variable=self.production_var,
            bg="#0d1a2b", fg="#d6e3f3", selectcolor="#17243a",
            activebackground="#0d1a2b", activeforeground="#ffffff",
            font=("Malgun Gothic", 9),
        ).pack(side="left", padx=(24, 0))
        tk.Label(
            assist_frame, text="배율", bg="#0d1a2b", fg="#9fb0c7",
            font=("Malgun Gothic", 9),
        ).pack(side="left", padx=(8, 5))
        self.production_scale_var = tk.StringVar(value=f"{assist.production_scale:g}")
        self.production_scale_box = ttk.Combobox(
            assist_frame, textvariable=self.production_scale_var,
            values=[f"{s:g}" for s in PRODUCTION_SCALE_CHOICES],
            state="readonly", width=5,
        )
        self.production_scale_box.pack(side="left")

        # 야생 저그 항목은 **자기 줄**에 둔다. pack(side="left")는 창 너비를
        # 넘치면 줄바꿈이 아니라 아예 안 그리므로(V1 §93 옵저버 체크박스 실종
        # 사고) 네 항목을 한 줄에 몰지 않는다.
        assist_frame2 = tk.Frame(
            self.root, bg="#0d1a2b", highlightbackground="#27506d",
            highlightthickness=1,
        )
        tk.Label(
            assist_frame2, text="야생 저그", bg="#0d1a2b", fg="#8fd0a4",
            font=("Malgun Gothic", 9, "bold"),
        ).pack(side="left", padx=(10, 14), pady=7)
        self.hold_wild_var = tk.BooleanVar(value=assist.hold_wild_units)
        tk.Checkbutton(
            assist_frame2, text="선배치 병력 고정",
            variable=self.hold_wild_var, bg="#0d1a2b", fg="#d6e3f3",
            selectcolor="#17243a", activebackground="#0d1a2b",
            activeforeground="#ffffff", font=("Malgun Gothic", 9),
        ).pack(side="left")
        self.hold_release_var = tk.StringVar(
            value=f"{assist.hold_wild_release_seconds / 60:g}"
        )
        self.hold_release_box = ttk.Combobox(
            assist_frame2, textvariable=self.hold_release_var,
            values=[str(m) for m in HOLD_RELEASE_CHOICES],
            state="readonly", width=4,
        )
        self.hold_release_box.pack(side="left", padx=(8, 3))
        tk.Label(
            assist_frame2, text="분에 해제 (이후 밀레 AI 자율)",
            bg="#0d1a2b", fg="#9fb0c7", font=("Malgun Gothic", 9),
        ).pack(side="left")
        tk.Label(
            assist_frame2,
            text="보조를 전부 끄면 순수 밀레 AI",
            bg="#0d1a2b", fg="#6e8299", font=("Malgun Gothic", 9),
        ).pack(side="left", padx=(20, 10))

        # 캠페인 유닛도 자기 줄에 둔다(위와 같은 이유).
        assist_frame3 = tk.Frame(
            self.root, bg="#0d1a2b", highlightbackground="#27506d",
            highlightthickness=1,
        )
        tk.Label(
            assist_frame3, text="캠페인 유닛", bg="#0d1a2b", fg="#8fd0a4",
            font=("Malgun Gothic", 9, "bold"),
        ).pack(side="left", padx=(10, 14), pady=7)
        self.campaign_units_var = tk.BooleanVar(value=assist.campaign_units)
        tk.Checkbutton(
            assist_frame3, text="로스터·업그레이드 연결",
            variable=self.campaign_units_var, bg="#0d1a2b", fg="#d6e3f3",
            selectcolor="#17243a", activebackground="#0d1a2b",
            activeforeground="#ffffff", font=("Malgun Gothic", 9),
            command=self._on_campaign_toggled,
        ).pack(side="left")
        self.campaign_production_var = tk.BooleanVar(
            value=assist.campaign_production
        )
        self.campaign_production_box = tk.Checkbutton(
            assist_frame3, text="생산 명령",
            variable=self.campaign_production_var, bg="#0d1a2b", fg="#d6e3f3",
            selectcolor="#17243a", activebackground="#0d1a2b",
            activeforeground="#ffffff", font=("Malgun Gothic", 9),
        )
        self.campaign_production_box.pack(side="left", padx=(12, 0))
        tk.Label(
            assist_frame3,
            text="골리앗·프레데터·의무병·애버레이션·토라스크·랩터 진화",
            bg="#0d1a2b", fg="#9fb0c7", font=("Malgun Gothic", 9),
        ).pack(side="left", padx=(14, 10))

        # ── 테스트 전용 ───────────────────────────────────────────────
        self.speed_box: ttk.Combobox | None = None
        self.observer_var = tk.BooleanVar(value=False)
        test_options: tk.Frame | None = None
        if self.test_mode:
            test_options = tk.Frame(self.root, bg="#08101d")
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

        footer = tk.Frame(self.root, bg="#08101d")
        self.status_var = tk.StringVar(
            value="슬롯을 설정한 뒤 V2 게임을 실행할 수 있습니다."
        )
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
            footer, text="게임 종료", command=self._stop_game, state="disabled",
            bg="#713a3a", fg="#ffffff", disabledforeground="#776b6b",
            relief="flat", padx=12, pady=8, cursor="hand2",
        )
        self.stop_button.pack(side="right", padx=(8, 0))
        self.start_button = tk.Button(
            footer, text="V2 게임 시작", command=self._start_game,
            bg="#1a8f5a", fg="#ffffff", activebackground="#22ab6d",
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

        # ── 배치 순서 ────────────────────────────────────────────────
        # 아래쪽부터 side="bottom" 으로 자리를 확정하고, 표를 **맨 마지막에**
        # expand 로 채운다. pack 은 공간이 부족하면 나중에 packed 된 위젯을
        # 잘라내므로, 표를 먼저 packed 하면 하단 버튼이 찌그러진다.
        # 화면이 작아도 버튼과 옵션은 항상 온전히 보이고 표만 줄어든다.
        footer.pack(side="bottom", fill="x", padx=22, pady=(8, 16))
        if test_options is not None:
            test_options.pack(side="bottom", fill="x", padx=24, pady=(6, 2))
        assist_frame3.pack(side="bottom", fill="x", padx=24, pady=(0, 2))
        assist_frame2.pack(side="bottom", fill="x", padx=24, pady=(0, 2))
        assist_frame.pack(side="bottom", fill="x", padx=24, pady=(8, 2))
        options.pack(side="bottom", fill="x", padx=24, pady=(6, 2))
        table.pack(side="top", fill="both", expand=True, padx=22, pady=6)

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
            # V2 는 유닛 제어를 아예 만들지 않는다. melee_only 맵에는 비컨
            # 브리지 자체가 없으므로 켤 수 있는 값이 아니다.
            unit_control=False,
            protoss_faction=next(
                key for key, label in PROTOSS_FACTIONS.items()
                if label == self.protoss_faction_var.get()
            ),
        )
        config.validate()
        return config

    def _current_assist(self) -> V2Assist:
        assist = V2Assist(
            expansion_assist=self.expansion_var.get(),
            expansion_cap=int(self.expansion_cap_var.get()),
            army_assist=self.army_var.get(),
            army_scale=float(self.army_scale_var.get()),
            production_assist=self.production_var.get(),
            production_scale=float(self.production_scale_var.get()),
            hold_wild_units=self.hold_wild_var.get(),
            hold_wild_release_seconds=float(self.hold_release_var.get()) * 60.0,
            campaign_units=self.campaign_units_var.get(),
            # 로스터가 없으면 훈련 명령이 존재하지 않는 유닛을 가리키므로
            # 설정 단계에서 함께 끈다(V2Assist.validate 도 같은 규칙을 건다).
            campaign_production=(
                self.campaign_units_var.get()
                and self.campaign_production_var.get()
            ),
        )
        assist.validate()
        return assist

    def _on_campaign_toggled(self) -> None:
        self.campaign_production_box.configure(
            state="normal" if self.campaign_units_var.get() else "disabled"
        )

    def _apply_settings(
        self, config: CustomLauncherConfig, assist: V2Assist
    ) -> None:
        config.validate()
        assist.validate()
        for row, slot in zip(self.rows, config.slots):
            row.set_slot(slot)
        self.full_vision_var.set(config.full_vision)
        self.support_air_var.set(config.allow_support_air)
        self.wild_zerg_var.set(config.wild_zerg)
        self.protoss_faction_var.set(PROTOSS_FACTIONS[config.protoss_faction])
        self.expansion_var.set(assist.expansion_assist)
        self.expansion_cap_var.set(str(assist.expansion_cap))
        self.army_var.set(assist.army_assist)
        self.army_scale_var.set(f"{assist.army_scale:g}")
        self.production_var.set(assist.production_assist)
        self.production_scale_var.set(f"{assist.production_scale:g}")
        self.hold_wild_var.set(assist.hold_wild_units)
        self.hold_release_var.set(f"{assist.hold_wild_release_seconds / 60:g}")
        self.campaign_units_var.set(assist.campaign_units)
        self.campaign_production_var.set(assist.campaign_production)
        self._on_campaign_toggled()

    @staticmethod
    def _read_settings(path: Path) -> tuple[CustomLauncherConfig, V2Assist]:
        data = json.loads(path.read_text(encoding="utf-8"))
        config = CustomLauncherConfig.from_dict(data)
        assist = V2Assist.from_dict(data.get("v2_assist", {}))
        return config, assist

    def _load_settings(self) -> tuple[CustomLauncherConfig, V2Assist]:
        try:
            return self._read_settings(SETTINGS_FILE)
        except (
            FileNotFoundError, OSError, ValueError, KeyError, TypeError,
            json.JSONDecodeError,
        ):
            return default_custom_config(), V2Assist()

    @staticmethod
    def _write_settings(
        path: Path, config: CustomLauncherConfig, assist: V2Assist
    ) -> None:
        payload = config.to_dict()
        payload["v2_assist"] = assist.to_dict()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _save_preset(self) -> None:
        try:
            config = self._current_config()
            assist = self._current_assist()
        except ValueError as error:
            messagebox.showerror("설정 오류", str(error), parent=self.root)
            return
        selected = filedialog.asksaveasfilename(
            parent=self.root, title="Custom AI V2 프리셋 저장",
            defaultextension=".json", filetypes=[("JSON 프리셋", "*.json")],
            initialdir=PROJECT_ROOT / "presets",
        )
        if selected:
            self._write_settings(Path(selected), config, assist)
            self.status_var.set(f"프리셋을 저장했습니다: {Path(selected).name}")

    def _load_preset(self) -> None:
        selected = filedialog.askopenfilename(
            parent=self.root, title="Custom AI V2 프리셋 불러오기",
            filetypes=[("JSON 프리셋", "*.json")],
            initialdir=PROJECT_ROOT / "presets",
        )
        if not selected:
            return
        try:
            config, assist = self._read_settings(Path(selected))
            self._apply_settings(config, assist)
            self.status_var.set(f"프리셋을 불러왔습니다: {Path(selected).name}")
        except Exception as error:
            messagebox.showerror("프리셋 오류", str(error), parent=self.root)

    def _reset_defaults(self) -> None:
        self._apply_settings(default_custom_config(), V2Assist())
        self.status_var.set("기본 4대4 설정과 기본 보조값을 복원했습니다.")

    def _set_controls_enabled(self, enabled: bool) -> None:
        for row in self.rows:
            row.set_enabled(enabled)
        for button in self.option_buttons:
            button.configure(state="normal" if enabled else "disabled")
        self.start_button.configure(state="normal" if enabled else "disabled")
        self.stop_button.configure(state="disabled" if enabled else "normal")
        state = "readonly" if enabled else "disabled"
        self.protoss_faction_box.configure(state=state)
        self.expansion_cap_box.configure(state=state)
        self.army_scale_box.configure(state=state)
        self.production_scale_box.configure(state=state)
        self.hold_release_box.configure(state=state)
        if self.speed_box is not None:
            self.speed_box.configure(state=state)

    def _start_game(self) -> None:
        if self.running:
            return
        try:
            config = self._current_config()
            assist = self._current_assist()
            self._write_settings(SETTINGS_FILE, config, assist)
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
        self.status_var.set("V2 게임 준비 중…")

        def status(message: str) -> None:
            self.root.after(0, self.status_var.set, message)

        def worker() -> None:
            try:
                result = asyncio.run(
                    run_v2_game(
                        config, assist, self.cancel_event, status,
                        test_mode=self.test_mode, speed=speed, observer=observer,
                    )
                )
                self.root.after(0, self._game_finished, result, None)
            except Exception as error:
                self.root.after(0, self._game_finished, "V2 게임 실행 실패", error)

        self.worker = threading.Thread(target=worker, name="sc2-v2", daemon=True)
        self.worker.start()

    def _stop_game(self) -> None:
        if self.running:
            self.status_var.set("SC2를 종료하는 중…")
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
                "게임 종료", "실행 중인 SC2 게임을 종료하고 런처를 닫을까요?",
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
    # start_custom_ai_v2_test.cmd 가 --test 를 넘긴다. 치트가 걸린 게임이
    # 실전 런처에서 실수로 시작되지 않도록 진입점을 나눈다(V1 과 같은 이유).
    test_mode = "--test" in sys.argv[1:]
    root = tk.Tk()
    V2LauncherApp(root, test_mode=test_mode)
    root.mainloop()


if __name__ == "__main__":
    main()
