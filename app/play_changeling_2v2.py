from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable, TextIO

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from s2clientprotocol import common_pb2 as common_pb

from sc2team.process import discover_sc2_executable, launch_sc2, stop_process
from sc2team.protocol import Sc2Connection, make_multiplayer_ports
from sc2team.worker_supply_proxy import WorkerSupplyProxy


MAP_FILE = (
    PROJECT_ROOT
    / "map"
    / "source"
    / "europe-melee-Pro-Bot-v0.2_test.SC2Map"
)
BOT_SOURCE_DIRECTORY = (
    PROJECT_ROOT
    / "vendor"
    / "SC2AIApp_2025_S1"
    / "SC2AIApp_2025_S1"
    / "Bots"
    / "changeling"
)
BOT_EXECUTABLE = BOT_SOURCE_DIRECTORY / "changeling-fixed.exe"
RUNTIME_DIRECTORY = PROJECT_ROOT / "runtime" / "changeling_2v2"

HUMAN_API_PORT = 15100
BOT_PROXY_PORTS = (15101, 15103, 15105)
BOT_SC2_API_PORTS = (15102, 15104, 15106)
MULTIPLAYER_START_PORT = 15200

RACES = {
    "Random": ("무작위", common_pb.Random),
    "Terran": ("테란", common_pb.Terran),
    "Zerg": ("저그", common_pb.Zerg),
    "Protoss": ("프로토스", common_pb.Protoss),
}
RACE_BY_LABEL = {label: key for key, (label, _value) in RACES.items()}

WORKER_TYPES = {45, 84, 104, 116}
TOWNHALL_TO_WORKER = {
    18: 45,
    59: 84,
    86: 104,
}


@dataclass
class BotInstance:
    player_id: int
    race: str
    proxy_port: int
    sc2_api_port: int
    directory: Path
    log_path: Path
    process: subprocess.Popen[bytes] | None = None
    proxy: WorkerSupplyProxy | None = None
    log_handle: TextIO | None = None


def validate_files() -> None:
    required = [
        MAP_FILE,
        BOT_EXECUTABLE,
        BOT_SOURCE_DIRECTORY / "config.yml",
        BOT_SOURCE_DIRECTORY / "protoss_builds.yml",
        BOT_SOURCE_DIRECTORY / "terran_builds.yml",
    ]
    missing = [path for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            "필요한 파일을 찾을 수 없습니다:\n" + "\n".join(map(str, missing))
        )


def prepare_bot_instance(
    player_id: int,
    race: str,
    proxy_port: int,
    sc2_api_port: int,
) -> BotInstance:
    if race not in RACES:
        raise ValueError(f"지원하지 않는 Changeling 종족입니다: {race}")
    directory = RUNTIME_DIRECTORY / f"p{player_id}"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "data").mkdir(exist_ok=True)

    for filename in ("protoss_builds.yml", "terran_builds.yml"):
        shutil.copy2(BOT_SOURCE_DIRECTORY / filename, directory / filename)

    config_text = (BOT_SOURCE_DIRECTORY / "config.yml").read_text(encoding="utf-8")
    config_text, count = re.subn(
        r"(?m)^MyBotRace\s*:\s*[A-Za-z]+\s*$",
        f"MyBotRace: {race}",
        config_text,
        count=1,
    )
    if count != 1:
        raise ValueError("Changeling config.yml에서 MyBotRace를 찾지 못했습니다.")
    config_text, count = re.subn(
        r"(?m)^MyBotName\s*:\s*.*$",
        f"MyBotName: Changeling P{player_id}",
        config_text,
        count=1,
    )
    if count != 1:
        raise ValueError("Changeling config.yml에서 MyBotName을 찾지 못했습니다.")
    (directory / "config.yml").write_text(config_text, encoding="utf-8", newline="")
    return BotInstance(
        player_id=player_id,
        race=race,
        proxy_port=proxy_port,
        sc2_api_port=sc2_api_port,
        directory=directory,
        log_path=RUNTIME_DIRECTORY / f"p{player_id}.log",
    )


