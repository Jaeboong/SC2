from __future__ import annotations

import asyncio
from collections import Counter
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sc2team.custom_config import CustomLauncherConfig, SlotConfig
from sc2team.custom_runtime import RACE_VALUES, build_runtime_map, player_setups
from sc2team.process import discover_sc2_executable, launch_sc2, stop_process
from sc2team.protocol import Sc2Connection


BASE_MAP_FILE = (
    PROJECT_ROOT
    / "map"
    / "source"
    / "europe-melee-2-7v7-rich-50000-fixed-teams.SC2Map"
)
RUNTIME_MAP_FILE = PROJECT_ROOT / "runtime" / "maps" / "campaign-dependency-probe.SC2Map"
PORT = 14113

WORKER_TYPES = {"Terran": 45, "Protoss": 84, "Zerg": 104}
TOWN_HALL_TYPES = {"Terran": 18, "Protoss": 59, "Zerg": 86}


def probe_config() -> CustomLauncherConfig:
    players = {
        1: ("human", "Terran", "bio_tank"),
        2: ("custom_ai", "Protoss", "stalker_immortal"),
        8: ("custom_ai", "Zerg", "ultra_ling_bane"),
        9: ("custom_ai", "Terran", "mech_macro"),
    }
    slots = []
    for slot_id in range(1, 15):
        controller, race, build = players.get(
            slot_id, ("empty", "Random", "random_ground")
        )
        slots.append(
            SlotConfig(
                slot=slot_id,
                controller=controller,
                team=1 if slot_id <= 7 else 2,
                race=race,
                build=build,
            )
        )
    config = CustomLauncherConfig(version=1, slots=tuple(slots))
    config.validate()
    return config


def owner_type_counts(observation, owner: int) -> Counter[int]:
    return Counter(
        unit.unit_type
        for unit in observation.observation.raw_data.units
        if unit.owner == owner
    )


async def main() -> None:
    config = probe_config()
    runtime_races = [slot.race for slot in (config.human,) + config.custom_ai_slots]
    build_runtime_map(
        PROJECT_ROOT,
        BASE_MAP_FILE,
        RUNTIME_MAP_FILE,
        config,
        campaign_units_pilot=True,
        active_config_file=RUNTIME_MAP_FILE.with_suffix(".json"),
    )

    process = launch_sc2(discover_sc2_executable(), PORT, 0)
    connection: Sc2Connection | None = None
    try:
        connection = await Sc2Connection.open(PORT)
        await connection.create_game_with_setups(
            RUNTIME_MAP_FILE.name,
            RUNTIME_MAP_FILE.read_bytes(),
            player_setups(config),
            realtime=False,
        )
        joined_player = await connection.join_game(
            RACE_VALUES[config.human.race],
            "Campaign Dependency Verification",
            None,
        )
        if joined_player != 1:
            raise RuntimeError(f"Participant joined as runtime P{joined_player}, expected P1")
        await connection.step(1)
        observation = await connection.observation(disable_fog=True)

        for owner, race in enumerate(runtime_races, start=1):
            counts = owner_type_counts(observation, owner)
            workers = counts[WORKER_TYPES[race]]
            town_halls = counts[TOWN_HALL_TYPES[race]]
            print(
                f"runtime=P{owner} race={race} workers={workers} "
                f"town_halls={town_halls} unit_types={dict(sorted(counts.items()))}"
            )
            if workers != 8 or town_halls != 1:
                raise RuntimeError(
                    "CAMPAIGN_DEPENDENCY_NORMAL_START=FAIL "
                    f"runtime P{owner} {race}: workers={workers}, town_halls={town_halls}"
                )
        print("CAMPAIGN_DEPENDENCY_NORMAL_START=PASS")
    finally:
        if connection is not None:
            await connection.quit()
            await connection.close()
        stop_process(process)


if __name__ == "__main__":
    asyncio.run(main())
