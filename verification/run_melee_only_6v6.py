"""Run a 6v6 Blizzard-melee-only visual stutter control for 15 real minutes.

After CreateGame/JoinGame this process sends no SC2 API requests until the
wall-clock deadline.  There are no observations, metrics, strategy updates,
replay snapshots, debug calls, or simulation steps during the measured run.
"""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import replace
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sc2team.custom_config import CustomLauncherConfig, SlotConfig
from sc2team.custom_runtime import build_runtime_map, player_setups
from sc2team.process import discover_sc2_executable, launch_sc2, stop_process
from sc2team.protocol import Sc2Connection


SETTINGS_FILE = PROJECT_ROOT / "runtime" / "custom_ai_settings.json"
BASE_MAP_FILE = (
    PROJECT_ROOT
    / "map"
    / "source"
    / "europe-melee-2-7v7-rich-50000-fixed-teams.SC2Map"
)
OUTPUT_MAP = PROJECT_ROOT / "runtime" / "maps" / "diagnostic-melee-only-6v6.SC2Map"
ACTIVE_CONFIG = PROJECT_ROOT / "runtime" / "diagnostic-melee-only-6v6.json"
RUN_SECONDS = 15 * 60


def diagnostic_config() -> CustomLauncherConfig:
    saved = CustomLauncherConfig.from_dict(
        json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    )
    slots: list[SlotConfig] = []
    for slot in saved.slots:
        active = slot.slot in {*range(1, 7), *range(8, 14)}
        controller = "human" if slot.slot == 1 else "custom_ai" if active else "empty"
        slots.append(replace(slot, controller=controller))
    return replace(
        saved,
        slots=tuple(slots),
        wild_zerg=False,
        full_vision=False,
        fullscreen=True,
    )


async def run() -> None:
    config = diagnostic_config()
    build_runtime_map(
        PROJECT_ROOT,
        BASE_MAP_FILE,
        OUTPUT_MAP,
        config,
        observer_mode=True,
        melee_only=True,
        active_config_file=ACTIVE_CONFIG,
    )
    process = launch_sc2(discover_sc2_executable(), 14120, 0, fullscreen=True)
    connection: Sc2Connection | None = None
    try:
        connection = await Sc2Connection.open(14120)
        await connection.ping()
        await connection.create_game_with_setups(
            OUTPUT_MAP.name,
            OUTPUT_MAP.read_bytes(),
            player_setups(config, observer=True),
            realtime=True,
        )
        await connection.join_as_observer("6v6 Melee-only Observer")
        print(
            "MELEE_ONLY_6V6_STARTED: 900 seconds, no observations or custom "
            "periodic runtime controllers",
            flush=True,
        )
        deadline = asyncio.get_running_loop().time() + RUN_SECONDS
        while process.poll() is None and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(1.0)
        print("MELEE_ONLY_6V6_FINISHED", flush=True)
        if process.poll() is None:
            await connection.quit()
    finally:
        stop_process(process)


if __name__ == "__main__":
    asyncio.run(run())