def launch_bot(instance: BotInstance) -> None:
    instance.log_path.parent.mkdir(parents=True, exist_ok=True)
    instance.log_handle = instance.log_path.open("w", encoding="utf-8", newline="")
    arguments = [
        str(BOT_EXECUTABLE),
        "--GamePort",
        str(instance.proxy_port),
        "--StartPort",
        str(MULTIPLAYER_START_PORT),
        "--LadderServer",
        "127.0.0.1",
        "--OpponentId",
        f"Local2v2-P{instance.player_id}",
        "--RealTime",
    ]
    instance.process = subprocess.Popen(
        arguments,
        cwd=instance.directory,
        stdout=instance.log_handle,
        stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    )


def stop_bot(instance: BotInstance) -> None:
    process = instance.process
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    instance.process = None
    if instance.log_handle is not None:
        instance.log_handle.close()
        instance.log_handle = None


def log_tail(instance: BotInstance, max_lines: int = 24) -> str:
    try:
        lines = instance.log_path.read_text(
            encoding="utf-8", errors="replace"
        ).splitlines()
        return "\n".join(lines[-max_lines:])
    except OSError:
        return ""


async def ensure_twelve_starting_workers(
    connection: Sc2Connection,
    player_count: int,
) -> None:
    units = ()
    for _attempt in range(40):
        observation = await connection.observation(disable_fog=False)
        units = observation.observation.raw_data.units
        if all(any(unit.owner == player_id for unit in units) for player_id in range(1, player_count + 1)):
            break
        await asyncio.sleep(0.1)
    else:
        raise RuntimeError("P1~P4 시작 유닛을 모두 확인하지 못했습니다.")

    for player_id in range(1, player_count + 1):
        workers = [
            unit
            for unit in units
            if unit.owner == player_id and unit.unit_type in WORKER_TYPES
        ]
        missing = max(0, 12 - len(workers))
        if not missing:
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
        anchor = workers[0].pos if workers else townhall.pos
        await connection.debug_create_units(
            TOWNHALL_TO_WORKER[townhall.unit_type],
            player_id,
            anchor.x,
            anchor.y,
            missing,
        )


