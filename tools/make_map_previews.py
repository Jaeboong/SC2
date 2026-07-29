"""map/source/ 의 맵마다 map/img/ 에 미니맵 프리뷰 PNG 를 만든다.

    .venv\\Scripts\\python.exe tools\\make_map_previews.py [--force] [맵 이름 ...]

맵 하나당 `map/img/<이름>/` 디렉터리에 파일이 여러 개 나온다. 지형만 그린
`terrain.png` 와, 팀 모드별로 시작 지점에 P1..PN 라벨을 팀 색상으로 찍은
`2team.png` 등이다. 런처는 현재 선택된 팀 모드에 맞는 파일을 그대로 띄운다.

MPQ 를 여는 건 node(`tools/extract_minimap.cjs`, `tools/map_capabilities.cjs`)
고 이미지 합성은 여기서 한다. Pillow 는 이 도구만 쓴다 — 런처는 tk 가 PNG 를
직접 읽으므로 의존이 없다.
"""

from __future__ import annotations

import argparse
import os
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from sc2team.custom_config import TEAM_REGION_LABELS  # noqa: E402
from sc2team.map_preview import (  # noqa: E402
    NEUTRAL_MARKER_COLOR,
    PREVIEW_CONTENT_SIZE,
    TEAM_MARKER_COLORS,
    MinimapPlacement,
    minimap_placement,
    preview_path,
    slot_positions,
    world_to_texture,
)
from sc2team.map_profile import MapProfile, read_map_profiles  # noqa: E402
from sc2team.team_layout import SlotPosition, resolve_team_layout  # noqa: E402


SOURCE_DIR = PROJECT_ROOT / "map" / "source"
IMAGE_DIR = PROJECT_ROOT / "map" / "img"
EXTRACT_TOOL = PROJECT_ROOT / "tools" / "extract_minimap.cjs"

# 콘텐츠가 들어갈 정사각 상자. 런처와 공유하는 값이다. 세로로 긴 맵은 이
# 폭보다 높은 이미지가 되므로 임의로 키우면 패널에서 잘린다.
TARGET_BOX = PREVIEW_CONTENT_SIZE
# 이름 / 수용 능력 / 팀 범례 세 줄. 맵 이름이 길어 한 줄에 묶으면 겹친다.
FOOTER_HEIGHT = 64
MIN_CANVAS_WIDTH = PREVIEW_CONTENT_SIZE
MARKER_RADIUS = 12

BACKGROUND = "#0b1220"
FOOTER_BACKGROUND = "#111a28"
TITLE_COLOR = "#e6eefb"
DETAIL_COLOR = "#93a7c1"
MARKER_OUTLINE = "#0b1220"
MARKER_TEXT = "#0b1220"

FONT_CANDIDATES = (
    Path("C:/Windows/Fonts/malgun.ttf"),
    Path("C:/Windows/Fonts/malgunsl.ttf"),
    Path("C:/Windows/Fonts/arial.ttf"),
)


def load_font(size: int) -> ImageFont.ImageFont:
    for candidate in FONT_CANDIDATES:
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), size)
    # 한글 폰트가 없는 환경에서도 그림 자체는 나와야 한다.
    return ImageFont.load_default()


def read_tga(data: bytes) -> Image.Image:
    """비압축 트루컬러 TGA 만 읽는다. SC2 에디터가 그 형식으로만 저장한다."""

    id_length, colour_map_type, image_type = data[0], data[1], data[2]
    width, height = struct.unpack_from("<HH", data, 12)
    bits, descriptor = data[16], data[17]
    if image_type != 2 or colour_map_type != 0:
        raise ValueError(f"지원하지 않는 TGA 형식입니다: type={image_type}")
    if bits not in (24, 32):
        raise ValueError(f"지원하지 않는 TGA 색 깊이입니다: {bits}bpp")
    offset = 18 + id_length
    stride = bits // 8
    expected = width * height * stride
    if len(data) < offset + expected:
        raise ValueError("TGA 픽셀 데이터가 잘렸습니다.")
    image = Image.frombuffer(
        "RGB" if bits == 24 else "RGBA",
        (width, height),
        data[offset : offset + expected],
        "raw",
        "BGR" if bits == 24 else "BGRA",
        0,
        1,
    )
    # 기술자 비트 5 가 서면 원점이 좌상단이다. 서지 않으면 아래에서 위로 저장된다.
    if not descriptor & 0x20:
        image = image.transpose(Image.FLIP_TOP_BOTTOM)
    return image.convert("RGB")


