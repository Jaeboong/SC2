"""미니맵 텍스처와 게임 좌표 사이의 변환, 그리고 프리뷰 파일 이름 규칙.

이미지를 그리는 코드는 `tools/make_map_previews.py` 에 있다. 여기에는 좌표
계산과 경로 규칙만 둔다 — 런처(프리뷰를 **읽는** 쪽)와 생성기(**쓰는** 쪽)가
같은 규칙을 봐야 하고, 런처에 Pillow 의존을 만들지 않기 위해서다.

**좌표 변환 규칙은 맵 22개 실측으로 확정했다.** 미니맵 텍스처는 2의 거듭제곱
크기이고, 그 안에 플레이 영역(카메라 경계)이 정수 배율로 확대돼 **중앙 정렬**
로 들어간다. 배율은 가로·세로 중 더 빡빡한 쪽으로 내림한다. 22개 맵 전부에서
이 규칙으로 계산한 사각형이 실제 이미지의 비검정 경계와 정확히 일치했다
(유럽 256x256 -> 1024x1024 배율 4, Torches 128x144 -> 128x256 배율 1 에
세로 패딩 56, Flat48 48x48 -> 64x64 배율 1 에 사방 패딩 8).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sc2team.map_profile import MapProfile, PlayableBounds
from sc2team.team_layout import SUPPORTED_TEAM_MODES, SlotPosition


# 팀 마커 색. 어두운 미니맵 위에서 서로 구분돼야 하므로 런처 섹션 색보다
# 밝게 잡았다. 번호 체계는 TEAM_REGION_LABELS 와 같다.
TEAM_MARKER_COLORS: dict[int, str] = {
    1: "#4da3ff",
    2: "#ff6a5c",
    3: "#5ddc92",
    4: "#c98cff",
}

# 팀 배치를 아직 모를 때(지형만 그린 프리뷰) 쓰는 색.
NEUTRAL_MARKER_COLOR = "#d8e4f2"

# 생성기와 Tk 런처가 함께 쓰는 프리뷰 콘텐츠 폭. PNG는 여기에 생성기 푸터를
# 더한 높이를 가지며, 런처 패널은 좌우 여백까지 더해 이 폭을 보장한다.
PREVIEW_CONTENT_SIZE = 360


@dataclass(frozen=True)
class MinimapPlacement:
    """텍스처 안에서 플레이 영역이 차지하는 사각형(픽셀)."""

    scale: int
    left: int
    top: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height

    @property
    def box(self) -> tuple[int, int, int, int]:
        """PIL 의 crop 상자."""

        return (self.left, self.top, self.right, self.bottom)


def minimap_placement(
    texture_size: tuple[int, int], bounds: PlayableBounds
) -> MinimapPlacement:
    """미니맵 텍스처 안에서 플레이 영역이 어디에 놓였는지 계산한다."""

    texture_width, texture_height = texture_size
    if bounds.width <= 0 or bounds.height <= 0:
        raise ValueError(
            f"플레이 영역이 비어 있습니다: {bounds.width}x{bounds.height}"
        )
    scale = min(texture_width // bounds.width, texture_height // bounds.height)
    if scale < 1:
        raise ValueError(
            f"미니맵 텍스처({texture_width}x{texture_height})가 플레이 영역"
            f"({bounds.width}x{bounds.height})보다 작습니다."
        )
    content_width = bounds.width * scale
    content_height = bounds.height * scale
    return MinimapPlacement(
        scale=scale,
        left=(texture_width - content_width) // 2,
        top=(texture_height - content_height) // 2,
        width=content_width,
        height=content_height,
    )


def world_to_texture(
    placement: MinimapPlacement, bounds: PlayableBounds, x: float, y: float
) -> tuple[float, float]:
    """게임 좌표 -> 미니맵 텍스처 픽셀.

    SC2 는 +y 가 북쪽이고 이미지는 위쪽이 행 0 이므로 y 를 뒤집는다.
    """

    return (
        placement.left + (x - bounds.left) * placement.scale,
        placement.top + (bounds.top - y) * placement.scale,
    )


def slot_positions(profile: MapProfile) -> tuple[tuple[SlotPosition, ...], bool]:
    """슬롯 -> 좌표. 두 번째 값이 참이면 **잠정** 배정이다.

    준비된 맵은 MapInfo 가 슬롯마다 시작 지점을 못박아 두므로 그대로 쓴다.
    준비 전 맵은 모든 슬롯의 ``startPoint`` 가 0 이다 — 엔진이 경기 시작 때
    배정하고 우리 빌더가 준비 단계에서 확정한다. 그 전에는 좌표만 알 수 있어
    서->동, 남->북 순으로 잠정 번호를 붙인다. 방위 분할은 번호가 아니라 좌표로
    결정되므로 팀 색상 자체는 잠정 여부와 무관하게 맞다.
    """

    if profile.player_starts:
        ordered = sorted(profile.player_starts, key=lambda start: start.slot)
        return (
            tuple(
                SlotPosition(slot=start.slot, x=start.x, y=start.y)
                for start in ordered
            ),
            False,
        )
    candidates = sorted(
        profile.start_locations, key=lambda point: (point.x, point.y, point.id)
    )[: profile.max_players]
    return (
        tuple(
            SlotPosition(slot=index + 1, x=point.x, y=point.y)
            for index, point in enumerate(candidates)
        ),
        True,
    )


def preview_file_name(team_mode: int | None) -> str:
    """`team_mode` 가 None 이면 마커 없는 지형 프리뷰."""

    if team_mode is None:
        return "terrain.png"
    if team_mode not in SUPPORTED_TEAM_MODES:
        raise ValueError(f"지원하지 않는 팀 모드입니다: {team_mode}")
    return f"{team_mode}team.png"


def preview_path(image_dir: Path, map_name: str, team_mode: int | None) -> Path:
    return image_dir / map_name / preview_file_name(team_mode)


__all__ = [
    "NEUTRAL_MARKER_COLOR",
    "PREVIEW_CONTENT_SIZE",
    "TEAM_MARKER_COLORS",
    "MinimapPlacement",
    "minimap_placement",
    "preview_file_name",
    "preview_path",
    "slot_positions",
    "world_to_texture",
]