async def run_changeling_2v2(
    races: tuple[str, str, str, str],
    cancel_event: threading.Event,
    status: Callable[[str], None],
    *,
    test_seconds: float | None = None,
) -> str:
    validate_files()
    if len(races) != 4 or any(race not in RACES for race in races):
        raise ValueError("P1~P4의 종족 설정이 올바르지 않습니다.")

    sc2_executable = discover_sc2_executable()
    multiplayer_ports = make_multiplayer_ports(MULTIPLAYER_START_PORT, 4)
    sc2_processes: list[subprocess.Popen[bytes]] = []
    human_connection: Sc2Connection | None = None
    bot_probes: list[Sc2Connection] = []
    human_player_id: int | None = None
    bots = [
        prepare_bot_instance(player_id, races[player_id - 1], proxy_port, api_port)
        for player_id, proxy_port, api_port in zip(
            range(2, 5), BOT_PROXY_PORTS, BOT_SC2_API_PORTS
        )
    ]

    try:
        status("사람용 SC2 1개와 Changeling용 SC2 3개를 실행하는 중…")
        api_ports = (HUMAN_API_PORT, *BOT_SC2_API_PORTS)
        for index, api_port in enumerate(api_ports):
            sc2_processes.append(
                launch_sc2(sc2_executable, api_port, index, width=800, height=450)
            )

        connections = await asyncio.gather(
            *(Sc2Connection.open(api_port, timeout=75.0) for api_port in api_ports)
        )
        human_connection = connections[0]
        bot_probes = list(connections[1:])
        versions = await asyncio.gather(*(connection.ping() for connection in connections))
        version_names = {version.game_version for version in versions}
        if len(version_names) != 1:
            raise RuntimeError(f"SC2 클라이언트 버전이 서로 다릅니다: {sorted(version_names)}")

        await asyncio.gather(*(probe.close() for probe in bot_probes))
        bot_probes.clear()
        for bot in bots:
            bot.proxy = WorkerSupplyProxy(
                listen_port=bot.proxy_port,
                sc2_port=bot.sc2_api_port,
            )
            await bot.proxy.start()

        status(f"SC2 {versions[0].game_version} 연결 완료 — 2대2 게임 생성 중…")
        await human_connection.create_game(
            MAP_FILE.name,
            MAP_FILE.read_bytes(),
            participant_count=4,
            realtime=True,
        )

        # Submit P1 first. SC2 assigns participant slots by join order; the
        # stagger also keeps P2/P3/P4 race settings aligned with their teams.
        human_join = asyncio.create_task(
            human_connection.join_game(
                RACES[races[0]][1],
                "Local Human P1",
                multiplayer_ports,
            )
        )
        await asyncio.sleep(0.5)
        for index, bot in enumerate(bots):
            status(f"P{bot.player_id} Changeling 참가 중…")
            launch_bot(bot)
            if index < len(bots) - 1:
                await asyncio.sleep(2.0)

        human_player_id = await asyncio.wait_for(human_join, timeout=180.0)
        if human_player_id != 1:
            raise RuntimeError(
                f"사람이 P1이 아닌 P{human_player_id} 슬롯에 참가했습니다. 다시 실행해 주세요."
            )

        await ensure_twelve_starting_workers(human_connection, 4)
        status(
            f"서쪽: P1 사람({RACES[races[0]][0]}) + P2 Changeling({RACES[races[1]][0]}) / "
            f"동쪽: P3({RACES[races[2]][0]}) + P4({RACES[races[3]][0]}) — 플레이하세요."
        )

        started_at = time.monotonic()
        while not cancel_event.is_set():
            for index, process in enumerate(sc2_processes):
                if process.poll() is not None:
                    role = "사람용" if index == 0 else f"P{index + 1} 봇용"
                    raise RuntimeError(f"{role} SC2 클라이언트가 종료됐습니다.")
            for bot in bots:
                if bot.process is not None and bot.process.poll() is not None:
                    tail = log_tail(bot)
                    detail = f"\n\nP{bot.player_id} 로그:\n{tail}" if tail else ""
                    raise RuntimeError(
                        f"P{bot.player_id} Changeling이 종료 코드 "
                        f"{bot.process.returncode}로 끝났습니다.{detail}"
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
                units = observation.observation.raw_data.units
                diagnostics = []
                for bot in bots:
                    owned = [unit for unit in units if unit.owner == bot.player_id]
                    if not owned:
                        raise RuntimeError(f"전체 시야인데도 P{bot.player_id} 유닛이 보이지 않습니다.")
                    counts = Counter(unit.unit_type for unit in owned)
                    proxy = bot.proxy
                    supply = ""
                    if proxy is not None:
                        supply = (
                            f", api=P{proxy.last_player_id}, workers={proxy.last_worker_count}, "
                            f"food={proxy.last_actual_food_used}→{proxy.last_patched_food_used}, "
                            f"cap={proxy.last_food_cap}→{proxy.last_patched_food_cap}"
                        )
                    diagnostics.append(
                        f"P{bot.player_id} {len(owned)}기 {dict(sorted(counts.items()))}{supply}"
                    )
                return (
                    f"Changeling 2대2 연결 테스트 통과: {test_seconds:g}초 유지\n"
                    + "\n".join(diagnostics)
                )
            await asyncio.sleep(1.0)

        return "사용자가 게임을 종료했습니다."
    finally:
        if human_connection is not None:
            with suppress(Exception):
                await human_connection.quit()
            with suppress(Exception):
                await human_connection.close()
        for probe in bot_probes:
            with suppress(Exception):
                await probe.close()
        for bot in bots:
            if bot.proxy is not None:
                with suppress(Exception):
                    await bot.proxy.close()
                bot.proxy = None
            stop_bot(bot)
        for process in sc2_processes:
            stop_process(process)


class Changeling2v2Launcher:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("SC2 Pro Bot 2대2 v0.2_test")
        self.root.geometry("700x540")
        self.root.resizable(False, False)
        self.root.configure(bg="#08101d")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        defaults = ("테란", "테란", "프로토스", "프로토스")
        self.race_variables = [tk.StringVar(value=value) for value in defaults]
        self.race_boxes: list[ttk.Combobox] = []
        self.status_text = tk.StringVar(value="종족을 선택하고 게임 시작을 누르세요.")
        self.cancel_event = threading.Event()
        self.running = False
        self.close_requested = False
        self.worker: threading.Thread | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        tk.Label(
            self.root,
            text="유럽 섬멸전 Pro Bot v0.2_test",
            bg="#08101d",
            fg="#f6fbff",
            font=("Malgun Gothic", 20, "bold"),
        ).pack(anchor="w", padx=28, pady=(24, 4))
        tk.Label(
            self.root,
            text="P1은 전체 시야로 세 Changeling의 동작을 관찰할 수 있습니다.",
            bg="#08101d",
            fg="#90a4bf",
            font=("Malgun Gothic", 10),
        ).pack(anchor="w", padx=30, pady=(0, 18))

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
        panel = tk.Frame(
            self.root,
            bg="#111a28",
            highlightbackground="#2b4667",
            highlightthickness=1,
        )
        panel.pack(fill="x", padx=28, pady=4)
        labels = (
            ("P1", "서쪽 1팀", "사람", "#78aef8"),
            ("P2", "서쪽 1팀", "Changeling", "#78aef8"),
            ("P3", "동쪽 2팀", "Changeling", "#ff8b83"),
            ("P4", "동쪽 2팀", "Changeling", "#ff8b83"),
        )
        for row, (slot, team, role, color) in enumerate(labels):
            tk.Label(panel, text=slot, bg="#111a28", fg=color, font=("Malgun Gothic", 11, "bold"), width=6).grid(row=row, column=0, padx=(12, 2), pady=10)
            tk.Label(panel, text=team, bg="#111a28", fg="#b8c6d9", font=("Malgun Gothic", 9), width=11).grid(row=row, column=1, padx=2, pady=10)
            tk.Label(panel, text=role, bg="#111a28", fg="#f4f7fb", font=("Malgun Gothic", 10), width=14).grid(row=row, column=2, padx=2, pady=10)
            box = ttk.Combobox(
                panel,
                textvariable=self.race_variables[row],
                values=[label for label, _value in RACES.values()],
                state="readonly",
                width=18,
            )
            box.grid(row=row, column=3, padx=(12, 18), pady=10)
            self.race_boxes.append(box)

        tk.Label(
            self.root,
            text="각 Changeling: 저그 Eris / 프로토스 Deimos / 테란 Phobos",
            bg="#08101d",
            fg="#d0a963",
            font=("Malgun Gothic", 9),
        ).pack(anchor="w", padx=30, pady=(12, 4))
        tk.Label(
            self.root,
            textvariable=self.status_text,
            bg="#08101d",
            fg="#a9bad0",
            wraplength=640,
            justify="left",
            font=("Malgun Gothic", 9),
        ).pack(anchor="w", padx=30, pady=(4, 14))

        buttons = tk.Frame(self.root, bg="#08101d")
        buttons.pack(fill="x", padx=28, pady=(0, 20))
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
            text="2대2 게임 시작",
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

    def _set_running(self, running: bool) -> None:
        self.running = running
        for box in self.race_boxes:
            box.configure(state="disabled" if running else "readonly")
        self.start_button.configure(state="disabled" if running else "normal")
        self.stop_button.configure(state="normal" if running else "disabled")

    def _start(self) -> None:
        if self.running:
            return
        races = tuple(RACE_BY_LABEL[variable.get()] for variable in self.race_variables)
        self.cancel_event.clear()
        self._set_running(True)
        self.status_text.set("2대2 게임 실행 준비 중…")

        def status(message: str) -> None:
            self.root.after(0, self.status_text.set, message)

        def worker() -> None:
            try:
                result = asyncio.run(run_changeling_2v2(races, self.cancel_event, status))
                self.root.after(0, self._finished, result, None)
            except Exception as error:
                self.root.after(0, self._finished, "게임 실행 실패", error)

        self.worker = threading.Thread(target=worker, name="changeling-2v2", daemon=True)
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
            messagebox.showerror("Changeling 2대2 실행 실패", str(error), parent=self.root)

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
    parser = argparse.ArgumentParser(description="Human + Changeling vs two Changeling")
    parser.add_argument("--cli", action="store_true", help="run without the Tk GUI")
    parser.add_argument("--p1-race", choices=RACES, default="Terran")
    parser.add_argument("--p2-race", choices=RACES, default="Terran")
    parser.add_argument("--p3-race", choices=RACES, default="Protoss")
    parser.add_argument("--p4-race", choices=RACES, default="Protoss")
    parser.add_argument("--test-seconds", type=float)
    return parser.parse_args()


def main() -> None:
    arguments = parse_args()
    races = (
        arguments.p1_race,
        arguments.p2_race,
        arguments.p3_race,
        arguments.p4_race,
    )
    if arguments.cli:
        cancel_event = threading.Event()
        try:
            result = asyncio.run(
                run_changeling_2v2(
                    races,
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
    Changeling2v2Launcher(root)
    root.mainloop()


if __name__ == "__main__":
    main()