def extract_minimap(map_path: Path, output: Path) -> bool:
    environment = dict(os.environ)
    shared = str(PROJECT_ROOT / "tools" / "node_modules")
    existing = environment.get("NODE_PATH")
    environment["NODE_PATH"] = f"{shared}{os.pathsep}{existing}" if existing else shared
    completed = subprocess.run(
        ["node", str(EXTRACT_TOOL), str(map_path), str(output)],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
    )
    if completed.returncode:
        detail = (completed.stderr or completed.stdout).strip()
        print(f"  미니맵을 꺼내지 못했습니다: {detail}")
        return False
    return True


def marker_positions(
    profile: MapProfile,
    slots: tuple[SlotPosition, ...],
    placement: MinimapPlacement,
    ratio: float,
) -> dict[int, tuple[float, float]]:
    """슬롯 -> 최종 이미지 픽셀 좌표."""

    assert profile.geometry is not None
    bounds = profile.geometry.bounds
    positions: dict[int, tuple[float, float]] = {}
    for start in slots:
        texture_x, texture_y = world_to_texture(placement, bounds, start.x, start.y)
        positions[start.slot] = (
            (texture_x - placement.left) * ratio,
            (texture_y - placement.top) * ratio,
        )
    return positions


def draw_markers(
    draw: ImageDraw.ImageDraw,
    positions: dict[int, tuple[float, float]],
    layout: dict[int, int] | None,
    font: ImageFont.ImageFont,
) -> None:
    for slot, (x, y) in sorted(positions.items()):
        colour = (
            NEUTRAL_MARKER_COLOR
            if layout is None
            else TEAM_MARKER_COLORS[layout[slot]]
        )
        draw.ellipse(
            (
                x - MARKER_RADIUS,
                y - MARKER_RADIUS,
                x + MARKER_RADIUS,
                y + MARKER_RADIUS,
            ),
            fill=colour,
            outline=MARKER_OUTLINE,
            width=2,
        )
        draw.text((x, y), f"P{slot}", font=font, fill=MARKER_TEXT, anchor="mm")


def fit_text(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, limit: int
) -> str:
    """`limit` 픽셀에 들어가도록 뒤를 줄인다."""

    if draw.textlength(text, font=font) <= limit:
        return text
    for length in range(len(text) - 1, 0, -1):
        clipped = f"{text[:length]}…"
        if draw.textlength(clipped, font=font) <= limit:
            return clipped
    return "…"


def draw_footer(
    draw: ImageDraw.ImageDraw,
    canvas_width: int,
    footer_top: int,
    profile: MapProfile,
    team_mode: int | None,
    provisional: bool,
) -> None:
    title_font = load_font(13)
    detail_font = load_font(11)
    draw.rectangle(
        (0, footer_top, canvas_width, footer_top + FOOTER_HEIGHT),
        fill=FOOTER_BACKGROUND,
    )
    draw.text(
        (10, footer_top + 9),
        fit_text(draw, profile.name, title_font, canvas_width - 20),
        font=title_font,
        fill=TITLE_COLOR,
    )

    summary = f"최대 {profile.max_players}명 · {profile.max_teams}팀"
    summary += (
        f" · 야생저그 캠프 {profile.wild_zerg_town_halls}"
        if profile.wild_zerg_town_halls
        else " · 야생저그 캠프 없음"
    )
    summary += f" · 시작 지점 {len(profile.start_locations)}"
    draw.text((10, footer_top + 29), summary, font=detail_font, fill=DETAIL_COLOR)

    legend_y = footer_top + 51
    x = 10
    if team_mode is None:
        note = "지형만 · 시작 지점에 슬롯 번호"
        if provisional:
            note = "지형만 · 슬롯 번호는 잠정 (맵 준비 전)"
        draw.text((x, legend_y), note, font=detail_font, fill=DETAIL_COLOR, anchor="lm")
        return
    if provisional:
        # 좌표에서 나온 팀 색은 맞지만 슬롯 번호는 빌더가 준비할 때 확정된다.
        draw.text(
            (canvas_width - 10, footer_top + 29),
            "슬롯 번호 잠정",
            font=detail_font,
            fill="#ffcf8a",
            anchor="ra",
        )
    for team in range(1, team_mode + 1):
        draw.ellipse(
            (x, legend_y - 5, x + 10, legend_y + 5),
            fill=TEAM_MARKER_COLORS[team],
            outline=MARKER_OUTLINE,
        )
        label = f"{team}팀 {TEAM_REGION_LABELS[team_mode][team]}"
        draw.text((x + 15, legend_y), label, font=detail_font, fill=DETAIL_COLOR, anchor="lm")
        x += 15 + int(draw.textlength(label, font=detail_font)) + 14


