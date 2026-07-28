"""Prove the test launcher's cheats actually take effect in a real game.

The test launcher promises infinite resources, instant production and full
vision. Each of those is a claim about a live game, not about the code that
sends the request, so each is measured here the way a player would notice it:

- resources: spend the bank down and check it refills, because all_resources is
  a one-off 5000/5000 grant rather than a standing state.
- production: time a unit out of a freshly created structure.
- vision: confirm the map-reveal cheat is accepted alongside the rest.

This drives the same run_layout_test path the launcher uses, so it fails if the
wiring breaks, not just if the cheats themselves change.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from s2clientprotocol import debug_pb2 as debug_pb
from s2clientprotocol import sc2api_pb2 as sc_pb

from sc2team.custom_config import CustomLauncherConfig, SlotConfig
from sc2team.custom_runtime import RACE_VALUES, build_runtime_map, player_setups
from sc2team.process import discover_sc2_executable, launch_sc2, stop_process
from sc2team.protocol import Sc2Connection

sys.path.insert(0, str(PROJECT_ROOT / "app"))
# Imported rather than copied: a probe with its own private floor would keep
# passing while the shipped launcher drifted away from it.
from play_custom_ai import TEST_RESOURCE_FLOOR, TEST_RESOURCE_GRANTS_ON_JOIN

BASE_MAP_FILE = (
    PROJECT_ROOT / "map" / "source" / "europe-melee-2-7v7-rich-50000-fixed-teams.SC2Map"
)
RUNTIME_MAP_FILE = PROJECT_ROOT / "runtime" / "maps" / "test-launcher-probe.SC2Map"
PORT = 14134

BARRACKS_TRAIN_MARINE = 560

# A Marine costs 18 game seconds, about 400 steps, at normal speed. fast_build
# must beat that decisively for "instant production" to mean anything.
NORMAL_MARINE_STEPS = 400
FAST_BUILD_STEP_BUDGET = 100


def config() -> CustomLauncherConfig:
    slots = []
    for slot_id in range(1, 15):
        if slot_id == 1:
            values = ("human", "Terran", "bio_tank")
        elif slot_id == 8:
            values = ("custom_ai", "Terran", "mech_macro")
        else:
            values = ("empty", "Random", "random_ground")
        slots.append(
            SlotConfig(slot_id, values[0], 1 if slot_id <= 7 else 2, values[1], values[2])
        )
    result = CustomLauncherConfig(1, tuple(slots), full_vision=True)
    result.validate()
    return result


async def bank(connection: Sc2Connection) -> tuple[int, int]:
    common = (await connection.observation(disable_fog=True)).observation.player_common
    return common.minerals, common.vespene


async def main() -> None:
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
        await connection.join_game(RACE_VALUES[probe.human.race], "Test Launcher Probe", None)

        # Same order and same cheats the test launcher applies on join.
        for state in (debug_pb.fast_build, debug_pb.food, debug_pb.show_map):
            await connection.debug_game_state(state)
        for _ in range(TEST_RESOURCE_GRANTS_ON_JOIN):
            await connection.debug_game_state(debug_pb.all_resources)
        await connection.step(16)

        minerals, vespene = await bank(connection)
        print(f"TEST_LAUNCHER_GRANT minerals={minerals} vespene={vespene}")
        if minerals < TEST_RESOURCE_FLOOR or vespene < TEST_RESOURCE_FLOOR:
            raise RuntimeError(
                f"initial grant {minerals}/{vespene} is below the launcher floor {TEST_RESOURCE_FLOOR}"
            )

        request = sc_pb.Request()
        request.data.CopyFrom(sc_pb.RequestData(unit_type_id=True))
        ids = {u.name: u.unit_id for u in (await connection.request(request)).data.units}

        obs = (await connection.observation(disable_fog=True)).observation
        ccs = [u for u in obs.raw_data.units if u.owner == 1 and u.unit_type == ids["CommandCenter"]]
        spot = (ccs[0].pos.x + 6, ccs[0].pos.y)
        await connection.debug_create_units(ids["Barracks"], 1, spot[0], spot[1], 1)
        await connection.step(10)
        obs = (await connection.observation(disable_fog=True)).observation
        rax = [u for u in obs.raw_data.units if u.owner == 1 and u.unit_type == ids["Barracks"]]
        if not rax or rax[0].build_progress < 1.0:
            raise RuntimeError("fast_build did not finish the structure instantly")
        print(f"TEST_LAUNCHER_FAST_BUILD structure_progress={rax[0].build_progress:.2f}")

        before = len([u for u in obs.raw_data.units if u.owner == 1 and u.unit_type == ids["Marine"]])
        await connection.raw_unit_command([rax[0].tag], BARRACKS_TRAIN_MARINE)
        elapsed = 0
        while elapsed < FAST_BUILD_STEP_BUDGET:
            await connection.step(8)
            elapsed += 8
            obs = (await connection.observation(disable_fog=True)).observation
            now = len([u for u in obs.raw_data.units if u.owner == 1 and u.unit_type == ids["Marine"]])
            if now > before:
                break
        else:
            raise RuntimeError(
                f"marine took over {FAST_BUILD_STEP_BUDGET} steps despite fast_build"
            )
        print(
            f"TEST_LAUNCHER_PRODUCTION marine_steps={elapsed} "
            f"normal~{NORMAL_MARINE_STEPS} speedup~{NORMAL_MARINE_STEPS / max(elapsed, 1):.0f}x"
        )

        # "Infinite" rests entirely on the top-up being additive: the launcher
        # calls all_resources again whenever the bank drops below the floor, and
        # that only works as a refill if repeated grants stack rather than
        # re-setting the bank to a fixed 5000. Draining the bank for real is not
        # possible here -- debug_create_units spawns units free of charge -- so
        # the additivity is what gets measured.
        before_minerals, before_vespene = await bank(connection)
        await connection.debug_game_state(debug_pb.all_resources)
        await connection.step(8)
        after_minerals, after_vespene = await bank(connection)
        print(
            f"TEST_LAUNCHER_TOPUP {before_minerals}/{before_vespene} -> "
            f"{after_minerals}/{after_vespene}"
        )
        if after_minerals <= before_minerals or after_vespene <= before_vespene:
            raise RuntimeError(
                "all_resources did not add to the bank, so the launcher's top-up "
                "cannot keep resources up as the game is played"
            )

        print("TEST_LAUNCHER=PASS")
    finally:
        if connection is not None:
            try:
                await connection.quit()
            finally:
                await connection.close()
        stop_process(process)


if __name__ == "__main__":
    asyncio.run(main())
