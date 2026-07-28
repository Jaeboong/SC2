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
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sc2team.launcher_config import (
    BUILD_LABELS,
    DEFAULT_BUILD_BY_RACE,
    DIFFICULTIES,
    RACES,
    AISelection,
    LauncherConfig,
    build_display,
    build_key,
    default_config,
    difficulty_display,
    difficulty_key,
    race_display,
    race_key,
)
from sc2team.process import discover_sc2_executable, launch_sc2, stop_process
from sc2team.protocol import Sc2Connection


BASE_MAP_FILE = (
    PROJECT_ROOT
    / "map"
    / "source"
    / "europe-melee-2-7v7-rich-50000-fixed-teams.SC2Map"
)
SETTINGS_FILE = PROJECT_ROOT / "runtime" / "launcher_settings.json"


async def run_local_game(
    config: LauncherConfig,
    cancel_event: threading.Event,
    status: Callable[[str], None],
) -> str:
    config.validate()
    if not BASE_MAP_FILE.is_file():
        raise FileNotFoundError(f"최종 맵을 찾을 수 없습니다: {BASE_MAP_FILE}")

    executable = discover_sc2_executable()
    process = launch_sc2(executable, 14100, 0, width=1280, height=720)
    connection: Sc2Connection | None = None
    result_text = "게임이 종료되었습니다."

    try:
        status("SC2를 실행하고 API 연결을 기다리는 중…")
        connection = await Sc2Connection.open(14100)
        version = await connection.ping()
        status(f"SC2 {version.game_version} 연결 완료 — 7대7 게임 생성 중…")

        await connection.create_game(
            BASE_MAP_FILE.name,
            BASE_MAP_FILE.read_bytes(),
            participant_count=1,
            computer_players=config.computer_players(),
            realtime=True,
        )
        player_id = await connection.join_game(
            config.human_race_value,
            "Local Human",
            None,
        )
        status(f"P{player_id}로 참가했습니다. SC2 창에서 플레이하세요.")

        while not cancel_event.is_set() and process.poll() is None:
            observation = await connection.observation()
            if observation.player_result:
                own_result = next(
                    (
                        result.result
                        for result in observation.player_result
                        if result.player_id == player_id
                    ),
                    None,
                )
                names = {1: "승리", 2: "패배", 3: "무승부", 4: "미결정"}
                result_text = f"게임 종료: {names.get(own_result, '결과 확인') }"
                break
            await asyncio.sleep(1.0)

        if cancel_event.is_set():
            result_text = "사용자가 게임을 종료했습니다."
        elif process.poll() is not None:
            result_text = "SC2 창이 닫혔습니다."
        return result_text
    finally:
        if connection is not None:
            await connection.quit()
            await connection.close()
        stop_process(process)


class PlayerRow:
    def __init__(
        self,
        parent: ttk.Frame,
        slot: int,
        team: str,
        selection: AISelection,
        row: int,
    ) -> None:
        self.slot = slot
        self.team = team
        self.build_id = selection.build

        team_color = "#78aef8" if team == "서쪽" else "#ff8b83"
        tk.Label(
            parent,
            text=f"P{slot}",
            bg="#111a28",
            fg="#f4f7fb",
            font=("Malgun Gothic", 10, "bold"),
            width=5,
        ).grid(row=row, column=0, padx=(8, 4), pady=5, sticky="ew")
        tk.Label(
            parent,
            text=team,
            bg="#111a28",
            fg=team_color,
            font=("Malgun Gothic", 10, "bold"),
            width=7,
        ).grid(row=row, column=1, padx=4, pady=5, sticky="ew")
        tk.Label(
            parent,
            text="내장 AI",
            bg="#111a28",
            fg="#c7d2e3",
            font=("Malgun Gothic", 9),
            width=8,
        ).grid(row=row, column=2, padx=4, pady=5, sticky="ew")

        self.race_var = tk.StringVar(value=race_display(selection.race))
        self.race_box = ttk.Combobox(
            parent,
            textvariable=self.race_var,
            values=[label for label, _ in RACES.values()],
            state="readonly",
            width=13,
        )
        self.race_box.grid(row=row, column=3, padx=4, pady=5, sticky="ew")

        self.build_var = tk.StringVar(
            value=build_display(selection.race, selection.build)
        )
        self.build_box = ttk.Combobox(
            parent,
            textvariable=self.build_var,
            state="readonly",
            width=28,
        )
        self.build_box.grid(row=row, column=4, padx=4, pady=5, sticky="ew")

        self.difficulty_var = tk.StringVar(
            value=difficulty_display(selection.difficulty)
        )
        self.difficulty_box = ttk.Combobox(
            parent,
            textvariable=self.difficulty_var,
            values=[label for label, _ in DIFFICULTIES.values()],
            state="readonly",
            width=15,
        )
        self.difficulty_box.grid(
            row=row, column=5, padx=(4, 8), pady=5, sticky="ew"
        )

        self.race_box.bind("<<ComboboxSelected>>", self._race_changed)
        self.build_box.bind("<<ComboboxSelected>>", self._build_changed)
        self._refresh_build_choices()

    def _race_changed(self, _event: object | None = None) -> None:
        self._refresh_build_choices()

    def _build_changed(self, _event: object | None = None) -> None:
        race_id = race_key(self.race_var.get())
        self.build_id = build_key(race_id, self.build_var.get())

    def _refresh_build_choices(self) -> None:
        race_id = race_key(self.race_var.get())
        labels = list(BUILD_LABELS[race_id].values())
        self.build_box.configure(values=labels)
        if self.build_id not in BUILD_LABELS[race_id]:
            self.build_id = DEFAULT_BUILD_BY_RACE[race_id]
        self.build_var.set(build_display(race_id, self.build_id))

    def selection(self) -> AISelection:
        return AISelection(
            slot=self.slot,
            race=race_key(self.race_var.get()),
            build=self.build_id,
            difficulty=difficulty_key(self.difficulty_var.get()),
        )

    def set_selection(self, selection: AISelection) -> None:
        self.build_id = selection.build
        self.race_var.set(race_display(selection.race))
        self.difficulty_var.set(difficulty_display(selection.difficulty))
        self._refresh_build_choices()

    def set_enabled(self, enabled: bool) -> None:
        state = "readonly" if enabled else "disabled"
        self.race_box.configure(state=state)
        self.build_box.configure(state=state)
        self.difficulty_box.configure(state=state)


class LauncherApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("SC2 유럽 섬멸전 7대7 로컬 런처")
        self.root.geometry("1100x920")
        self.root.minsize(900, 640)
        self.root.configure(bg="#08101d")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.running = False
        self.close_requested = False
        self.worker: threading.Thread | None = None
        self.cancel_event = threading.Event()
        self.rows: list[PlayerRow] = []
        self._configure_style()
        self._build_ui(self._load_config())

    def _configure_style(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(
            "TCombobox",
            fieldbackground="#17243a",
            background="#17243a",
            foreground="#f4f7fb",
            arrowcolor="#8ec5ff",
            bordercolor="#34506f",
            lightcolor="#34506f",
            darkcolor="#34506f",
            padding=6,
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", "#17243a"), ("disabled", "#101827")],
            foreground=[("readonly", "#f4f7fb"), ("disabled", "#6e7c90")],
        )

    def _build_ui(self, config: LauncherConfig) -> None:
        header = tk.Frame(self.root, bg="#08101d")
        header.pack(fill="x", padx=24, pady=(20, 12))
        tk.Label(
            header,
            text="유럽 섬멸전 7대7",
            bg="#08101d",
            fg="#f6fbff",
            font=("Malgun Gothic", 22, "bold"),
        ).pack(anchor="w")
        tk.Label(
            header,
            text="서쪽 P1–P7  vs  동쪽 P8–P14  ·  풍부한 자원 50,000  ·  일꾼 보급 0",
            bg="#08101d",
            fg="#90a4bf",
            font=("Malgun Gothic", 10),
        ).pack(anchor="w", pady=(3, 0))

        table = tk.Frame(
            self.root,
            bg="#111a28",
            highlightbackground="#2b4667",
            highlightthickness=1,
        )
        table.pack(fill="both", expand=True, padx=24, pady=8)

        headings = ["슬롯", "진영", "플레이어", "종족", "AI 빌드", "AI 난이도"]
        widths = [5, 7, 8, 13, 28, 15]
        for column, (heading, width) in enumerate(zip(headings, widths)):
            tk.Label(
                table,
                text=heading,
                width=width,
                bg="#1a2a40",
                fg="#bcd7f5",
                font=("Malgun Gothic", 9, "bold"),
                pady=9,
            ).grid(row=0, column=column, padx=(1, 0), pady=(1, 5), sticky="ew")
            table.grid_columnconfigure(column, weight=2 if column == 4 else 1)

        tk.Label(
            table,
            text="P1",
            bg="#111a28",
            fg="#f4f7fb",
            font=("Malgun Gothic", 10, "bold"),
        ).grid(row=1, column=0, padx=4, pady=6, sticky="ew")
        tk.Label(
            table,
            text="서쪽",
            bg="#111a28",
            fg="#78aef8",
            font=("Malgun Gothic", 10, "bold"),
        ).grid(row=1, column=1, padx=4, pady=6, sticky="ew")
        tk.Label(
            table,
            text="사람",
            bg="#111a28",
            fg="#ffffff",
            font=("Malgun Gothic", 9, "bold"),
        ).grid(row=1, column=2, padx=4, pady=6, sticky="ew")
        self.human_race_var = tk.StringVar(value=race_display(config.human_race))
        self.human_race_box = ttk.Combobox(
            table,
            textvariable=self.human_race_var,
            values=[label for label, _ in RACES.values()],
            state="readonly",
            width=13,
        )
        self.human_race_box.grid(row=1, column=3, padx=4, pady=6, sticky="ew")
        for column in (4, 5):
            tk.Label(
                table,
                text="—",
                bg="#111a28",
                fg="#627086",
                font=("Malgun Gothic", 10),
            ).grid(row=1, column=column, padx=4, pady=6, sticky="ew")

        selections = {player.slot: player for player in config.ai_players}
        for slot in range(2, 15):
            team = "서쪽" if slot <= 7 else "동쪽"
            self.rows.append(
                PlayerRow(table, slot, team, selections[slot], row=slot)
            )

        note = tk.Label(
            self.root,
            text=(
                "기본값: 모든 AI 자원 집중 / P2–P13 정예 / "
                "적 팀 P14 자원 치터"
            ),
            bg="#08101d",
            fg="#d0a963",
            font=("Malgun Gothic", 9),
        )
        note.pack(anchor="w", padx=26, pady=(4, 4))

        tk.Label(
            self.root,
            text=(
                "안정 모드: 공중 전용 성향은 목록에서 제외했습니다. "
                "세부 지상 빌드 강제 기능은 시작 유닛 오류로 임시 비활성화했습니다."
            ),
            bg="#08101d",
            fg="#e58f8f",
            font=("Malgun Gothic", 9),
        ).pack(anchor="w", padx=26, pady=(0, 4))

        footer = tk.Frame(self.root, bg="#08101d")
        footer.pack(fill="x", padx=24, pady=(5, 20))
        self.status_var = tk.StringVar(value="설정을 선택한 뒤 게임 시작을 누르세요.")
        tk.Label(
            footer,
            textvariable=self.status_var,
            bg="#08101d",
            fg="#9fb0c7",
            font=("Malgun Gothic", 9),
            anchor="w",
        ).pack(side="left", fill="x", expand=True)

        self.reset_button = tk.Button(
            footer,
            text="기본값 복원",
            command=self._reset_defaults,
            bg="#26364d",
            fg="#e6edf7",
            activebackground="#314966",
            activeforeground="#ffffff",
            relief="flat",
            padx=16,
            pady=9,
            cursor="hand2",
        )
        self.reset_button.pack(side="right", padx=(8, 0))
        self.stop_button = tk.Button(
            footer,
            text="게임 종료",
            command=self._stop_game,
            state="disabled",
            bg="#713a3a",
            fg="#ffffff",
            disabledforeground="#776b6b",
            relief="flat",
            padx=16,
            pady=9,
            cursor="hand2",
        )
        self.stop_button.pack(side="right", padx=(8, 0))
        self.start_button = tk.Button(
            footer,
            text="게임 시작",
            command=self._start_game,
            bg="#1674b9",
            fg="#ffffff",
            activebackground="#228bd4",
            activeforeground="#ffffff",
            relief="flat",
            font=("Malgun Gothic", 10, "bold"),
            padx=24,
            pady=9,
            cursor="hand2",
        )
        self.start_button.pack(side="right", padx=(16, 0))

    def _current_config(self) -> LauncherConfig:
        config = LauncherConfig(
            human_race=race_key(self.human_race_var.get()),
            ai_players=tuple(row.selection() for row in self.rows),
        )
        config.validate()
        return config

    def _load_config(self) -> LauncherConfig:
        try:
            return LauncherConfig.from_dict(
                json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            )
        except (FileNotFoundError, OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            return default_config()

    def _save_config(self, config: LauncherConfig) -> None:
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(
            json.dumps(config.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _set_controls_enabled(self, enabled: bool) -> None:
        self.human_race_box.configure(state="readonly" if enabled else "disabled")
        for row in self.rows:
            row.set_enabled(enabled)
        self.reset_button.configure(state="normal" if enabled else "disabled")
        self.start_button.configure(state="normal" if enabled else "disabled")
        self.stop_button.configure(state="disabled" if enabled else "normal")

    def _start_game(self) -> None:
        if self.running:
            return
        try:
            config = self._current_config()
            self._save_config(config)
        except Exception as error:
            messagebox.showerror("설정 오류", str(error), parent=self.root)
            return

        self.running = True
        self.cancel_event.clear()
        self._set_controls_enabled(False)
        self.status_var.set("게임 시작 준비 중…")

        def status(message: str) -> None:
            self.root.after(0, self.status_var.set, message)

        def worker() -> None:
            try:
                result = asyncio.run(run_local_game(config, self.cancel_event, status))
                self.root.after(0, self._game_finished, result, None)
            except Exception as error:
                self.root.after(0, self._game_finished, "게임 실행 실패", error)

        self.worker = threading.Thread(target=worker, name="sc2-game", daemon=True)
        self.worker.start()

    def _stop_game(self) -> None:
        if self.running:
            self.status_var.set("SC2 게임을 종료하는 중…")
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

    def _reset_defaults(self) -> None:
        config = default_config()
        self.human_race_var.set(race_display(config.human_race))
        for row, selection in zip(self.rows, config.ai_players):
            row.set_selection(selection)
        self.status_var.set("기본 설정을 복원했습니다.")

    def _on_close(self) -> None:
        if self.running:
            if not messagebox.askyesno(
                "게임 종료",
                "실행 중인 SC2 게임을 종료하고 런처를 닫을까요?",
                parent=self.root,
            ):
                return
            self.close_requested = True
            self.status_var.set("SC2 게임을 종료한 뒤 런처를 닫는 중…")
            self.cancel_event.set()
            self.stop_button.configure(state="disabled")
            return
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    LauncherApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