def render(
    profile: MapProfile,
    content: Image.Image,
    placement: MinimapPlacement,
    team_mode: int | None,
    slots: tuple[SlotPosition, ...],
    provisional: bool,
) -> Image.Image:
    ratio = TARGET_BOX / max(content.width, content.height)
    render_width = max(1, round(content.width * ratio))
    render_height = max(1, round(content.height * ratio))
    resample = Image.LANCZOS if ratio < 1.0 else Image.BICUBIC
    scaled = content.resize((render_width, render_height), resample)

    canvas_width = max(render_width, MIN_CANVAS_WIDTH)
    canvas = Image.new(
        "RGB", (canvas_width, render_height + FOOTER_HEIGHT), BACKGROUND
    )
    offset_x = (canvas_width - render_width) // 2
    canvas.paste(scaled, (offset_x, 0))

    draw = ImageDraw.Draw(canvas)
    positions = {
        slot: (x + offset_x, y)
        for slot, (x, y) in marker_positions(profile, slots, placement, ratio).items()
    }
    layout = None if team_mode is None else resolve_team_layout(slots, team_mode)
    draw_markers(draw, positions, layout, load_font(11))
    draw_footer(draw, canvas_width, render_height, profile, team_mode, provisional)
    return canvas


def build_previews(profile: MapProfile, image_dir: Path, force: bool) -> int:
    if not profile.readable:
        print(f"{profile.name}: 건너뜀 — {profile.reason}")
        return 0
    if profile.geometry is None:
        print(f"{profile.name}: 건너뜀 — 플레이 영역을 읽지 못했습니다.")
        return 0
    if not profile.has_minimap:
        print(f"{profile.name}: 건너뜀 — 맵에 Minimap.tga 가 없습니다.")
        return 0

    map_path = PROJECT_ROOT / profile.path
    with tempfile.TemporaryDirectory(prefix="sc2team-minimap-") as scratch:
        target = Path(scratch) / "Minimap.tga"
        if not extract_minimap(map_path, target):
            return 0
        texture = read_tga(target.read_bytes())

    placement = minimap_placement(texture.size, profile.geometry.bounds)
    content = texture.crop(placement.box)
    slots, provisional = slot_positions(profile)
    if not slots:
        print(f"{profile.name}: 건너뜀 — 시작 지점을 찾지 못했습니다.")
        return 0
    if provisional:
        print("  슬롯 번호는 잠정이다 — 이 맵은 아직 준비되지 않았다(startPoint 미지정).")

    (image_dir / profile.name).mkdir(parents=True, exist_ok=True)
    written = 0
    modes: list[int | None] = [None, *range(2, profile.max_teams + 1)]
    for team_mode in modes:
        destination = preview_path(image_dir, profile.name, team_mode)
        if destination.exists() and not force:
            print(f"  이미 있음: {destination.name} (--force 로 다시 만든다)")
            continue
        render(profile, content, placement, team_mode, slots, provisional).save(
            destination
        )
        print(f"  기록: {destination.name}")
        written += 1
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description="맵 미니맵 프리뷰를 만든다.")
    parser.add_argument("names", nargs="*", help="맵 이름(확장자 없이). 비우면 전부.")
    parser.add_argument("--force", action="store_true", help="이미 있는 PNG 도 다시 만든다.")
    parser.add_argument("--source-dir", type=Path, default=SOURCE_DIR)
    parser.add_argument("--image-dir", type=Path, default=IMAGE_DIR)
    arguments = parser.parse_args()

    source_dir: Path = arguments.source_dir
    if not source_dir.is_dir():
        print(f"맵 디렉터리가 없습니다: {source_dir}")
        return 2
    if arguments.names:
        targets = [source_dir / f"{name}.SC2Map" for name in arguments.names]
        missing = [target for target in targets if not target.exists()]
        if missing:
            print("없는 맵: " + ", ".join(path.name for path in missing))
            return 2
    else:
        targets = sorted(source_dir.glob("*.SC2Map"))
    if not targets:
        print(f"{source_dir} 에 맵이 없습니다.")
        return 0

    profiles = read_map_profiles(PROJECT_ROOT, *targets)
    written = 0
    for profile in profiles:
        print(profile.name)
        written += build_previews(profile, arguments.image_dir, arguments.force)
    print(f"PREVIEWS_WRITTEN={written} maps={len(profiles)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
