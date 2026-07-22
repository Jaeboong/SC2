from __future__ import annotations

import asyncio
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from s2clientprotocol import sc2api_pb2 as sc_pb

from sc2team.custom_config import CustomLauncherConfig, SlotConfig
from sc2team.custom_runtime import RACE_VALUES, build_runtime_map, player_setups
from sc2team.process import discover_sc2_executable, launch_sc2, stop_process
from sc2team.protocol import Sc2Connection


BASE_MAP_FILE = PROJECT_ROOT / "maps" / "generated" / "europe-melee-2-7v7-rich-50000-fixed-teams.SC2Map"
RUNTIME_MAP_FILE = PROJECT_ROOT / "runtime" / "maps" / "campaign-roster-probe.SC2Map"
PORT = 14116
CUSTOM_UNITS = {
    "HotSTorrasque": (500, 6),
    "SC2TeamAberration": (275, 3),
    "SC2TeamGoliath": (150, 2),
    "SC2TeamPredator": (140, 3),
    "SC2TeamMedic": (60, 2),
}


def config() -> CustomLauncherConfig:
    slots = []
    for slot_id in range(1, 15):
        if slot_id == 1:
            values = ("human", "Zerg", "ling_bane")
        elif slot_id == 8:
            values = ("custom_ai", "Terran", "mech_macro")
        else:
            values = ("empty", "Random", "random_ground")
        slots.append(SlotConfig(slot_id, values[0], 1 if slot_id <= 7 else 2, values[1], values[2]))
    result = CustomLauncherConfig(1, tuple(slots))
    result.validate()
    return result


async def main() -> None:
    probe = config()
    build_runtime_map(
        PROJECT_ROOT, BASE_MAP_FILE, RUNTIME_MAP_FILE, probe,
        strategy_bridge=True, campaign_units_pilot=True,
        active_config_file=RUNTIME_MAP_FILE.with_suffix(".json"),
    )
    process = launch_sc2(discover_sc2_executable(), PORT, 0)
    connection: Sc2Connection | None = None
    try:
        connection = await Sc2Connection.open(PORT)
        await connection.create_game_with_setups(
            RUNTIME_MAP_FILE.name, RUNTIME_MAP_FILE.read_bytes(),
            player_setups(probe), realtime=False,
        )
        await connection.join_game(RACE_VALUES[probe.human.race], "Campaign Roster Verification", None)
        request = sc_pb.Request()
        request.data.CopyFrom(sc_pb.RequestData(ability_id=True, unit_type_id=True, upgrade_id=True))
        data = (await connection.request(request)).data
        units = {item.name: item for item in data.units}
        upgrades = {item.name: item for item in data.upgrades}
        for name, (life, food) in CUSTOM_UNITS.items():
            item = units.get(name)
            if item is None:
                raise RuntimeError(f"CAMPAIGN_ROSTER=FAIL missing {name}")
            print(
                f"catalog {name}: id={item.unit_id} available={item.available} "
                f"ability={item.ability_id} food={item.food_required} life={life}"
            )
            if not item.available or item.ability_id == 0 or item.food_required != food:
                raise RuntimeError(f"CAMPAIGN_ROSTER=FAIL invalid production data for {name}")
        raptor = upgrades.get("SC2TeamRaptorEvolution")
        if raptor is None:
            raise RuntimeError("CAMPAIGN_ROSTER=FAIL missing Raptor upgrade")
        print(f"catalog SC2TeamRaptorEvolution: id={raptor.upgrade_id}")

        await connection.step(90)
        initial = await connection.observation(disable_fog=True)
        owned = [
            unit for unit in initial.observation.raw_data.units
            if unit.owner == 2 and unit.unit_type == 45
        ]
        start = (
            sum(unit.pos.x for unit in owned) / len(owned),
            sum(unit.pos.y for unit in owned) / len(owned),
        )
        for offset, name in enumerate(CUSTOM_UNITS):
            await connection.debug_create_units(units[name].unit_id, 2, start[0] + offset * 3, start[1], 1)
        await connection.debug_create_units(units["Zergling"].unit_id, 2, start[0], start[1] + 3, 1)
        await connection.step(2)
        observation = await connection.observation(disable_fog=True)
        created = {
            unit.unit_type: unit
            for unit in observation.observation.raw_data.units
            if unit.owner == 2 and unit.unit_type in {units[name].unit_id for name in CUSTOM_UNITS}
        }
        print(
            "debug_rows="
            f"{[(unit.unit_type, unit.owner, round(unit.health_max)) for unit in observation.observation.raw_data.units if unit.owner == 2]}"
        )
        for name, (life, _food) in CUSTOM_UNITS.items():
            unit = created.get(units[name].unit_id)
            if unit is None or round(unit.health_max) != life:
                raise RuntimeError(
                    f"CAMPAIGN_ROSTER=FAIL create/stats {name}: "
                    f"{None if unit is None else unit.health_max}"
                )
        print("CAMPAIGN_ROSTER_CATALOG=PASS")
        print("CAMPAIGN_ROSTER_CREATE=PASS")
    finally:
        if connection is not None:
            await connection.quit()
            await connection.close()
        stop_process(process)


if __name__ == "__main__":
    asyncio.run(main())
