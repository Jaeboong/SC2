"""Capture rendered pixels of the campaign roster units.

Every other campaign probe asserts catalog IDs, debug creation, and combat damage.
All of those pass while a unit renders as the gray placeholder sphere, which is how
the Dragoon (v1.10.1) and Predator (v1.10.3, v1.10.4) defects reached the user. This
probe enables the SC2 render interface and writes real PNG frames so the model can
be inspected instead of inferred.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PIL import Image, ImageChops, ImageEnhance
from s2clientprotocol import common_pb2 as common_pb
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
RUNTIME_MAP_FILE = PROJECT_ROOT / "runtime" / "maps" / "campaign-render-probe.SC2Map"
OUTPUT_DIR = PROJECT_ROOT / "runtime" / "render"
PORT = 14128
WIDTH = 1280
HEIGHT = 720

# Each subject is rendered alone next to a known-good control so a gray sphere is
# obvious by comparison rather than by judgement.
SUBJECTS = (
    # "Predator" is Blizzard's own campaign unit. Rendering it next to our
    # SC2TeamPredator separates "the campaign asset cannot load" from "our custom
    # child records are wired wrong".
    ("Predator", "Hellion"),
    ("SC2TeamPredator", "Hellion"),
    ("SC2TeamGoliath", "SiegeTank"),
    ("SC2TeamMedic", "Marine"),
    ("SC2TeamAberration", "Roach"),
    ("HotSTorrasque", "Ultralisk"),
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


async def join_with_render(connection: Sc2Connection, race: int) -> None:
    options = sc_pb.InterfaceOptions(
        raw=True,
        score=True,
        show_cloaked=True,
        render=sc_pb.SpatialCameraSetup(
            resolution=common_pb.Size2DI(x=WIDTH, y=HEIGHT),
            minimap_resolution=common_pb.Size2DI(x=128, y=128),
        ),
    )
    request = sc_pb.Request()
    request.join_game.CopyFrom(
        sc_pb.RequestJoinGame(race=race, options=options, player_name="Render Probe")
    )
    response = (await connection.request(request)).join_game
    if response.HasField("error"):
        raise RuntimeError(f"join failed: {response.error} {response.error_details}")


MINIMAP = 128


async def kill_units(connection: Sc2Connection, tags: list[int]) -> None:
    if not tags:
        return
    request = sc_pb.Request()
    command = request.debug.debug.add()
    command.kill_unit.tag.extend(tags)
    await connection.request(request)


async def map_size(connection: Sc2Connection) -> tuple[int, int]:
    request = sc_pb.Request()
    request.game_info.SetInParent()
    info = (await connection.request(request)).game_info
    size = info.start_raw.map_size
    return size.x, size.y


async def move_camera(
    connection: Sc2Connection, x: float, y: float, size: tuple[int, int]
) -> None:
    # The render interface only accepts a minimap point, so convert world space
    # into minimap pixels. Minimap y grows downward while world y grows upward.
    width, height = size
    request = sc_pb.Request()
    action = request.action.actions.add()
    action.action_render.camera_move.center_minimap.x = round(x / width * MINIMAP)
    action.action_render.camera_move.center_minimap.y = round(
        MINIMAP - y / height * MINIMAP
    )
    await connection.request(request)


def to_image(render) -> Image.Image:
    image = render.map
    size = image.size
    mode = "RGB" if image.bits_per_pixel == 24 else "L"
    return Image.frombytes(mode, (size.x, size.y), image.data)


def isolate(before: Image.Image, after: Image.Image, path: Path) -> str:
    """Save a zoomed crop of screen center, where the camera was just centered.

    A whole-frame pixel diff is useless here because grass, water, and mineral
    sparkle animate every step. The camera is centered on the spawn point, so a
    fixed center window is a more reliable way to frame the subject. The diff is
    still reported as a sanity signal that something actually appeared.
    """
    half_w, half_h = 190, 150
    cx, cy = after.width // 2, after.height // 2
    box = (cx - half_w, cy - half_h, cx + half_w, cy + half_h)
    crop = after.crop(box)
    scale = 3
    crop = crop.resize((crop.width * scale, crop.height * scale), Image.LANCZOS)
    crop = ImageEnhance.Brightness(crop).enhance(2.4)
    crop = ImageEnhance.Contrast(crop).enhance(1.3)
    path.parent.mkdir(parents=True, exist_ok=True)
    crop.save(path)

    window = ImageChops.difference(
        before.convert("RGB").crop(box), after.convert("RGB").crop(box)
    )
    changed = sum(1 for value in window.convert("L").getdata() if value > 40)
    return f"changed_px={changed} center_box={box} scale={scale}x"


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
    process = launch_sc2(discover_sc2_executable(), PORT, 0, width=WIDTH, height=HEIGHT)
    connection: Sc2Connection | None = None
    try:
        connection = await Sc2Connection.open(PORT)
        await connection.create_game_with_setups(
            RUNTIME_MAP_FILE.name,
            RUNTIME_MAP_FILE.read_bytes(),
            player_setups(probe),
            realtime=False,
        )
        await join_with_render(connection, RACE_VALUES[probe.human.race])

        request = sc_pb.Request()
        request.data.CopyFrom(sc_pb.RequestData(unit_type_id=True))
        data = (await connection.request(request)).data
        ids = {unit.name: unit.unit_id for unit in data.units}

        size = await map_size(connection)
        await connection.step(90)
        initial = await connection.observation(disable_fog=True)
        workers = [
            unit
            for unit in initial.observation.raw_data.units
            if unit.owner == 1 and unit.unit_type == ids["SCV"]
        ]
        if not workers:
            raise RuntimeError("RENDER=FAIL no human SCVs")
        base_x = sum(unit.pos.x for unit in workers) / len(workers)
        base_y = sum(unit.pos.y for unit in workers) / len(workers)

        await connection.debug_show_map()
        for subject, control in SUBJECTS:
            if subject not in ids:
                print(f"RENDER[{subject}]=MISSING_CATALOG", flush=True)
                continue
            x = base_x - 6
            y = base_y - 6
            await move_camera(connection, x, y, size)
            await connection.step(8)
            empty = to_image(
                (await connection.observation(disable_fog=True)).observation.render_data
            )

            for label, unit_name in ((subject, subject), (f"{subject}__control", control)):
                await connection.debug_create_units(ids[unit_name], 1, x, y, 1)
                await connection.step(8)
                shot = await connection.observation(disable_fog=True)
                frame = to_image(shot.observation.render_data)
                path = OUTPUT_DIR / f"{label}.png"
                detail = isolate(empty, frame, path)
                print(f"RENDER[{label}]={detail} file={path.name}", flush=True)
                # Remove the unit so the next subject diffs against a clean plate.
                await kill_units(
                    connection,
                    [
                        unit.tag
                        for unit in shot.observation.raw_data.units
                        if unit.owner == 1 and unit.unit_type == ids[unit_name]
                    ],
                )
                await connection.step(8)
            base_y -= 12
        if hold_seconds:
            await asyncio.sleep(hold_seconds)
    finally:
        if connection is not None:
            await connection.quit()
            await connection.close()
        stop_process(process)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--hold-seconds", type=float, default=0.0)
    asyncio.run(main(parser.parse_args().hold_seconds))
