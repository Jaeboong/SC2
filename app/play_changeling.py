from __future__ import annotations

import argparse
import asyncio
from collections import Counter
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
from contextlib import suppress
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Callable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from s2clientprotocol import common_pb2 as common_pb

from sc2team.process import discover_sc2_executable, launch_sc2, stop_process
from sc2team.protocol import Sc2Connection, make_multiplayer_ports
from sc2team.worker_supply_proxy import WorkerSupplyProxy


MAP_FILE = (
    PROJECT_ROOT
    / "maps"
    / "generated"
    / "torches-le-Pro-Bot_test.SC2Map"
)
BOT_DIRECTORY = (
    PROJECT_ROOT
    / "vendor"
    / "SC2AIApp_2025_S1"
    / "SC2AIApp_2025_S1"
    / "Bots"
    / "changeling"
)
BOT_EXECUTABLE = BOT_DIRECTORY / "changeling-fixed.exe"
BOT_CONFIG = BOT_DIRECTORY / "config.yml"
BOT_LOG = PROJECT_ROOT / "runtime" / "changeling.log"

HUMAN_API_PORT = 14100
BOT_PROXY_PORT = 14101
BOT_SC2_API_PORT = 14102
MULTIPLAYER_START_PORT = 14200

RACES = {
    "Random": ("무작위", common_pb.Random),
    "Terran": ("테란", common_pb.Terran),
    "Zerg": ("저그", common_pb.Zerg),
    "Protoss": ("프로토스", common_pb.Protoss),
}
RACE_BY_LABEL = {label: key for key, (label, _value) in RACES.items()}

WORKER_TYPES = {45, 84, 104, 116}
TOWNHALL_TO_WORKER = {
    18: 45,   # Command Center -> SCV
    59: 84,   # Nexus -> Probe
    86: 104,  # Hatchery -> Drone
}


def validate_files() -> None:
    missing = [
        path
        for path in (MAP_FILE, BOT_EXECUTABLE, BOT_CONFIG)
        if not path.is_file()
    ]
    if missing:
        formatted = "\n".join(str(path) for path in missing)
        raise FileNotFoundError(f"필요한 파일을 찾을 수 없습니다:\n{formatted}")


def configure_bot_race(race: str) -> bytes:
    if race not in RACES:
        raise ValueError(f"지원하지 않는 Changeling 종족입니다: {race}")
    original = BOT_CONFIG.read_bytes()
    text = original.decode("utf-8")
    updated, count = re.subn(
        r"(?m)^MyBotRace\s*:\s*[A-Za-z]+\s*$",
        f"MyBotRace: {race}",
        text,
        count=1,
    )
    if count != 1:
        raise ValueError("Changeling config.yml에서 MyBotRace를 찾지 못했습니다.")
    BOT_CONFIG.write_text(updated, encoding="utf-8", newline="")
    return original


def restore_bot_config(original: bytes | None) -> None:
    if original is not None:
        BOT_CONFIG.write_bytes(original)


def launch_changeling(log_handle: object) -> subprocess.Popen[bytes]:
    arguments = [
        str(BOT_EXECUTABLE),
        "--GamePort",
        str(BOT_PROXY_PORT),
        "--StartPort",
        str(MULTIPLAYER_START_PORT),
        "--LadderServer",
        "127.0.0.1",
        "--OpponentId",
        "LocalHuman",
        "--RealTime",
    ]
    return subprocess.Popen(
        arguments,
        cwd=BOT_DIRECTORY,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    )


