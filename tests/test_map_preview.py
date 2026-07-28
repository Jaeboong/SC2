from __future__ import annotations

import unittest
from pathlib import Path

from sc2team.map_preview import (
    MinimapPlacement,
    minimap_placement,
    preview_file_name,
    preview_path,
    slot_positions,
    world_to_texture,
)
from sc2team.map_profile import (
    MapGeometry,
    MapProfile,
    PlayableBounds,
    PlayerStart,
    StartLocation,
)
from sc2team.team_layout import SlotPosition


# 실측값이다. 맵 22개에서 "콘텐츠 = 플레이 영역 x 정수배, 텍스처 안에 중앙
# 정렬"이 예외 없이 성립함을 확인했고, 아래 세 맵이 그 세 가지 형태다.
EUROPE_BOUNDS = PlayableBounds(left=0, bottom=0, right=256, top=256)
EUROPE_TEXTURE = (1024, 1024)

# 세로로 패딩이 붙는 형태. 플레이 영역 128x144, 텍스처 128x256.
TORCHES_BOUNDS = PlayableBounds(left=14, bottom=32, right=142, top=176)
TORCHES_TEXTURE = (128, 256)

# 배율이 1 로 내려앉는 형태. 64/48 은 1.33 이므로 정수배는 1 이다.
FLAT48_BOUNDS = PlayableBounds(left=12, bottom=16, right=60, top=64)
FLAT48_TEXTURE = (64, 64)


class PlacementTests(unittest.TestCase):
    def test_scale_four_fills_the_whole_texture(self) -> None:
        placement = minimap_placement(EUROPE_TEXTURE, EUROPE_BOUNDS)
        self.assertEqual(
            placement, MinimapPlacement(scale=4, left=0, top=0, width=1024, height=1024)
        )

    def test_vertical_padding_is_centred(self) -> None:
        placement = minimap_placement(TORCHES_TEXTURE, TORCHES_BOUNDS)
        self.assertEqual(
            placement, MinimapPlacement(scale=1, left=0, top=56, width=128, height=144)
        )

    def test_scale_floors_to_an_integer(self) -> None:
        placement = minimap_placement(FLAT48_TEXTURE, FLAT48_BOUNDS)
        self.assertEqual(
            placement, MinimapPlacement(scale=1, left=8, top=8, width=48, height=48)
        )

    def test_texture_smaller_than_the_playable_area_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            minimap_placement((32, 32), EUROPE_BOUNDS)

    def test_empty_playable_area_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            minimap_placement((64, 64), PlayableBounds(left=8, bottom=8, right=8, top=40))


class WorldToTextureTests(unittest.TestCase):
    """SC2 는 +y 가 북쪽이고 이미지는 위쪽이 행 0 이다. y 는 뒤집힌다."""

    def test_north_west_corner_maps_to_the_top_left(self) -> None:
        placement = minimap_placement(EUROPE_TEXTURE, EUROPE_BOUNDS)
        self.assertEqual(world_to_texture(placement, EUROPE_BOUNDS, 0.0, 256.0), (0.0, 0.0))

    def test_south_east_corner_maps_to_the_bottom_right(self) -> None:
        placement = minimap_placement(EUROPE_TEXTURE, EUROPE_BOUNDS)
        self.assertEqual(
            world_to_texture(placement, EUROPE_BOUNDS, 256.0, 0.0), (1024.0, 1024.0)
        )

    def test_base_map_start_location(self) -> None:
        # P1 = (28.5, 11.5): 남서쪽 끝. 배율 4 이므로 x 114, y 는 아래쪽이다.
        placement = minimap_placement(EUROPE_TEXTURE, EUROPE_BOUNDS)
        self.assertEqual(
            world_to_texture(placement, EUROPE_BOUNDS, 28.5, 11.5), (114.0, 978.0)
        )

    def test_padded_texture_offsets_are_applied(self) -> None:
        placement = minimap_placement(TORCHES_TEXTURE, TORCHES_BOUNDS)
        # 플레이 영역 북서 모서리는 세로 패딩 56 만큼 내려간다.
        self.assertEqual(world_to_texture(placement, TORCHES_BOUNDS, 14.0, 176.0), (0.0, 56.0))
        self.assertEqual(
            world_to_texture(placement, TORCHES_BOUNDS, 142.0, 32.0), (128.0, 200.0)
        )


def make_profile(**overrides: object) -> MapProfile:
    defaults: dict[str, object] = {
        "name": "test",
        "path": Path("test.SC2Map"),
        "readable": True,
        "reason": "",
        "map_info_slots": 6,
        "max_players": 4,
        "geometry": MapGeometry(width=128, height=128, bounds=EUROPE_BOUNDS),
        "start_locations": (),
        "player_starts": (),
        "wild_zerg_town_halls": 0,
        "has_minimap": True,
        "prepared": False,
        "preparable": True,
    }
    defaults.update(overrides)
    return MapProfile(**defaults)  # type: ignore[arg-type]


class SlotPositionTests(unittest.TestCase):
    def test_pinned_start_points_are_used_as_is(self) -> None:
        profile = make_profile(
            player_starts=(
                PlayerStart(slot=2, start_point=20, x=5.0, y=6.0),
                PlayerStart(slot=1, start_point=10, x=1.0, y=2.0),
            )
        )
        slots, provisional = slot_positions(profile)
        self.assertFalse(provisional)
        self.assertEqual(
            slots,
            (
                SlotPosition(slot=1, x=1.0, y=2.0),
                SlotPosition(slot=2, x=5.0, y=6.0),
            ),
        )

    def test_unprepared_map_falls_back_to_start_locations(self) -> None:
        """준비 전 맵은 MapInfo 의 startPoint 가 전부 0 이다(실측)."""

        profile = make_profile(
            max_players=2,
            start_locations=(
                StartLocation(id=7, x=90.0, y=10.0),
                StartLocation(id=3, x=10.0, y=80.0),
            ),
        )
        slots, provisional = slot_positions(profile)
        self.assertTrue(provisional)
        # 서쪽부터 번호를 붙인다.
        self.assertEqual(
            slots,
            (
                SlotPosition(slot=1, x=10.0, y=80.0),
                SlotPosition(slot=2, x=90.0, y=10.0),
            ),
        )

    def test_fallback_never_exceeds_the_player_capacity(self) -> None:
        profile = make_profile(
            max_players=2,
            start_locations=tuple(
                StartLocation(id=index, x=float(index) * 10.0, y=0.0)
                for index in range(1, 6)
            ),
        )
        slots, _ = slot_positions(profile)
        self.assertEqual([position.slot for position in slots], [1, 2])

    def test_map_without_start_locations_yields_nothing(self) -> None:
        slots, provisional = slot_positions(make_profile())
        self.assertEqual(slots, ())
        self.assertTrue(provisional)


class PreviewNameTests(unittest.TestCase):
    def test_terrain_only_name(self) -> None:
        self.assertEqual(preview_file_name("torches-le", None), "torches-le.png")

    def test_team_mode_suffix(self) -> None:
        self.assertEqual(preview_file_name("torches-le", 3), "torches-le-3team.png")

    def test_path_joins_the_image_directory(self) -> None:
        self.assertEqual(
            preview_path(Path("map/img"), "torches-le", 4),
            Path("map/img/torches-le-4team.png"),
        )

    def test_unsupported_team_mode_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            preview_file_name("torches-le", 5)


if __name__ == "__main__":
    unittest.main()
