"""Measure where a melee roster unit stops when told to attack a building.

The gray-sphere bug taught us that catalog, create and combat probes all pass on
a unit that is visibly wrong: "it dealt damage" says nothing about where the
attacker was standing when it did. Players reported roster melee units walking
*into* buildings, so this probe measures the thing they actually saw -- the
center-to-center distance at the moment the attacker settles -- and compares it
against the same measurement for Blizzard's own campaign unit on the same target.

A melee attacker should come to rest roughly at the point where the two collision
footprints touch, so distance ~= attacker.radius + target.radius. Stopping much
closer than the target's own radius means the attacker is standing inside the
building's footprint, which is the reported defect.
"""

from __future__ import annotations

import asyncio
from math import hypot
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
    PROJECT_ROOT / "maps" / "generated" / "europe-melee-2-7v7-rich-50000-fixed-teams.SC2Map"
)
RUNTIME_MAP_FILE = PROJECT_ROOT / "runtime" / "maps" / "melee-approach-probe.SC2Map"
PORT = 14128
ATTACK_ABILITY_ID = 23
TARGET_STRUCTURE = "Barracks"

# Each attacker is placed this far from the target so it has to walk in, and is
# given this many steps to close the gap and settle before being measured.
APPROACH_OFFSET = 8.0
SETTLE_STEPS = 224

# SC2TeamPredator parents from campaign Predator, so it should stop exactly where
# the original stops, and measured drift is 0.000. The v1.10.5 roster, which
# parented from HellionTank and declared Radius 0.5 against a model built for
# 0.625, drifted 0.241: it stopped 0.137 from a wall of radius 1.812 and pushed a
# third of the cat inside the building. This tolerance is deliberately tight
# enough to fail that build; loosening it re-admits the reported defect.
CONTROL_TOLERANCE = 0.1

SUBJECTS = ("Predator", "SC2TeamPredator", "SC2TeamAberration")
CONTROL = "Predator"


async def kill_units(connection: Sc2Connection, tags: list[int]) -> None:
    if not tags:
        return
    request = sc_pb.Request()
    command = request.debug.debug.add()
    command.kill_unit.tag.extend(tags)
    await connection.request(request)


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
    result = CustomLauncherConfig(1, tuple(slots))
    result.validate()
    return result


def nearest(units, unit_type: int, owner: int, position: tuple[float, float]):
    candidates = [u for u in units if u.unit_type == unit_type and u.owner == owner]
    if not candidates:
        raise RuntimeError(f"No unit_type={unit_type} owned by P{owner} was found")
    return min(candidates, key=lambda u: hypot(u.pos.x - position[0], u.pos.y - position[1]))


async def measure(connection, ids, name: str, point: tuple[float, float]) -> dict[str, float]:
    target_point = (point[0] + APPROACH_OFFSET, point[1])
    await connection.debug_create_units(ids[name], 1, point[0], point[1], 1)
    await connection.debug_create_units(ids[TARGET_STRUCTURE], 2, target_point[0], target_point[1], 1)
    await connection.step(2)

    before = await connection.observation(disable_fog=True)
    attacker = nearest(before.observation.raw_data.units, ids[name], 1, point)
    target = nearest(before.observation.raw_data.units, ids[TARGET_STRUCTURE], 2, target_point)

    result = await connection.raw_unit_command(
        [attacker.tag], ATTACK_ABILITY_ID, target_unit_tag=target.tag
    )
    if result != (1,):
        raise RuntimeError(f"{name}: attack command rejected: {result}")
    await connection.step(SETTLE_STEPS)

    after = await connection.observation(disable_fog=True)
    moved = next((u for u in after.observation.raw_data.units if u.tag == attacker.tag), None)
    if moved is None:
        raise RuntimeError(f"{name}: attacker died during the approach")
    structure = next((u for u in after.observation.raw_data.units if u.tag == target.tag), None)
    if structure is None:
        raise RuntimeError(f"{name}: target was destroyed before it could be measured")

    distance = hypot(moved.pos.x - structure.pos.x, moved.pos.y - structure.pos.y)
    touching = moved.radius + structure.radius
    # An attacker still sitting on its spawn point never engaged, so there is no
    # approach to measure. Running the subjects at different offsets hid this:
    # one offset happened to be unpathable and every unit placed there "failed",
    # which measures the terrain rather than the unit. Every subject now runs at
    # the same spot, so this can only mean the unit itself refused to close.
    travelled = hypot(moved.pos.x - point[0], moved.pos.y - point[1])
    if travelled < 1.0:
        raise RuntimeError(
            f"{name}: never left its spawn point (moved {travelled:.3f}); it did "
            "not engage the structure at all"
        )
    measurement = {
        "distance": distance,
        "attacker_radius": moved.radius,
        "target_radius": structure.radius,
        "touching": touching,
        "overlap": touching - distance,
    }
    print(
        f"APPROACH[{name}] distance={distance:.3f} "
        f"attacker_radius={moved.radius:.3f} target_radius={structure.radius:.3f} "
        f"touching_at={touching:.3f} overlap={measurement['overlap']:+.3f}"
    )
    await kill_units(connection, [moved.tag, structure.tag])
    await connection.step(4)
    # Standing closer to the center than the building's own radius means the
    # attacker is inside the footprint -- exactly what players reported.
    if distance < structure.radius:
        raise RuntimeError(
            f"{name}: stopped {distance:.3f} from the center of a structure whose "
            f"radius is {structure.radius:.3f}; the attacker is inside the building"
        )
    return measurement


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
        await connection.join_game(RACE_VALUES[probe.human.race], "Melee Approach Verification", None)

        request = sc_pb.Request()
        request.data.CopyFrom(sc_pb.RequestData(unit_type_id=True))
        data = (await connection.request(request)).data
        ids = {unit.name: unit.unit_id for unit in data.units}
        missing = [name for name in (*SUBJECTS, TARGET_STRUCTURE) if name not in ids]
        if missing:
            raise RuntimeError(f"Catalog is missing: {missing}")

        await connection.step(90)
        initial = await connection.observation(disable_fog=True)
        workers = [
            u for u in initial.observation.raw_data.units if u.owner == 1 and u.unit_type == 45
        ]
        center = (
            sum(u.pos.x for u in workers) / len(workers),
            sum(u.pos.y for u in workers) / len(workers),
        )

        # One shared, known-pathable spot for every subject, run one at a time and
        # cleared in between, so the only variable left is the unit itself.
        spot = (center[0] + 12, center[1] - 14)
        results: dict[str, dict[str, float]] = {}
        for name in SUBJECTS:
            results[name] = await measure(connection, ids, name, spot)

        control = results[CONTROL]["distance"]
        ours = results["SC2TeamPredator"]["distance"]
        drift = abs(ours - control)
        print(
            f"APPROACH_CONTROL_DRIFT SC2TeamPredator={ours:.3f} "
            f"{CONTROL}={control:.3f} drift={drift:.3f} tolerance={CONTROL_TOLERANCE}"
        )
        if drift > CONTROL_TOLERANCE:
            raise RuntimeError(
                f"SC2TeamPredator stops {drift:.3f} from where campaign {CONTROL} "
                "stops; it no longer inherits the original's approach behavior"
            )
        print("MELEE_APPROACH=PASS")
    finally:
        if connection is not None:
            try:
                await connection.quit()
            finally:
                await connection.close()
        stop_process(process)


if __name__ == "__main__":
    asyncio.run(main())
