from __future__ import annotations

import argparse
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


BASE_MAP_FILE = (
    PROJECT_ROOT
    / "maps"
    / "generated"
    / "europe-melee-2-7v7-rich-50000-fixed-teams.SC2Map"
)
RUNTIME_MAP_FILE = PROJECT_ROOT / "runtime" / "maps" / "campaign-visual-probe.SC2Map"
PORT = 14127
VISUAL_UNITS = (
    "SC2TeamGoliath",
    "SC2TeamPredator",
    "SC2TeamMedic",
    "SC2TeamAberration",
    "HotSTorrasque",
    "Zergling",
)


def config() -> CustomLauncherConfig:
    slots = []
    for slot_id in range(1, 15):
        if slot_id == 1:
            values = ("human", "Terran", "bio_tank")
        elif slot_id == 8:
            values = ("custom_ai", "Zerg", "ultra_ling_bane")
        else:
            values = ("empty", "Random", "random_ground")
        slots.append(
            SlotConfig(
                slot_id,
                values[0],
                1 if slot_id <= 7 else 2,
                values[1],
                values[2],
            )
        )
    result = CustomLauncherConfig(1, tuple(slots))
    result.validate()
    return result


async def main(hold_seconds: float) -> None:
    probe = config()
    build_runtime_map(
        PROJECT_ROOT,
        BASE_MAP_FILE,
        RUNTIME_MAP_FILE,
        probe,
        strategy_bridge=False,
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
            player_setups(probe),
            realtime=False,
        )
        await connection.join_game(
            RACE_VALUES[probe.human.race],
            "Campaign Visual Verification",
            None,
        )
        request = sc_pb.Request()
        request.data.CopyFrom(sc_pb.RequestData(unit_type_id=True))
        data = (await connection.request(request)).data
        ids = {unit.name: unit.unit_id for unit in data.units}
        missing = [name for name in VISUAL_UNITS if name not in ids]
        if missing:
            raise RuntimeError(f"CAMPAIGN_VISUAL=FAIL missing catalog units: {missing}")

        await connection.step(90)
        initial = await connection.observation(disable_fog=True)
        workers = [
            unit
            for unit in initial.observation.raw_data.units
            if unit.owner == 1 and unit.unit_type == ids["SCV"]
        ]
        if not workers:
            raise RuntimeError("CAMPAIGN_VISUAL=FAIL no human SCVs")
        center_x = sum(unit.pos.x for unit in workers) / len(workers)
        center_y = sum(unit.pos.y for unit in workers) / len(workers)

        # Keep the row close to the initial human camera. The first five entries
        # cover every asset-bearing campaign model used by the roster pilot;
        # Zergling provides an adjacent baseline model for comparison.
        for index, name in enumerate(VISUAL_UNITS):
            await connection.debug_create_units(
                ids[name],
                1,
                center_x - 8 + index * 3.2,
                center_y - 5,
                1,
            )
        await connection.debug_show_map()
        await connection.step(2)
        observation = await connection.observation(disable_fog=True)
        created = [
            unit
            for unit in observation.observation.raw_data.units
            if unit.owner == 1 and unit.unit_type in {ids[name] for name in VISUAL_UNITS}
        ]
        if len(created) < len(VISUAL_UNITS):
            raise RuntimeError(
                f"CAMPAIGN_VISUAL=FAIL created {len(created)}/{len(VISUAL_UNITS)} units"
            )
        print("CAMPAIGN_VISUAL_READY=" + ",".join(VISUAL_UNITS), flush=True)
        print(f"CAMPAIGN_VISUAL_HOLD_SECONDS={hold_seconds:g}", flush=True)
        await asyncio.sleep(hold_seconds)
    finally:
        if connection is not None:
            await connection.quit()
            await connection.close()
        stop_process(process)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Open an SC2 visual probe containing all asset-bearing campaign units."
    )
    parser.add_argument(
        "--hold-seconds",
        type=float,
        default=300.0,
        help="How long to keep the visual probe open (default: 300).",
    )
    args = parser.parse_args()
    asyncio.run(main(args.hold_seconds))
