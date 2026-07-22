from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sc2team.custom_config import CustomLauncherConfig
from sc2team.custom_runtime import RACE_VALUES, player_setups, runtime_slots
from sc2team.process import discover_sc2_executable, launch_sc2, stop_process
from sc2team.protocol import Sc2Connection


SETTINGS_FILE = PROJECT_ROOT / "runtime" / "custom_ai_settings.json"
RELEASE_MAP_FILE = (
    PROJECT_ROOT / "runtime" / "maps" / "europe-melee-custom-ai-v1.25.0.SC2Map"
)
PORT = 14126

START_UNITS = {
    "Terran": ({18, 130, 132}, {45}),
    "Zerg": ({86, 100, 101}, {104}),
    "Protoss": ({59}, {84}),
}


async def main() -> None:
    config = CustomLauncherConfig.from_dict(
        json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    )
    if not RELEASE_MAP_FILE.is_file():
        raise FileNotFoundError(f"Release map is missing: {RELEASE_MAP_FILE}")

    process = launch_sc2(discover_sc2_executable(), PORT, 0)
    connection: Sc2Connection | None = None
    try:
        connection = await Sc2Connection.open(PORT)
        setups = player_setups(config)
        await connection.create_game_with_setups(
            RELEASE_MAP_FILE.name,
            RELEASE_MAP_FILE.read_bytes(),
            setups,
            realtime=False,
        )
        joined = await connection.join_game(
            RACE_VALUES[config.human.race], "Release Map Verification", None
        )
        if joined != 1:
            raise RuntimeError(f"Human joined as runtime P{joined}, expected P1")

        await connection.step(90)
        observation = await connection.observation(disable_fog=True)
        all_units = observation.observation.raw_data.units
        rows = []
        for runtime_id, slot in enumerate(runtime_slots(config), start=1):
            if slot.race == "Random":
                # The concrete race is not known until SC2 resolves it. Its
                # ordinary melee start is covered by the race-specific probes.
                continue
            town_halls, workers = START_UNITS[slot.race]
            owned = [unit for unit in all_units if unit.owner == runtime_id]
            town_hall_count = sum(unit.unit_type in town_halls for unit in owned)
            worker_count = sum(unit.unit_type in workers for unit in owned)
            rows.append(
                f"runtimeP{runtime_id}=logicalP{slot.slot}:{slot.race} "
                f"townhall={town_hall_count} workers={worker_count}"
            )
            if town_hall_count != 1 or worker_count != 8:
                raise RuntimeError(
                    "RELEASE_ENGINE_SMOKE=FAIL " + rows[-1]
                )

        print(f"players={len(setups)} human=P{config.human.slot}->runtimeP1")
        for row in rows:
            print(row)
        print("RELEASE_ENGINE_SMOKE=PASS")
    finally:
        if connection is not None:
            try:
                await connection.quit()
            finally:
                await connection.close()
        stop_process(process)


if __name__ == "__main__":
    asyncio.run(main())
