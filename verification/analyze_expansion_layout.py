"""Extract every live resource base, solve depot positions, and render a PNG.

The solver intentionally follows the well-tested python-sc2 geometry, then adds
two checks needed by this unusually dense 14-player map:

* a full 5x5 placement-grid footprint instead of checking only the center;
* SC2's own building-placement and pathing queries for the chosen points.

Outputs:
  runtime/reports/expansion-layout.json
  runtime/reports/expansion-layout.png
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import itertools
import json
import math
from pathlib import Path
import sys

from PIL import Image, ImageDraw, ImageFont
from s2clientprotocol import common_pb2 as common_pb
from s2clientprotocol import sc2api_pb2 as sc_pb

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sc2team.custom_config import CustomLauncherConfig
from sc2team.custom_runtime import RACE_VALUES, build_runtime_map, player_setups
from sc2team.process import discover_sc2_executable, launch_sc2, stop_process
from sc2team.protocol import Sc2Connection


BASE_MAP = (
    PROJECT_ROOT
    / "maps"
    / "generated"
    / "europe-melee-2-7v7-rich-50000-fixed-teams.SC2Map"
)
PROBE_MAP = PROJECT_ROOT / "runtime" / "maps" / "expansion-layout-probe.SC2Map"
REPORT_DIR = PROJECT_ROOT / "runtime" / "reports"
JSON_PATH = REPORT_DIR / "expansion-layout.json"
PNG_PATH = REPORT_DIR / "expansion-layout.png"
BUILD_JSON_PATH = PROJECT_ROOT / "tools" / "build" / "expansion-layout.json"
PORT = 14330

RESOURCE_SPREAD_THRESHOLD = 8.5
GAS_DISTANCE_WEIGHT = 3.0
MINERAL_CLEARANCE = 6.0
GAS_CLEARANCE = 7.0
EXPANSION_GAP_THRESHOLD = 15.0
TERRAIN_LEVEL_TOLERANCE = 8
DEPOT_DEDUP_DISTANCE = 10.0
TOWN_HALL_TYPES = {18, 59, 86, 100, 101, 130, 132}
COMMAND_CENTER_BUILD_ABILITY = 318
TOWN_HALL_ABILITIES = {"Terran": 318, "Protoss": 880, "Zerg": 1152}
EXPECTED_STARTS = {
    1: (28.5, 11.5), 2: (27.5, 47.5), 3: (13.5, 90.5),
    4: (10.5, 144.5), 5: (61.5, 181.5), 6: (47.5, 221.5),
    7: (8.5, 245.5), 8: (199.5, 14.5), 9: (246.5, 32.5),
    10: (186.5, 60.5), 11: (200.5, 129.5), 12: (231.5, 159.5),
    13: (161.5, 188.5), 14: (237.5, 240.5),
}


@dataclass(frozen=True)
class Resource:
    x: float
    y: float
    gas: bool
    unit_type: int


@dataclass
class BaseCandidate:
    resources: list[Resource]
    x: float
    y: float
    geometry_score: float
    placement_result: int = 0
    covered_by: list[int] | None = None
    pathing: dict[int, float] | None = None
    options: list[tuple[float, float, float]] | None = None
    race_positions: dict[str, tuple[float, float]] | None = None
    race_results: dict[str, int] | None = None

    @property
    def minerals(self) -> int:
        return sum(not resource.gas for resource in self.resources)

    @property
    def gases(self) -> int:
        return sum(resource.gas for resource in self.resources)


def distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def placement_bits(image_data) -> list[list[int]]:
    width, height = image_data.size.x, image_data.size.y
    unpacked: list[int] = []
    for value in image_data.data:
        unpacked.extend((value >> shift) & 1 for shift in range(7, -1, -1))
    if len(unpacked) != width * height:
        raise RuntimeError(
            f"placement grid size mismatch: {len(unpacked)} != {width}x{height}"
        )
    return [unpacked[y * width : (y + 1) * width] for y in range(height)]


def terrain_bytes(image_data) -> list[list[int]]:
    width, height = image_data.size.x, image_data.size.y
    values = list(image_data.data)
    if len(values) != width * height:
        raise RuntimeError(
            f"terrain-height grid size mismatch: {len(values)} != {width}x{height}"
        )
    return [values[y * width : (y + 1) * width] for y in range(height)]


def resource_height(resource: Resource, heights: list[list[int]]) -> int:
    y = min(max(round(resource.y), 0), len(heights) - 1)
    x = min(max(round(resource.x), 0), len(heights[0]) - 1)
    return heights[y][x]


def split_resource_component(group: list[Resource]) -> list[list[Resource]]:
    """Split chained/double resource lines into one economy base per group.

    Normal bases have at most ten mineral patches and two geysers.  Dense areas
    on this map put two bases within the single-link radius, so an unrestricted
    flood fill merges both sides of a cliff or two adjacent crescents.  Gas
    pairs provide stable initial centers; deterministic Lloyd refinement then
    assigns each mineral line to the nearest base.
    """
    mineral_count = sum(not resource.gas for resource in group)
    gas_count = sum(resource.gas for resource in group)
    base_count = max(1, math.ceil(mineral_count / 10), math.ceil(gas_count / 2))
    if base_count == 1:
        return [group]

    gases = [resource for resource in group if resource.gas]
    unused = set(range(len(gases)))
    centers: list[tuple[float, float]] = []
    while len(unused) >= 2 and len(centers) < base_count:
        left, right = min(
            itertools.combinations(unused, 2),
            key=lambda pair: distance(
                (gases[pair[0]].x, gases[pair[0]].y),
                (gases[pair[1]].x, gases[pair[1]].y),
            ),
        )
        centers.append(
            ((gases[left].x + gases[right].x) / 2, (gases[left].y + gases[right].y) / 2)
        )
        unused.remove(left)
        unused.remove(right)
    points = [(resource.x, resource.y) for resource in group]
    if not centers:
        centers.append(min(points))
    while len(centers) < base_count:
        centers.append(
            max(points, key=lambda point: min(distance(point, center) for center in centers))
        )

    assignments: list[list[Resource]] = []
    for _ in range(20):
        assignments = [[] for _ in centers]
        for resource in group:
            index = min(
                range(len(centers)),
                key=lambda candidate: distance((resource.x, resource.y), centers[candidate]),
            )
            assignments[index].append(resource)
        new_centers = []
        for index, members in enumerate(assignments):
            if not members:
                new_centers.append(centers[index])
                continue
            weights = [GAS_DISTANCE_WEIGHT if member.gas else 1.0 for member in members]
            total = sum(weights)
            new_centers.append(
                (
                    sum(member.x * weight for member, weight in zip(members, weights)) / total,
                    sum(member.y * weight for member, weight in zip(members, weights)) / total,
                )
            )
        if all(distance(old, new) < 0.01 for old, new in zip(centers, new_centers)):
            break
        centers = new_centers

    # A tiny fragment is not a base. Attach it to the nearest real mineral line.
    valid = [members for members in assignments if sum(not item.gas for item in members) >= 4]
    rejected = [members for members in assignments if sum(not item.gas for item in members) < 4]
    for members in rejected:
        if not valid:
            continue
        for resource in members:
            target = min(
                valid,
                key=lambda candidate: distance(
                    (resource.x, resource.y),
                    (
                        sum(item.x for item in candidate) / len(candidate),
                        sum(item.y for item in candidate) / len(candidate),
                    ),
                ),
            )
            target.append(resource)
    return valid


def cluster_resources(
    resources: list[Resource], heights: list[list[int]]
) -> list[list[Resource]]:
    groups = [[resource] for resource in resources]
    changed = True
    while changed:
        changed = False
        for left_index, right_index in itertools.combinations(range(len(groups)), 2):
            left, right = groups[left_index], groups[right_index]
            if any(
                abs(resource_height(a, heights) - resource_height(b, heights))
                <= TERRAIN_LEVEL_TOLERANCE
                and distance((a.x, a.y), (b.x, b.y)) <= RESOURCE_SPREAD_THRESHOLD
                for a in left
                for b in right
            ):
                groups[left_index] = left + right
                groups.pop(right_index)
                changed = True
                break
    return [split for group in groups for split in split_resource_component(group)]


def footprint_buildable(
    grid: list[list[int]], x: float, y: float, *, radius: int = 2
) -> bool:
    height, width = len(grid), len(grid[0])
    center_x, center_y = int(x), int(y)
    for tile_y in range(center_y - radius, center_y + radius + 1):
        for tile_x in range(center_x - radius, center_x + radius + 1):
            if not (0 <= tile_x < width and 0 <= tile_y < height):
                return False
            if grid[tile_y][tile_x] == 0:
                return False
    return True


def solve_candidate(
    group: list[Resource],
    grid: list[list[int]],
    heights: list[list[int]],
    all_resources: list[Resource],
) -> BaseCandidate | None:
    minerals = sum(not resource.gas for resource in group)
    # Single decorations and gas-only groups are not economy bases.
    if minerals < 4:
        return None
    group_heights = sorted(resource_height(resource, heights) for resource in group)
    target_height = group_heights[len(group_heights) // 2]
    center_x = int(sum(resource.x for resource in group) / len(group)) + 0.5
    center_y = int(sum(resource.y for resource in group) / len(group)) + 0.5
    options: list[tuple[float, float, float]] = []
    for offset_x in range(-12, 13):
        for offset_y in range(-12, 13):
            if math.hypot(offset_x, offset_y) > 12.0:
                continue
            x, y = center_x + offset_x, center_y + offset_y
            if not footprint_buildable(grid, x, y):
                continue
            candidate_height = heights[min(max(round(y), 0), len(heights) - 1)][
                min(max(round(x), 0), len(heights[0]) - 1)
            ]
            if abs(candidate_height - target_height) > TERRAIN_LEVEL_TOLERANCE:
                continue
            if any(
                distance((x, y), (resource.x, resource.y))
                <= (GAS_CLEARANCE if resource.gas else MINERAL_CLEARANCE)
                for resource in all_resources
            ):
                continue
            distances = [distance((x, y), (resource.x, resource.y)) for resource in group]
            mineral_distances = [
                value for value, resource in zip(distances, group) if not resource.gas
            ]
            gas_distances = [
                value for value, resource in zip(distances, group) if resource.gas
            ]
            # A geyser feeds three workers and must not be treated like one mineral
            # patch. This pulls the depot into the mineral/gas pocket instead of
            # behind the mineral crescent, while the maximum term prevents a good
            # average from hiding one remote half of a resource line.
            score = (
                sum(mineral_distances)
                + GAS_DISTANCE_WEIGHT * sum(gas_distances)
                + max(distances) * 0.75
            )
            options.append((score, x, y))
    if not options:
        return None
    options.sort()
    best = options[0]
    return BaseCandidate(group, best[1], best[2], best[0], options=options[:80])


def merge_duplicate_candidates(
    candidates: list[BaseCandidate],
    grid: list[list[int]],
    heights: list[list[int]],
    all_resources: list[Resource],
) -> list[BaseCandidate]:
    """Collapse resource fragments that solve to the same town-hall footprint."""
    merged = list(candidates)
    while True:
        pair = next(
            (
                (left, right)
                for left, right in itertools.combinations(range(len(merged)), 2)
                if distance(
                    (merged[left].x, merged[left].y),
                    (merged[right].x, merged[right].y),
                ) < DEPOT_DEDUP_DISTANCE
            ),
            None,
        )
        if pair is None:
            return merged
        left, right = pair
        resources = list(dict.fromkeys(merged[left].resources + merged[right].resources))
        replacement = solve_candidate(resources, grid, heights, all_resources)
        if replacement is None:
            # The two 5x5 footprints overlap, so keeping both is never valid.
            replacement = min(
                (merged[left], merged[right]), key=lambda candidate: candidate.geometry_score
            )
        merged[left] = replacement
        merged.pop(right)


async def engine_queries(
    connection: Sc2Connection,
    candidates: list[BaseCandidate],
    path_starts: dict[int, tuple[float, float]],
) -> None:
    placement_request = sc_pb.Request()
    placement_request.query.ignore_resource_requirements = True
    placement_order: list[tuple[BaseCandidate, str]] = []
    for candidate in candidates:
        candidate.race_positions = {}
        candidate.race_results = {}
        for race, ability in TOWN_HALL_ABILITIES.items():
            query = placement_request.query.placements.add()
            query.ability_id = ability
            query.target_pos.x = candidate.x
            query.target_pos.y = candidate.y
            placement_order.append((candidate, race))
    placement_response = await connection.request(placement_request)
    for (candidate, race), result in zip(
        placement_order, placement_response.query.placements
    ):
        candidate.race_results[race] = int(result.result)
        # The live query also rejects temporary blockers (starting workers,
        # neutral guards and creep at game loop 0).  The geometry point already
        # passed the static 5x5 placement grid and resource clearances, so do not
        # move a town hall to the wrong side of its mineral line merely to dodge
        # a unit that will move. Keep the query result as diagnostics only.
        candidate.race_positions[race] = (candidate.x, candidate.y)
        if race == "Terran":
            candidate.placement_result = int(result.result)

    path_request = sc_pb.Request()
    order: list[tuple[BaseCandidate, int]] = []
    for candidate in candidates:
        candidate.pathing = {}
        for player, start in path_starts.items():
            query = path_request.query.pathing.add()
            query.start_pos.x, query.start_pos.y = start
            query.end_pos.x, query.end_pos.y = candidate.x, candidate.y
            order.append((candidate, player))
    path_response = await connection.request(path_request)
    for (candidate, player), result in zip(order, path_response.query.pathing):
        candidate.pathing[player] = round(float(result.distance), 2)


def assign_covered_starts(
    candidates: list[BaseCandidate], starts: dict[int, tuple[float, float]]
) -> None:
    """Bind each actual starting hall to exactly one resource base.

    Radius-only marking hid legitimate pocket expansions whose depot center is
    close to the main. A town hall can cover only its nearest resource group.
    """
    for candidate in candidates:
        candidate.covered_by = []
    for player, start in starts.items():
        nearest = min(
            candidates,
            key=lambda candidate: distance((candidate.x, candidate.y), start),
        )
        if distance((nearest.x, nearest.y), start) < EXPANSION_GAP_THRESHOLD:
            nearest.covered_by.append(player)


def draw_report(
    grid: list[list[int]],
    resources: list[Resource],
    candidates: list[BaseCandidate],
    starts: dict[int, tuple[float, float]],
) -> None:
    map_width, map_height = len(grid[0]), len(grid)
    scale = 3
    map_px = max(map_width, map_height) * scale
    margin = 30
    right_width = 520
    image = Image.new("RGB", (map_px + right_width + margin * 3, map_px + margin * 2), "#11161b")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()

    def world_to_full(x: float, y: float) -> tuple[int, int]:
        return margin + round(x * scale), margin + round((map_height - y) * scale)

    # Placement terrain.
    terrain = Image.new("RGB", (map_width, map_height))
    terrain_pixels = terrain.load()
    for y in range(map_height):
        for x in range(map_width):
            terrain_pixels[x, map_height - 1 - y] = (
                (45, 63, 54) if grid[y][x] else (27, 31, 37)
            )
    terrain = terrain.resize((map_width * scale, map_height * scale), Image.Resampling.NEAREST)
    image.paste(terrain, (margin, margin))

    # Resource-to-candidate association makes cluster mistakes visible.
    for index, candidate in enumerate(candidates, 1):
        cx, cy = world_to_full(candidate.x, candidate.y)
        for resource in candidate.resources:
            rx, ry = world_to_full(resource.x, resource.y)
            draw.line((cx, cy, rx, ry), fill="#4b5963", width=1)
    for resource in resources:
        x, y = world_to_full(resource.x, resource.y)
        color = "#4ee07a" if resource.gas else "#f0cf42"
        radius = 4 if resource.gas else 3
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color)
    for index, candidate in enumerate(candidates, 1):
        x, y = world_to_full(candidate.x, candidate.y)
        color = "#7f8c98" if candidate.covered_by else "#4aa8ff"
        draw.rectangle((x - 7, y - 7, x + 7, y + 7), outline=color, width=2)
        draw.text((x + 8, y - 7), str(index), fill="#ffffff", font=font)
    for player, (start_x, start_y) in starts.items():
        x, y = world_to_full(start_x, start_y)
        draw.ellipse((x - 7, y - 7, x + 7, y + 7), outline="#ff5f57", width=3)
        draw.text((x + 8, y + 2), f"P{player}", fill="#ffb0aa", font=font)

    panel_x = map_px + margin * 2
    draw.text((panel_x, margin), "Expansion solver", fill="white", font=font)
    legend = [
        "yellow=mineral  green=gas",
        "blue=available depot  gray=covered by start",
        "red=P1-P13 starting town halls",
        f"clusters={len(candidates)} resources={len(resources)}",
        "T/P/Z positions are engine-validated per race",
    ]
    for row, line in enumerate(legend, 1):
        draw.text((panel_x, margin + row * 17), line, fill="#c8d0d8", font=font)

    # Two zoom panels requested by the observed failure.
    def zoom_box(
        title: str, center: tuple[float, float], top: int, half_span: float = 42.0
    ) -> None:
        left, size = panel_x, 225
        draw.rectangle((left, top, left + size, top + size), fill="#1b2329", outline="#5b6870")
        min_x, min_y = center[0] - half_span, center[1] - half_span
        factor = size / (half_span * 2)

        def zpoint(x: float, y: float) -> tuple[int, int]:
            return (
                left + round((x - min_x) * factor),
                top + size - round((y - min_y) * factor),
            )

        for candidate_index, candidate in enumerate(candidates, 1):
            if distance((candidate.x, candidate.y), center) > half_span * 1.35:
                continue
            cx, cy = zpoint(candidate.x, candidate.y)
            for resource in candidate.resources:
                rx, ry = zpoint(resource.x, resource.y)
                if left <= rx <= left + size and top <= ry <= top + size:
                    draw.line((cx, cy, rx, ry), fill="#46535c")
        for resource in resources:
            if abs(resource.x - center[0]) > half_span or abs(resource.y - center[1]) > half_span:
                continue
            x, y = zpoint(resource.x, resource.y)
            color = "#4ee07a" if resource.gas else "#f0cf42"
            draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill=color)
        for candidate_index, candidate in enumerate(candidates, 1):
            if abs(candidate.x - center[0]) > half_span or abs(candidate.y - center[1]) > half_span:
                continue
            x, y = zpoint(candidate.x, candidate.y)
            color = "#7f8c98" if candidate.covered_by else "#4aa8ff"
            draw.rectangle((x - 8, y - 8, x + 8, y + 8), outline=color, width=2)
            draw.text((x + 9, y - 7), f"{candidate_index} ({candidate.x:g},{candidate.y:g})", fill="white", font=font)
        for player, start in starts.items():
            if abs(start[0] - center[0]) > half_span or abs(start[1] - center[1]) > half_span:
                continue
            x, y = zpoint(*start)
            draw.ellipse((x - 8, y - 8, x + 8, y + 8), outline="#ff5f57", width=3)
            draw.text((x + 9, y + 2), f"P{player}", fill="#ffb0aa", font=font)
        draw.text((left + 5, top + 5), title, fill="white", font=font)

    zoom_box("P12 area", starts.get(12, (231.5, 159.5)), margin + 110)
    zoom_box("P13 area", starts.get(13, (161.5, 188.5)), margin + 355)
    PNG_PATH.parent.mkdir(parents=True, exist_ok=True)
    image.save(PNG_PATH)


async def main() -> None:
    config = CustomLauncherConfig.from_dict(
        json.loads(
            (PROJECT_ROOT / "runtime" / "custom_ai_settings.json").read_text(
                encoding="utf-8"
            )
        )
    )
    build_runtime_map(
        PROJECT_ROOT,
        BASE_MAP,
        PROBE_MAP,
        config,
        strategy_bridge=True,
        campaign_units_pilot=True,
    )
    process = launch_sc2(discover_sc2_executable(), PORT, 0)
    connection: Sc2Connection | None = None
    try:
        connection = await Sc2Connection.open(PORT)
        await connection.create_game_with_setups(
            PROBE_MAP.name,
            PROBE_MAP.read_bytes(),
            player_setups(config),
            realtime=False,
        )
        await connection.join_game(RACE_VALUES["Terran"], "Expansion layout analyzer", None)
        observation = await connection.observation(disable_fog=True)
        info_request = sc_pb.Request()
        info_request.game_info.SetInParent()
        game_info = (await connection.request(info_request)).game_info
        grid = placement_bits(game_info.start_raw.placement_grid)
        heights = terrain_bytes(game_info.start_raw.terrain_height)
        resources = [
            Resource(unit.pos.x, unit.pos.y, unit.vespene_contents > 0, unit.unit_type)
            for unit in observation.observation.raw_data.units
            if unit.mineral_contents > 0 or unit.vespene_contents > 0
        ]
        runtime_starts: dict[int, tuple[float, float]] = {}
        for unit in observation.observation.raw_data.units:
            if unit.owner in runtime_starts or unit.unit_type not in TOWN_HALL_TYPES:
                continue
            if 1 <= unit.owner <= 14 and unit.build_progress >= 1.0:
                runtime_starts[unit.owner] = (round(unit.pos.x, 1), round(unit.pos.y, 1))
        runtime_to_logical: dict[int, int] = {}
        unused_logical = set(EXPECTED_STARTS)
        for runtime, actual in sorted(runtime_starts.items()):
            logical = min(
                unused_logical,
                key=lambda slot: distance(actual, EXPECTED_STARTS[slot]),
            )
            runtime_to_logical[runtime] = logical
            unused_logical.remove(logical)
        starts = {
            logical: runtime_starts[runtime]
            for runtime, logical in runtime_to_logical.items()
        }
        path_starts: dict[int, tuple[float, float]] = {}
        worker_types = {45, 84, 104}
        for runtime, logical in runtime_to_logical.items():
            town_hall = runtime_starts[runtime]
            workers = [
                unit
                for unit in observation.observation.raw_data.units
                if unit.owner == runtime and unit.unit_type in worker_types
            ]
            if workers:
                worker = min(
                    workers,
                    key=lambda unit: distance((unit.pos.x, unit.pos.y), town_hall),
                )
                path_starts[logical] = (worker.pos.x, worker.pos.y)
            else:
                path_starts[logical] = town_hall
        groups = cluster_resources(resources, heights)
        candidates = [
            candidate
            for group in groups
            if (candidate := solve_candidate(group, grid, heights, resources)) is not None
        ]
        candidates = merge_duplicate_candidates(candidates, grid, heights, resources)
        candidates.sort(key=lambda candidate: (candidate.y, candidate.x))
        assign_covered_starts(candidates, starts)
        for candidate in candidates:
            if candidate.covered_by:
                # A preplaced town hall is ground truth for its own resource line.
                # Do not visualize a second geometry estimate beside it.
                owner = min(
                    candidate.covered_by,
                    key=lambda player: distance((candidate.x, candidate.y), starts[player]),
                )
                candidate.x, candidate.y = starts[owner]
                candidate.options = [(0.0, candidate.x, candidate.y)]
        await engine_queries(connection, candidates, path_starts)
        payload = {
            "map": str(BASE_MAP.relative_to(PROJECT_ROOT)),
            "resource_spread_threshold": RESOURCE_SPREAD_THRESHOLD,
            "expansion_gap_threshold": EXPANSION_GAP_THRESHOLD,
            "starts": {str(player): list(point) for player, point in starts.items()},
            "candidates": [
                {
                    "id": index,
                    "position": [candidate.x, candidate.y],
                    "geometry_position": [
                        candidate.options[0][1], candidate.options[0][2]
                    ] if candidate.options else [candidate.x, candidate.y],
                    "minerals": candidate.minerals,
                    "gases": candidate.gases,
                    "geometry_score": round(candidate.geometry_score, 2),
                    "placement_result": candidate.placement_result,
                    "race_positions": {
                        race: list(position)
                        for race, position in (candidate.race_positions or {}).items()
                    },
                    "race_results": candidate.race_results or {},
                    "covered_by_starts": candidate.covered_by,
                    "pathing": {str(player): value for player, value in (candidate.pathing or {}).items()},
                    "resources": [
                        [resource.x, resource.y, "gas" if resource.gas else "mineral"]
                        for resource in candidate.resources
                    ],
                }
                for index, candidate in enumerate(candidates, 1)
            ],
        }
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        JSON_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        build_payload = {
            "version": 1,
            "map": payload["map"],
            "expansion_gap_threshold": EXPANSION_GAP_THRESHOLD,
            "candidates": [
                {
                    "id": candidate["id"],
                    "race_positions": candidate["race_positions"],
                    "covered_by_starts": candidate["covered_by_starts"],
                    "pathing": candidate["pathing"],
                }
                for candidate in payload["candidates"]
            ],
        }
        BUILD_JSON_PATH.write_text(
            json.dumps(build_payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        draw_report(grid, resources, candidates, starts)
        print(f"EXPANSION_LAYOUT candidates={len(candidates)} resources={len(resources)}")
        print(f"EXPANSION_LAYOUT_JSON={JSON_PATH}")
        print(f"EXPANSION_LAYOUT_PNG={PNG_PATH}")
        print(f"EXPANSION_LAYOUT_BUILD_JSON={BUILD_JSON_PATH}")
    finally:
        if connection is not None:
            try:
                await connection.quit()
            except Exception:
                pass
            await connection.close()
        stop_process(process)


if __name__ == "__main__":
    asyncio.run(main())
