from __future__ import annotations

import asyncio
import json
import sys
import threading
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
    CustomLauncherConfig,
    SlotConfig,
)
from sc2team.custom_runtime import (  # noqa: E402
    RACE_VALUES,
    player_setups,
    runtime_player_id,
)
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
                team=1 if slot_id <= 7 else 2,
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
            await connection.join_as_observer("V3 Observer")
        else:
            player_id = await connection.join_game(
                RACE_VALUES[config.human.race],
                f"P{config.human.slot} Local Human",
                None,
            )
            expected = runtime_player_id(config, config.human.slot)
            if player_id != expected:
                raise RuntimeError(
                    f"사람 슬롯 매핑 실패: 내부 P{expected}가 아니라 P{player_id}로 참가했습니다."
                )
        status(
            f"SC2 {version.game_version} — V3 지상군 정책 적용 완료. "
            + (
                f"옵저버 모드: P{config.human.slot}까지 AI가 플레이합니다."
                if observer
                else "생산·테크·확장·출격은 맵 내부 V3 Galaxy 정책이 담당합니다."
            )
        )
        while not cancel_event.is_set() and process.poll() is None:
            observation = await connection.observation(disable_fog=True)
            if observation.player_result:
                return "V3 게임이 종료되었습니다."
            await asyncio.sleep(1.0)
        if cancel_event.is_set():
            return "사용자가 V3 게임을 종료했습니다."
        return "SC2 창이 닫혔습니다."
    finally:
        if connection is not None:
            try:
                await connection.quit()
            finally:
                await connection.close()
        stop_process(process)


class SlotRow:
    def __init__(self, app: "V3LauncherApp", parent: tk.Widget, slot: SlotConfig, row: int, build: str | None) -> None:
        self.app = app
        self.slot_id = slot.slot
        self.build_id = build
        self._changing = False
        team = "1팀·서쪽" if slot.slot <= 7 else "2팀·동쪽"
        tk.Label(parent, text=f"P{slot.slot}", bg="#111a28", fg="#f4f7fb", width=5).grid(row=row, column=0, pady=3, sticky="ew")
        tk.Label(parent, text=team, bg="#111a28", fg="#90a4bf", width=12).grid(row=row, column=1, pady=3, sticky="ew")
        self.controller_var = tk.StringVar(value=CONTROLLERS[slot.controller])
        self.controller_box = ttk.Combobox(parent, textvariable=self.controller_var, values=list(CONTROLLERS.values()), state="readonly", width=12)
        self.controller_box.grid(row=row, column=2, padx=3, pady=3, sticky="ew")
        self.race_var = tk.StringVar(value=RACES[slot.race])
        self.race_box = ttk.Combobox(parent, textvariable=self.race_var, values=list(RACES.values()), state="readonly", width=12)
        self.race_box.grid(row=row, column=3, padx=3, pady=3, sticky="ew")
        self.build_var = tk.StringVar()
        self.build_box = ttk.Combobox(parent, textvariable=self.build_var, state="readonly", width=39)
        self.build_box.grid(row=row, column=4, padx=(3, 7), pady=3, sticky="ew")
        self.controller_box.bind("<<ComboboxSelected>>", self._controller_changed)
        self.race_box.bind("<<ComboboxSelected>>", self._race_changed)
        self.build_box.bind("<<ComboboxSelected>>", self._build_changed)
        self.refresh()

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
            team=1 if self.slot_id <= 7 else 2,
            race=self.race,
            build=DEFAULT_BUILD_BY_RACE[self.race],
            melee_build="Macro" if self.controller == "custom_ai" else "",
        )


class V3LauncherApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(f"SC2 V3 Ground AI v{APP_VERSION}")
        self.root.geometry("1040x820")
        self.root.minsize(940, 720)
        self.root.configure(bg="#08101d")
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self.running = False
        self.close_requested = False
        self.cancel_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.rows: list[SlotRow] = []
        self.observer_var = tk.BooleanVar(value=False)
        self._style()
        config, builds = self._load()
        self._build_ui(config, builds)

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
        table = tk.Frame(self.root, bg="#111a28", highlightbackground="#2b4667", highlightthickness=1)
        table.pack(fill="both", expand=True, padx=22, pady=6)
        for column, (heading, width) in enumerate(zip(("슬롯", "위치·팀", "플레이어", "종족", "V3 지상군 빌드"), (5, 12, 13, 13, 40))):
            tk.Label(table, text=heading, width=width, bg="#1a2a40", fg="#bcd7f5", font=("Malgun Gothic", 9, "bold"), pady=7).grid(row=0, column=column, sticky="ew")
            table.grid_columnconfigure(column, weight=3 if column == 4 else 1)
        for index, slot in enumerate(config.slots, start=1):
            self.rows.append(SlotRow(self, table, slot, index, builds.get(slot.slot)))
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
            return CustomLauncherConfig.from_dict(data["launcher"]), {int(key): str(value) for key, value in data["builds"].items()}
        except (FileNotFoundError, OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            self.observer_var.set(False)
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
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def _set_enabled(self, enabled: bool) -> None:
        for row in self.rows:
            row.set_enabled(enabled)
        self.faction_box.configure(state="readonly" if enabled else "disabled")
        self.observer_check.configure(state="normal" if enabled else "disabled")
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
