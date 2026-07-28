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


ATTACK_ABILITY_ID = 23


BASE_MAP_FILE = (
    PROJECT_ROOT
    / "map"
    / "source"
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


async def main(hold_seconds: float, attack: bool) -> None:
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

        target_tag: int | None = None
        if attack:
            # Attack animation cannot be verified numerically: verify_campaign_combat
            # saturates (every attacker kills the 125-life Marauder inside its step
            # budget, so damage=125 whether the weapon reaches at range 1.5 or has
            # to walk into contact at 0.1). Give the row one shared enemy and a
            # standing attack order so the swing itself can be watched.
            #
            # The target is a Nexus, not a combat unit: it never fights back, so
            # the subjects survive the whole hold (an enemy Ultralisk one-shots
            # the 60-life Medic). Its life is topped up every tick below so it
            # never dies either and the animation loop runs indefinitely.
            await connection.debug_create_units(
                ids["Nexus"], 2, center_x, center_y - 12, 1
            )
            await connection.step(2)
            engaged = await connection.observation(disable_fog=True)
            target = next(
                (
                    unit
                    for unit in engaged.observation.raw_data.units
                    if unit.owner == 2 and unit.unit_type == ids["Nexus"]
                ),
                None,
            )
            if target is None:
                raise RuntimeError("CAMPAIGN_VISUAL=FAIL enemy target was not created")
            target_tag = target.tag
            subjects = [
                unit
                for unit in engaged.observation.raw_data.units
                if unit.owner == 1 and unit.unit_type in {ids[n] for n in VISUAL_UNITS}
            ]
            ordered = 0
            for subject in subjects:
                result = await connection.raw_unit_command(
                    [subject.tag], ATTACK_ABILITY_ID, target_unit_tag=target_tag
                )
                if result == (1,):
                    ordered += 1
                else:
                    print(
                        f"CAMPAIGN_VISUAL_ATTACK_REJECTED={subject.unit_type} {result}",
                        flush=True,
                    )
            print(f"CAMPAIGN_VISUAL_ATTACK_ORDERED={ordered}", flush=True)

        print(f"CAMPAIGN_VISUAL_HOLD_SECONDS={hold_seconds:g}", flush=True)
        # The game is in step mode, so a plain sleep freezes the simulation and no
        # animation ever plays. Advance it in small chunks paced to wall-clock so
        # the hold runs at normal (1x) speed for a human watching the window.
        # 22.4 game loops per second is SC2's "Faster" rate, which is what the
        # client renders at.
        loops_per_second = 22.4
        chunk = 4
        chunk_seconds = chunk / loops_per_second
        elapsed = 0.0
        while elapsed < hold_seconds:
            await connection.step(chunk)
            if target_tag is not None:
                await connection.debug_set_unit_life(target_tag, 1000.0)
                await connection.debug_set_unit_shields(target_tag, 1000.0)
            await asyncio.sleep(chunk_seconds)
            elapsed += chunk_seconds
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
    parser.add_argument(
        "--attack",
        action="store_true",
        help="Spawn a durable enemy per subject and issue a standing attack order "
             "so the attack animation can be watched (verify_campaign_combat "
             "saturates and cannot show it).",
    )
    args = parser.parse_args()
    asyncio.run(main(args.hold_seconds, args.attack))