def stop_subprocess(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def log_tail(max_lines: int = 20) -> str:
    try:
        return "\n".join(
            BOT_LOG.read_text(encoding="utf-8", errors="replace").splitlines()[
                -max_lines:
            ]
        )
    except OSError:
        return ""


async def ensure_twelve_starting_workers(connection: Sc2Connection) -> None:
    """Bring the bundled eight-worker Torches start up to modern 12 workers."""

    for _attempt in range(20):
        observation = await connection.observation(disable_fog=False)
        units = observation.observation.raw_data.units
        if any(unit.owner in (1, 2) for unit in units):
            break
        await asyncio.sleep(0.1)
    else:
        raise RuntimeError("시작 일꾼을 확인하지 못했습니다.")

    for player_id in (1, 2):
        own_workers = [
            unit
            for unit in units
            if unit.owner == player_id and unit.unit_type in WORKER_TYPES
        ]
        missing = max(0, 12 - len(own_workers))
        if missing == 0:
            continue
        townhall = next(
            (
                unit
                for unit in units
                if unit.owner == player_id and unit.unit_type in TOWNHALL_TO_WORKER
            ),
            None,
        )
        if townhall is None:
            raise RuntimeError(f"P{player_id} 시작 건물을 확인하지 못했습니다.")
        worker_type = TOWNHALL_TO_WORKER[townhall.unit_type]
        anchor = own_workers[0].pos if own_workers else townhall.pos
        await connection.debug_create_units(
            worker_type,
            player_id,
            anchor.x,
            anchor.y,
            missing,
        )


async def run_changeling_game(
    human_race: str,
    bot_race: str,
    cancel_event: threading.Event,
    status: Callable[[str], None],
    *,
    test_seconds: float | None = None,
) -> str:
    validate_files()
    if human_race not in RACES:
        raise ValueError(f"지원하지 않는 사람 종족입니다: {human_race}")

    sc2_executable = discover_sc2_executable()
    ports = make_multiplayer_ports(MULTIPLAYER_START_PORT, 2)
    sc2_processes: list[subprocess.Popen[bytes]] = []
    human_connection: Sc2Connection | None = None
    bot_probe: Sc2Connection | None = None
    bot_process: subprocess.Popen[bytes] | None = None
    worker_supply_proxy: WorkerSupplyProxy | None = None
    original_config: bytes | None = None
    human_player_id: int | None = None

    BOT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with BOT_LOG.open("w", encoding="utf-8", newline="") as log_handle:
        try:
            original_config = configure_bot_race(bot_race)
            status("사람용 및 Changeling용 SC2를 실행하는 중…")
            sc2_processes.append(
                launch_sc2(sc2_executable, HUMAN_API_PORT, 0, width=800, height=450)
            )
            sc2_processes.append(
                launch_sc2(
                    sc2_executable,
                    BOT_SC2_API_PORT,
                    1,
                    width=800,
                    height=450,
                )
            )

            human_connection, bot_probe = await asyncio.gather(
                Sc2Connection.open(HUMAN_API_PORT),
                Sc2Connection.open(BOT_SC2_API_PORT),
            )
            human_version, bot_version = await asyncio.gather(
                human_connection.ping(),
                bot_probe.ping(),
            )
            if human_version.game_version != bot_version.game_version:
                raise RuntimeError(
                    "SC2 클라이언트 버전이 서로 다릅니다: "
                    f"{human_version.game_version} / {bot_version.game_version}"
                )

            # Changeling needs exclusive use of the second client's websocket.
            await bot_probe.close()
            bot_probe = None
            worker_supply_proxy = WorkerSupplyProxy(
                listen_port=BOT_PROXY_PORT,
                sc2_port=BOT_SC2_API_PORT,
            )
            await worker_supply_proxy.start()

            status(f"SC2 {human_version.game_version} 연결 완료 — 1대1 게임 생성 중…")
            await human_connection.create_game(
                MAP_FILE.name,
                MAP_FILE.read_bytes(),
                participant_count=2,
                realtime=True,
            )

            bot_process = launch_changeling(log_handle)
            human_player_id = await asyncio.wait_for(
                human_connection.join_game(
                    RACES[human_race][1],
                    "Local Human",
                    ports,
                ),
                timeout=120.0,
            )
            if human_player_id != 1:
                raise RuntimeError(
                    f"사람이 P1이 아닌 P{human_player_id} 슬롯에 참가했습니다."
                )

            await ensure_twelve_starting_workers(human_connection)

            status(
                f"P1 사람({RACES[human_race][0]}) vs "
                f"P2 Changeling({RACES[bot_race][0]}) — SC2 창에서 플레이하세요."
            )
            started_at = time.monotonic()
            while not cancel_event.is_set():
                if sc2_processes[0].poll() is not None:
                    return "사람용 SC2 창이 닫혔습니다."
                if sc2_processes[1].poll() is not None:
                    raise RuntimeError("Changeling용 SC2 클라이언트가 종료됐습니다.")
                if bot_process.poll() is not None:
                    tail = log_tail()
                    detail = f"\n\nChangeling 로그:\n{tail}" if tail else ""
                    raise RuntimeError(
                        f"Changeling이 종료 코드 {bot_process.returncode}로 끝났습니다."
                        f"{detail}"
                    )

                observation = await human_connection.observation(disable_fog=False)
                if observation.player_result:
                    own_result = next(
                        (
                            result.result
                            for result in observation.player_result
                            if result.player_id == human_player_id
                        ),
                        None,
                    )
                    result_names = {1: "승리", 2: "패배", 3: "무승부", 4: "미결정"}
                    return f"게임 종료: {result_names.get(own_result, '결과 확인')}"

                if test_seconds is not None and time.monotonic() - started_at >= test_seconds:
                    p2_units = [
                        unit
                        for unit in observation.observation.raw_data.units
                        if unit.owner == 2
                    ]
                    if not p2_units:
                        raise RuntimeError(
                            "전체 시야인데도 Changeling의 P2 유닛을 관측하지 못했습니다."
                        )
                    type_counts = Counter(unit.unit_type for unit in p2_units)
                    supply_diagnostics = ""
                    if worker_supply_proxy is not None:
                        supply_diagnostics = (
                            ", bot API "
                            f"P{worker_supply_proxy.last_player_id} "
                            f"workers={worker_supply_proxy.last_worker_count}, "
                            f"food={worker_supply_proxy.last_actual_food_used}→"
                            f"{worker_supply_proxy.last_patched_food_used}, "
                            f"cap={worker_supply_proxy.last_food_cap}→"
                            f"{worker_supply_proxy.last_patched_food_cap}"
                        )
                    return (
                        f"Changeling 연결 테스트 통과: {test_seconds:g}초 유지, "
                        f"P2 유닛 {len(p2_units)}기 관측 "
                        f"(type_id별 {dict(sorted(type_counts.items()))})"
                        f"{supply_diagnostics}"
                    )
                await asyncio.sleep(1.0)

            return "사용자가 게임을 종료했습니다."
        finally:
            if human_connection is not None:
                with suppress(Exception):
                    await human_connection.quit()
                with suppress(Exception):
                    await human_connection.close()
            if bot_probe is not None:
                with suppress(Exception):
                    await bot_probe.close()
            if worker_supply_proxy is not None:
                with suppress(Exception):
                    await worker_supply_proxy.close()
            stop_subprocess(bot_process)
            for process in sc2_processes:
                stop_process(process)
            restore_bot_config(original_config)


class ChangelingLauncher:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("SC2 Pro Bot 1대1 테스트")
        self.root.geometry("620x390")
        self.root.resizable(False, False)
        self.root.configure(bg="#08101d")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.running = False
        self.close_requested = False
        self.cancel_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.human_race = tk.StringVar(value="테란")
        self.bot_race = tk.StringVar(value="무작위")
        self.status_text = tk.StringVar(value="설정을 선택하고 게임 시작을 누르세요.")
        self._build_ui()

    def _build_ui(self) -> None:
        tk.Label(
            self.root,
            text="Torches LE Pro Bot_test",
            bg="#08101d",
            fg="#f6fbff",
            font=("Malgun Gothic", 20, "bold"),
        ).pack(anchor="w", padx=28, pady=(24, 4))
        tk.Label(
            self.root,
            text="P1 사람은 전장 전체를 보며 P2 Changeling의 동작을 관찰합니다.",
            bg="#08101d",
            fg="#90a4bf",
            font=("Malgun Gothic", 10),
        ).pack(anchor="w", padx=30, pady=(0, 22))

        panel = tk.Frame(
            self.root,
            bg="#111a28",
            highlightbackground="#2b4667",
            highlightthickness=1,
        )
        panel.pack(fill="x", padx=28, pady=4)

        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(
            "TCombobox",
            fieldbackground="#17243a",
            background="#17243a",
            foreground="#f4f7fb",
            arrowcolor="#8ec5ff",
            padding=7,
        )

        self.human_box = self._add_player_row(
            panel, 0, "P1", "사람", self.human_race, "#78aef8"
        )
        self.bot_box = self._add_player_row(
            panel, 1, "P2", "Changeling", self.bot_race, "#ff8b83"
        )

        tk.Label(
            self.root,
            text="Changeling 무작위: 저그 Eris / 프로토스 Deimos / 테란 Phobos",
            bg="#08101d",
            fg="#d0a963",
            font=("Malgun Gothic", 9),
        ).pack(anchor="w", padx=30, pady=(12, 4))
        tk.Label(
            self.root,
            textvariable=self.status_text,
            bg="#08101d",
            fg="#a9bad0",
            wraplength=560,
            justify="left",
            font=("Malgun Gothic", 9),
        ).pack(anchor="w", padx=30, pady=(4, 16))

        buttons = tk.Frame(self.root, bg="#08101d")
        buttons.pack(fill="x", padx=28, pady=(0, 22))
        self.stop_button = tk.Button(
            buttons,
            text="게임 종료",
            command=self._stop,
            state="disabled",
            bg="#713a3a",
            fg="#ffffff",
            disabledforeground="#776b6b",
            relief="flat",
            padx=18,
            pady=9,
        )
        self.stop_button.pack(side="right", padx=(8, 0))
        self.start_button = tk.Button(
            buttons,
            text="게임 시작",
            command=self._start,
            bg="#1674b9",
            fg="#ffffff",
            activebackground="#228bd4",
            activeforeground="#ffffff",
            relief="flat",
            font=("Malgun Gothic", 10, "bold"),
            padx=24,
            pady=9,
        )
        self.start_button.pack(side="right")

    def _add_player_row(
        self,
        parent: tk.Frame,
        row: int,
        slot: str,
        player_type: str,
        variable: tk.StringVar,
        color: str,
    ) -> ttk.Combobox:
        tk.Label(
            parent,
            text=slot,
            bg="#111a28",
            fg=color,
            font=("Malgun Gothic", 11, "bold"),
            width=7,
        ).grid(row=row, column=0, padx=(12, 4), pady=12)
        tk.Label(
            parent,
            text=player_type,
            bg="#111a28",
            fg="#f4f7fb",
            font=("Malgun Gothic", 10),
            width=15,
        ).grid(row=row, column=1, padx=4, pady=12)
        box = ttk.Combobox(
            parent,
            textvariable=variable,
            values=[label for label, _value in RACES.values()],
            state="readonly",
            width=18,
        )
        box.grid(row=row, column=2, padx=(12, 18), pady=12)
        return box

    def _set_running(self, running: bool) -> None:
        self.running = running
        state = "disabled" if running else "readonly"
        self.human_box.configure(state=state)
        self.bot_box.configure(state=state)
        self.start_button.configure(state="disabled" if running else "normal")
        self.stop_button.configure(state="normal" if running else "disabled")

    def _start(self) -> None:
        if self.running:
            return
        human_race = RACE_BY_LABEL[self.human_race.get()]
        bot_race = RACE_BY_LABEL[self.bot_race.get()]
        self.cancel_event.clear()
        self._set_running(True)
        self.status_text.set("게임 실행 준비 중…")

        def status(message: str) -> None:
            self.root.after(0, self.status_text.set, message)

        def worker() -> None:
            try:
                result = asyncio.run(
                    run_changeling_game(
                        human_race,
                        bot_race,
                        self.cancel_event,
                        status,
                    )
                )
                self.root.after(0, self._finished, result, None)
            except Exception as error:
                self.root.after(0, self._finished, "게임 실행 실패", error)

        self.worker = threading.Thread(target=worker, name="changeling-game", daemon=True)
        self.worker.start()

    def _stop(self) -> None:
        if self.running:
            self.status_text.set("게임을 종료하는 중…")
            self.cancel_event.set()
            self.stop_button.configure(state="disabled")

    def _finished(self, result: str, error: Exception | None) -> None:
        self._set_running(False)
        if self.close_requested:
            self.root.destroy()
            return
        if error is None:
            self.status_text.set(result)
        else:
            self.status_text.set(f"실행 실패: {error}")
            messagebox.showerror("Changeling 실행 실패", str(error), parent=self.root)

    def _on_close(self) -> None:
        if self.running:
            if not messagebox.askyesno(
                "게임 종료",
                "실행 중인 게임을 종료하고 런처를 닫을까요?",
                parent=self.root,
            ):
                return
            self.close_requested = True
            self.cancel_event.set()
            self.status_text.set("게임 종료 후 런처를 닫는 중…")
            return
        self.root.destroy()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Human vs Changeling local SC2 launcher")
    parser.add_argument("--cli", action="store_true", help="run without the Tk GUI")
    parser.add_argument("--human-race", choices=RACES, default="Terran")
    parser.add_argument("--bot-race", choices=RACES, default="Random")
    parser.add_argument("--test-seconds", type=float)
    return parser.parse_args()


def main() -> None:
    arguments = parse_args()
    if arguments.cli:
        cancel_event = threading.Event()
        try:
            result = asyncio.run(
                run_changeling_game(
                    arguments.human_race,
                    arguments.bot_race,
                    cancel_event,
                    print,
                    test_seconds=arguments.test_seconds,
                )
            )
            print(result)
        except KeyboardInterrupt:
            cancel_event.set()
        return

    root = tk.Tk()
    ChangelingLauncher(root)
    root.mainloop()


if __name__ == "__main__":
    main()
