from __future__ import annotations

import asyncio
import json
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Callable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
for extra in (PROJECT_ROOT, PROJECT_ROOT / "v3"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from sc2team.custom_config import (  # noqa: E402
    CONTROLLERS,
    DEFAULT_BUILD_BY_RACE,
    PROTOSS_FACTIONS,
    RACES,
    TEAM_MODE_LABELS,
    TEAM_REGION_LABELS,
    CustomLauncherConfig,
    SlotConfig,
    team_for_slot,
    team_label_for_slot,
)
from sc2team.custom_runtime import (  # noqa: E402
    RACE_VALUES,
    player_setups,
    runtime_player_id,
)
from sc2team.live_observe import DEFAULT_PORT as OBSERVE_PORT, LiveObserveBridge  # noqa: E402
from sc2team.process import discover_sc2_executable, launch_sc2, stop_process  # noqa: E402
from sc2team.protocol import Sc2Connection  # noqa: E402
from sc2team_v3.config import (  # noqa: E402
    V3_DEFAULT_BUILD_BY_RACE,
    V3_GROUND_BUILDS,
    V3BuildConfig,
)
from sc2team_v3.runtime import build_v3_map, install_v3_mod  # noqa: E402


APP_VERSION = "3.2.0"
BASE_MAP_FILE = (
    PROJECT_ROOT
    / "maps"
    / "generated"
    / "europe-melee-2-7v7-rich-50000-fixed-teams.SC2Map"
)
RUNTIME_MAP_FILE = PROJECT_ROOT / "runtime" / "maps" / "europe-melee-v3-ground.SC2Map"
SETTINGS_FILE = PROJECT_ROOT / "runtime" / "v3_launcher_settings.json"
PORT = 14180

TEAM_SECTION_COLORS: dict[int, tuple[str, str]] = {
    1: ("#203d61", "#cce6ff"),
    2: ("#643333", "#ffd6d2"),
    3: ("#30533a", "#d5f6dc"),
    4: ("#563665", "#efd7ff"),
}


def _default_state() -> tuple[CustomLauncherConfig, dict[int, str]]:
    active_ai = {2, 3, 4, 8, 9, 10, 11}
    race_order = ("Terran", "Protoss", "Zerg")
    slots: list[SlotConfig] = []
    builds: dict[int, str] = {}
    ai_index = 0
    for slot_id in range(1, 15):
        if slot_id == 1:
            controller = "human"
            race = "Terran"
        elif slot_id in active_ai:
            controller = "custom_ai"
            race = race_order[ai_index % len(race_order)]
            ai_index += 1
            builds[slot_id] = V3_DEFAULT_BUILD_BY_RACE[race]
        else:
            controller = "empty"
            race = "Random"
        slots.append(
            SlotConfig(
                slot=slot_id,
                controller=controller,
                team=team_for_slot(slot_id, 2),
                race=race,
                build=DEFAULT_BUILD_BY_RACE[race],
                melee_build="Macro" if controller == "custom_ai" else "",
            )
        )
    config = CustomLauncherConfig(
        version=1,
        slots=tuple(slots),
        allow_support_air=False,
        unit_control=False,
    )
    config.validate()
    return config, builds


async def run_v3_game(
    config: CustomLauncherConfig,
    builds: dict[int, str],
    cancel_event: threading.Event,
    status: Callable[[str], None],
    *,
    observer: bool = False,
    live_observe: bool = False,
    command_card: bool = False,
) -> str:
    config.validate()
    v3_config = V3BuildConfig(
        campaign_units=True,
        player_builds=tuple(sorted(builds.items())),
    )
    v3_config.validate()
    status("검증된 V3 커스텀 AI와 맵을 빌드하는 중…")
    runtime_map = build_v3_map(
        PROJECT_ROOT,
        BASE_MAP_FILE,
        RUNTIME_MAP_FILE,
        config,
        v3_config,
        observer_mode=observer,
        active_config_file=RUNTIME_MAP_FILE.with_suffix(".json"),
    )
    executable = discover_sc2_executable()
    installed = install_v3_mod(PROJECT_ROOT, executable.parents[2])
    status(f"V3 커스텀 AI 설치 완료: {installed.name} — SC2 연결 중…")
    process = launch_sc2(
        executable, PORT, 0, width=1280, height=720, fullscreen=config.fullscreen
    )
    connection: Sc2Connection | None = None
    bridge: LiveObserveBridge | None = None
    try:
        connection = await Sc2Connection.open(PORT)
        version = await connection.ping()
        await connection.create_game_with_setups(
            runtime_map.name,
            runtime_map.read_bytes(),
            player_setups(config, observer=observer),
            realtime=True,
        )
        if observer:
            await connection.join_as_observer("V3 Observer", command_card=command_card)
        else:
            player_id = await connection.join_game(
                RACE_VALUES[config.human.race],
                f"P{config.human.slot} Local Human",
                None,
                command_card=command_card,
            )
            expected = runtime_player_id(config, config.human.slot)
            if player_id != expected:
                raise RuntimeError(
                    f"사람 슬롯 매핑 실패: 내부 P{expected}가 아니라 P{player_id}로 참가했습니다."
                )
        if live_observe:
            try:
                bridge = LiveObserveBridge(port=OBSERVE_PORT, log=status)
                await bridge.start()
            except OSError as error:
                # 브리지는 진단 보조다. 포트가 이미 잡혀 있다는 이유로 게임 실행
                # 자체를 실패시키지 않는다.
                bridge = None
                status(f"라이브 관측 브리지를 열지 못했습니다({error}). 게임은 그대로 진행합니다.")
        status(
            f"SC2 {version.game_version} — V3 지상군 정책 적용 완료. "
            + (
                f"옵저버 모드: P{config.human.slot}까지 AI가 플레이합니다."
                if observer
                else "생산·테크·확장·출격은 맵 내부 V3 Galaxy 정책이 담당합니다."
            )
            + (f" 라이브 관측: {bridge.url}" if bridge is not None else "")
        )
        while not cancel_event.is_set() and process.poll() is None:
            started = time.perf_counter()
            observation = await connection.observation(disable_fog=True)
            roundtrip_ms = (time.perf_counter() - started) * 1000.0
            if bridge is not None:
                # 브리지는 이 관측을 재사용만 한다. 조회 요청마다 새 관측을 뜨면
                # realtime 게임의 프레임을 갉아먹는다.
                bridge.publish(observation, roundtrip_ms=roundtrip_ms)
            if observation.player_result:
                return "V3 게임이 종료되었습니다."
            await asyncio.sleep(1.0)
        if cancel_event.is_set():
            return "사용자가 V3 게임을 종료했습니다."
        return "SC2 창이 닫혔습니다."
    finally:
        if bridge is not None:
            await bridge.stop()
        if connection is not None:
            try:
                await connection.quit()
            finally:
                await connection.close()
        stop_process(process)


class SlotRow:
    def __init__(self, app: "V3LauncherApp", parent: tk.Widget, slot: SlotConfig, build: str | None) -> None:
        self.app = app
        self.slot_id = slot.slot
        self.build_id = build
        self._changing = False
        self.slot_label = tk.Label(
            parent,
            text=f"P{slot.slot}",
            bg="#111a28",
            fg="#f4f7fb",
            width=5,
        )
        self.team_label = tk.Label(parent, bg="#111a28", fg="#90a4bf", width=12)
        self.controller_var = tk.StringVar(value=CONTROLLERS[slot.controller])
        self.controller_box = ttk.Combobox(parent, textvariable=self.controller_var, values=list(CONTROLLERS.values()), state="readonly", width=12)
        self.race_var = tk.StringVar(value=RACES[slot.race])
        self.race_box = ttk.Combobox(parent, textvariable=self.race_var, values=list(RACES.values()), state="readonly", width=12)
        self.build_var = tk.StringVar()
        self.build_box = ttk.Combobox(parent, textvariable=self.build_var, state="readonly", width=39)
        self.controller_box.bind("<<ComboboxSelected>>", self._controller_changed)
        self.race_box.bind("<<ComboboxSelected>>", self._race_changed)
        self.build_box.bind("<<ComboboxSelected>>", self._build_changed)
        self.refresh()

    def grid(self, row: int) -> None:
        self.slot_label.grid(row=row, column=0, pady=2, sticky="ew")
        self.team_label.grid(row=row, column=1, pady=2, sticky="ew")
        self.controller_box.grid(row=row, column=2, padx=3, pady=2, sticky="ew")
        self.race_box.grid(row=row, column=3, padx=3, pady=2, sticky="ew")
        self.build_box.grid(
            row=row,
            column=4,
            padx=(3, 7),
            pady=2,
            sticky="ew",
        )

    @property
    def controller(self) -> str:
        return next(key for key, value in CONTROLLERS.items() if value == self.controller_var.get())

    @property
    def race(self) -> str:
        return next(key for key, value in RACES.items() if value == self.race_var.get())

    def _controller_changed(self, _event=None) -> None:
        if not self._changing:
            self.app.on_controller_changed(self)
        self.refresh()

    def _race_changed(self, _event=None) -> None:
        self.build_id = V3_DEFAULT_BUILD_BY_RACE.get(self.race)
        self.refresh()

    def _build_changed(self, _event=None) -> None:
        builds = V3_GROUND_BUILDS.get(self.race, {})
        self.build_id = next((key for key, label in builds.items() if label == self.build_var.get()), None)

    def refresh(self) -> None:
        self.team_label.configure(
            text=team_label_for_slot(self.slot_id, self.app.team_mode)
        )
        active = self.controller != "empty"
        ai = self.controller == "custom_ai" or (
            self.controller == "human" and self.app.observer_var.get()
        )
        self.race_box.configure(state="readonly" if active else "disabled")
        builds = V3_GROUND_BUILDS.get(self.race, {})
        if ai and self.build_id not in builds:
            self.build_id = V3_DEFAULT_BUILD_BY_RACE.get(self.race)
        self.build_box.configure(values=list(builds.values()))
        self.build_var.set(builds.get(self.build_id, "종족을 먼저 선택하세요" if ai else "—"))
        self.build_box.configure(state="readonly" if ai and builds else "disabled")

    def set_controller(self, controller: str) -> None:
        self.controller_var.set(CONTROLLERS[controller])
        self.refresh()

    def set_enabled(self, enabled: bool) -> None:
        self.controller_box.configure(state="readonly" if enabled else "disabled")
        if enabled:
            self.refresh()
        else:
            self.race_box.configure(state="disabled")
            self.build_box.configure(state="disabled")

    def to_slot(self) -> SlotConfig:
        return SlotConfig(
            slot=self.slot_id,
            controller=self.controller,
            team=team_for_slot(self.slot_id, self.app.team_mode),
            race=self.race,
            build=DEFAULT_BUILD_BY_RACE[self.race],
            melee_build="Macro" if self.controller == "custom_ai" else "",
        )


class V3LauncherApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(f"SC2 V3 Ground AI v{APP_VERSION}")
        self.root.geometry("1040x920")
        self.root.minsize(940, 820)
        self.root.configure(bg="#08101d")
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self.running = False
        self.close_requested = False
        self.cancel_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.rows: list[SlotRow] = []
        self.observer_var = tk.BooleanVar(value=False)
        # 진단용 옵트인. 기본은 꺼짐 — 평소 플레이는 지금과 완전히 동일해야 한다.
        self.live_observe_var = tk.BooleanVar(value=False)
        self.command_card_var = tk.BooleanVar(value=False)
        self._style()
        config, builds = self._load()
        self.team_mode_var = tk.StringVar(value=TEAM_MODE_LABELS[config.team_mode])
        self._build_ui(config, builds)

    @property
    def team_mode(self) -> int:
        selected = self.team_mode_var.get()
        return next(
            mode for mode, label in TEAM_MODE_LABELS.items() if label == selected
        )

    def _style(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TCombobox", fieldbackground="#17243a", background="#17243a", foreground="#f4f7fb", arrowcolor="#8ec5ff", padding=4)
        style.map("TCombobox", fieldbackground=[("readonly", "#17243a"), ("disabled", "#101827")], foreground=[("readonly", "#f4f7fb"), ("disabled", "#6e7c90")])

    def _build_ui(self, config: CustomLauncherConfig, builds: dict[int, str]) -> None:
        header = tk.Frame(self.root, bg="#08101d")
        header.pack(fill="x", padx=22, pady=(16, 8))
        tk.Label(header, text="V3 지상군 AI", bg="#08101d", fg="#f6fbff", font=("Malgun Gothic", 21, "bold")).pack(anchor="w")
        tk.Label(header, text="각 AI 슬롯에서 확정한 종족별 2개 빌드를 선택합니다. 캠페인 유닛 포함 · 공중 전투 빌드 제외", bg="#08101d", fg="#90a4bf", font=("Malgun Gothic", 10)).pack(anchor="w")
        team_controls = tk.Frame(header, bg="#08101d")
        team_controls.pack(fill="x", pady=(8, 0))
        tk.Label(
            team_controls,
            text="팀 구성",
            bg="#08101d",
            fg="#d6e3f3",
            font=("Malgun Gothic", 10, "bold"),
        ).pack(side="left", padx=(0, 8))
        self.team_mode_box = ttk.Combobox(
            team_controls,
            textvariable=self.team_mode_var,
            values=list(TEAM_MODE_LABELS.values()),
            state="readonly",
            width=42,
        )
        self.team_mode_box.pack(side="left")
        self.team_mode_box.bind("<<ComboboxSelected>>", self._team_mode_changed)
        self.table = tk.Frame(self.root, bg="#111a28", highlightbackground="#2b4667", highlightthickness=1)
        self.table.pack(fill="both", expand=True, padx=22, pady=6)
        for column, (heading, width) in enumerate(zip(("슬롯", "위치·팀", "플레이어", "종족", "V3 지상군 빌드"), (5, 12, 13, 13, 40))):
            tk.Label(self.table, text=heading, width=width, bg="#1a2a40", fg="#bcd7f5", font=("Malgun Gothic", 9, "bold"), pady=7).grid(row=0, column=column, sticky="ew")
            self.table.grid_columnconfigure(column, weight=3 if column == 4 else 1)
        self.team_section_labels: dict[int, tk.Label] = {}
        for team in range(1, 5):
            background, foreground = TEAM_SECTION_COLORS[team]
            self.team_section_labels[team] = tk.Label(
                self.table,
                bg=background,
                fg=foreground,
                anchor="w",
                padx=10,
                pady=4,
                font=("Malgun Gothic", 10, "bold"),
            )
        for slot in config.slots:
            self.rows.append(SlotRow(self, self.table, slot, builds.get(slot.slot)))
        self._layout_team_sections()
        options = tk.Frame(self.root, bg="#08101d")
        options.pack(fill="x", padx=22, pady=4)
        self.full_vision_var = tk.BooleanVar(value=config.full_vision)
        self.wild_zerg_var = tk.BooleanVar(value=config.wild_zerg)
        self.fullscreen_var = tk.BooleanVar(value=config.fullscreen)
        self.faction_var = tk.StringVar(value=PROTOSS_FACTIONS[config.protoss_faction])
        for label, variable in (("사람 전체 시야", self.full_vision_var), ("야생 저그 활성화", self.wild_zerg_var), ("전체 화면", self.fullscreen_var)):
            tk.Checkbutton(options, text=label, variable=variable, bg="#08101d", fg="#d6e3f3", selectcolor="#17243a", activebackground="#08101d", activeforeground="#fff").pack(side="left", padx=(0, 18))
        tk.Label(options, text="프로토스 전역 진영", bg="#08101d", fg="#d6e3f3").pack(side="left", padx=(8, 6))
        self.faction_box = ttk.Combobox(options, textvariable=self.faction_var, values=list(PROTOSS_FACTIONS.values()), state="readonly", width=13)
        self.faction_box.pack(side="left")
        observer_options = tk.Frame(self.root, bg="#08101d")
        observer_options.pack(fill="x", padx=22, pady=(2, 4))
        self.observer_check = tk.Checkbutton(
            observer_options,
            text="옵저버 모드 (사람 슬롯도 V3 AI가 플레이)",
            variable=self.observer_var,
            command=self._observer_changed,
            bg="#08101d",
            fg="#ffcf8a",
            selectcolor="#17243a",
            activebackground="#08101d",
            activeforeground="#ffffff",
            font=("Malgun Gothic", 9, "bold"),
        )
        self.observer_check.pack(side="left")
        diagnostics = tk.Frame(self.root, bg="#08101d")
        diagnostics.pack(fill="x", padx=22, pady=(2, 4))
        self.live_observe_check = tk.Checkbutton(
            diagnostics,
            text=f"라이브 관측 브리지 (127.0.0.1:{OBSERVE_PORT}, 읽기 전용)",
            variable=self.live_observe_var,
            command=self._live_observe_changed,
            bg="#08101d",
            fg="#9ee8c0",
            selectcolor="#17243a",
            activebackground="#08101d",
            activeforeground="#ffffff",
        )
        self.live_observe_check.pack(side="left", padx=(0, 18))
        self.command_card_check = tk.Checkbutton(
            diagnostics,
            text="명령카드 계측 (ui_data·abilities)",
            variable=self.command_card_var,
            bg="#08101d",
            fg="#9ee8c0",
            selectcolor="#17243a",
            activebackground="#08101d",
            activeforeground="#ffffff",
        )
        self.command_card_check.pack(side="left")
        self._live_observe_changed()
        footer = tk.Frame(self.root, bg="#08101d")
        footer.pack(fill="x", padx=22, pady=(6, 15))
        self.status_var = tk.StringVar(value="AI 슬롯의 종족과 V3 빌드를 선택하세요.")
        tk.Label(footer, textvariable=self.status_var, bg="#08101d", fg="#9fb0c7", anchor="w").pack(side="left", fill="x", expand=True)
        self.start_button = tk.Button(footer, text="V3 게임 시작", command=self._start, bg="#1674b9", fg="#fff", relief="flat", padx=16, pady=8)
        self.start_button.pack(side="right", padx=(8, 0))
        self.stop_button = tk.Button(footer, text="게임 종료", command=self._stop, state="disabled", bg="#713a3a", fg="#fff", relief="flat", padx=12, pady=8)
        self.stop_button.pack(side="right")

    def on_controller_changed(self, changed: SlotRow) -> None:
        if changed.controller == "human":
            for row in self.rows:
                if row is not changed and row.controller == "human":
                    row.set_controller("empty")

    def _layout_team_sections(self) -> None:
        for label in self.team_section_labels.values():
            label.grid_remove()

        rows_by_slot = {row.slot_id: row for row in self.rows}
        grid_row = 1
        for team in range(1, self.team_mode + 1):
            slot_ids = tuple(
                slot
                for slot in range(1, 15)
                if team_for_slot(slot, self.team_mode) == team
            )
            region = TEAM_REGION_LABELS[self.team_mode][team]
            section = self.team_section_labels[team]
            section.configure(
                text=(
                    f"{team}팀 · {region}  |  "
                    + ", ".join(f"P{slot}" for slot in slot_ids)
                    + f"  ({len(slot_ids)}개 슬롯)"
                )
            )
            section.grid(
                row=grid_row,
                column=0,
                columnspan=5,
                padx=1,
                pady=(5 if grid_row > 1 else 2, 1),
                sticky="ew",
            )
            grid_row += 1
            for slot in slot_ids:
                rows_by_slot[slot].grid(grid_row)
                grid_row += 1

    def _team_mode_changed(self, _event=None) -> None:
        for row in self.rows:
            row.refresh()
        self._layout_team_sections()
        self.status_var.set(
            f"팀 구성을 {TEAM_MODE_LABELS[self.team_mode]} 모드로 변경했습니다."
        )

    def _live_observe_changed(self) -> None:
        # 명령카드 계측은 브리지로만 읽을 수 있으므로 브리지가 꺼지면 같이 끈다.
        if not self.live_observe_var.get():
            self.command_card_var.set(False)
        self.command_card_check.configure(
            state="normal" if self.live_observe_var.get() else "disabled"
        )

    def _observer_changed(self) -> None:
        for row in self.rows:
            row.refresh()
        self.status_var.set(
            "옵저버 모드: 사람 슬롯도 선택한 V3 빌드의 컴퓨터로 실행됩니다."
            if self.observer_var.get()
            else "일반 모드: 사람 슬롯으로 직접 플레이합니다."
        )

    def _current(self) -> tuple[CustomLauncherConfig, dict[int, str]]:
        slots = tuple(row.to_slot() for row in self.rows)
        config = CustomLauncherConfig(
            version=1,
            slots=slots,
            full_vision=self.full_vision_var.get(),
            allow_support_air=False,
            protoss_faction=next(key for key, label in PROTOSS_FACTIONS.items() if label == self.faction_var.get()),
            wild_zerg=self.wild_zerg_var.get(),
            unit_control=False,
            fullscreen=self.fullscreen_var.get(),
        )
        config.validate()
        builds: dict[int, str] = {}
        for row in self.rows:
            is_v3_ai = row.controller == "custom_ai" or (
                self.observer_var.get() and row.controller == "human"
            )
            if not is_v3_ai:
                continue
            if row.race == "Random" or row.build_id not in V3_GROUND_BUILDS.get(row.race, {}):
                raise ValueError(f"P{row.slot_id}: V3 AI는 종족과 세부 빌드를 직접 선택해야 합니다.")
            builds[row.slot_id] = row.build_id
        return config, builds

    def _load(self) -> tuple[CustomLauncherConfig, dict[int, str]]:
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            self.observer_var.set(bool(data.get("observer_mode", False)))
            self.live_observe_var.set(bool(data.get("live_observe", False)))
            self.command_card_var.set(bool(data.get("command_card", False)))
            return CustomLauncherConfig.from_dict(data["launcher"]), {int(key): str(value) for key, value in data["builds"].items()}
        except (FileNotFoundError, OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            self.observer_var.set(False)
            self.live_observe_var.set(False)
            self.command_card_var.set(False)
            return _default_state()

    def _save(self, config: CustomLauncherConfig, builds: dict[int, str]) -> None:
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(
            json.dumps(
                {
                    "version": 2,
                    "launcher": config.to_dict(),
                    "builds": builds,
                    "observer_mode": self.observer_var.get(),
                    "live_observe": self.live_observe_var.get(),
                    "command_card": self.command_card_var.get(),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def _set_enabled(self, enabled: bool) -> None:
        for row in self.rows:
            row.set_enabled(enabled)
        self.team_mode_box.configure(state="readonly" if enabled else "disabled")
        self.faction_box.configure(state="readonly" if enabled else "disabled")
        self.observer_check.configure(state="normal" if enabled else "disabled")
        self.live_observe_check.configure(state="normal" if enabled else "disabled")
        self.command_card_check.configure(
            state="normal" if enabled and self.live_observe_var.get() else "disabled"
        )
        self.start_button.configure(state="normal" if enabled else "disabled")
        self.stop_button.configure(state="disabled" if enabled else "normal")

    def _start(self) -> None:
        if self.running:
            return
        try:
            config, builds = self._current()
            self._save(config, builds)
        except Exception as error:
            messagebox.showerror("V3 설정 오류", str(error), parent=self.root)
            return
        self.running = True
        observer = self.observer_var.get()
        live_observe = self.live_observe_var.get()
        command_card = live_observe and self.command_card_var.get()
        self.cancel_event.clear()
        self._set_enabled(False)

        def status(message: str) -> None:
            self.root.after(0, self.status_var.set, message)

        def worker() -> None:
            try:
                result = asyncio.run(
                    run_v3_game(
                        config,
                        builds,
                        self.cancel_event,
                        status,
                        observer=observer,
                        live_observe=live_observe,
                        command_card=command_card,
                    )
                )
                self.root.after(0, self._finished, result, None)
            except Exception as error:
                self.root.after(0, self._finished, "V3 실행 실패", error)

        self.worker = threading.Thread(target=worker, name="sc2-v3-launcher", daemon=True)
        self.worker.start()

    def _stop(self) -> None:
        self.status_var.set("V3 게임을 종료하는 중…")
        self.cancel_event.set()
        self.stop_button.configure(state="disabled")

    def _finished(self, result: str, error: Exception | None) -> None:
        self.running = False
        if self.close_requested:
            self.root.destroy()
            return
        self._set_enabled(True)
        self.status_var.set(result if error is None else f"실행 실패: {error}")
        if error is not None:
            messagebox.showerror("V3 실행 실패", str(error), parent=self.root)

    def _close(self) -> None:
        if self.close_requested:
            return
        if self.running:
            if not messagebox.askyesno("게임 종료", "SC2를 종료하고 런처를 닫을까요?", parent=self.root):
                return
            self.close_requested = True
            self.status_var.set("SC2를 종료한 뒤 V3 런처를 닫는 중…")
            self.cancel_event.set()
            return
        self.close_requested = True
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    V3LauncherApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
