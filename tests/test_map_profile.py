from __future__ import annotations

import unittest
from pathlib import Path

from sc2team.map_profile import (
    MapGeometry,
    MapProfile,
    PlayableBounds,
    PlayerStart,
    StartLocation,
    max_teams_for,
    read_map_profiles,
)
from app.play_custom_ai_v3 import wild_zerg_availability


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASE_MAP = (
    PROJECT_ROOT
    / "map"
    / "source"
    / "europe-melee-2-7v7-rich-50000-fixed-teams.SC2Map"
)


def make_profile(**overrides: object) -> MapProfile:
    defaults: dict[str, object] = {
        "name": "test",
        "path": Path("test.SC2Map"),
        "readable": True,
        "reason": "",
        "map_info_slots": 16,
        "max_players": 14,
        "geometry": MapGeometry(
            width=256,
            height=256,
            bounds=PlayableBounds(left=0, bottom=0, right=256, top=256),
        ),
        "start_locations": tuple(
            StartLocation(id=index, x=float(index), y=0.0) for index in range(1, 21)
        ),
        "player_starts": tuple(
            PlayerStart(slot=index, start_point=index, x=float(index), y=0.0)
            for index in range(1, 15)
        ),
        "wild_zerg_town_halls": 14,
        "has_minimap": True,
        "prepared": True,
        "preparable": False,
    }
    defaults.update(overrides)
    return MapProfile(**defaults)  # type: ignore[arg-type]


class MaxTeamsTests(unittest.TestCase):
    def test_two_players_allow_only_two_teams(self) -> None:
        self.assertEqual(max_teams_for(2), 2)

    def test_three_players_allow_three_teams(self) -> None:
        self.assertEqual(max_teams_for(3), 3)

    def test_four_players_unlock_four_teams(self) -> None:
        self.assertEqual(max_teams_for(4), 4)

    def test_more_players_stay_capped_at_four_teams(self) -> None:
        self.assertEqual(max_teams_for(14), 4)

    def test_a_single_player_supports_no_team_mode(self) -> None:
        self.assertEqual(max_teams_for(1), 0)


class WildZergAvailabilityTests(unittest.TestCase):
    def test_map_without_camps_cannot_host_wild_zerg(self) -> None:
        profile = make_profile(wild_zerg_town_halls=0)
        available, reason = profile.wild_zerg_available(4)
        self.assertFalse(available)
        self.assertIn("저그 본진", reason)

    def test_wild_zerg_needs_a_spare_start_location(self) -> None:
        profile = make_profile(
            start_locations=tuple(
                StartLocation(id=index, x=float(index), y=0.0) for index in range(1, 5)
            )
        )
        available, reason = profile.wild_zerg_available(4)
        self.assertFalse(available)
        self.assertIn("여분 시작 지점", reason)

    def test_spare_start_location_and_camps_allow_wild_zerg(self) -> None:
        available, reason = make_profile().wild_zerg_available(14)
        self.assertTrue(available)
        self.assertEqual(reason, "")

    def test_unreadable_map_never_allows_wild_zerg(self) -> None:
        available, _ = make_profile(readable=False).wild_zerg_available(2)
        self.assertFalse(available)


class LauncherWildZergAvailabilityTests(unittest.TestCase):
    def test_map_without_p15_town_hall_is_unavailable(self) -> None:
        available, reason = wild_zerg_availability(
            make_profile(wild_zerg_town_halls=0), 14
        )
        self.assertFalse(available)
        self.assertIn("저그 본진", reason)

    def test_start_locations_must_exceed_active_players(self) -> None:
        starts = tuple(
            StartLocation(id=index, x=float(index), y=0.0) for index in range(1, 15)
        )
        profile = make_profile(start_locations=starts)
        self.assertFalse(wild_zerg_availability(profile, 14)[0])
        self.assertTrue(wild_zerg_availability(profile, 13)[0])

    def test_activating_final_slot_reverses_availability(self) -> None:
        starts = tuple(
            StartLocation(id=index, x=float(index), y=0.0) for index in range(1, 16)
        )
        profile = make_profile(start_locations=starts)
        self.assertTrue(wild_zerg_availability(profile, 14)[0])
        self.assertFalse(wild_zerg_availability(profile, 15)[0])


class UsabilityTests(unittest.TestCase):
    def test_unprepared_map_is_not_usable_yet(self) -> None:
        profile = make_profile(prepared=False, preparable=True)
        self.assertFalse(profile.usable)

    def test_prepared_map_is_usable(self) -> None:
        self.assertTrue(make_profile().usable)


class BaseMapProbeTests(unittest.TestCase):
    """실제 베이스 맵을 읽는다. node 도구까지 통과해야 의미가 있다."""

    def test_base_map_reports_expected_capacity(self) -> None:
        if not BASE_MAP.is_file():
            self.skipTest(f"베이스 맵이 없습니다: {BASE_MAP}")
        profiles = read_map_profiles(PROJECT_ROOT, BASE_MAP)
        self.assertEqual(len(profiles), 1)
        profile = profiles[0]
        self.assertTrue(profile.readable, profile.reason)
        self.assertEqual(profile.max_players, 14)
        self.assertEqual(profile.max_teams, 4)
        self.assertEqual(len(profile.start_locations), 20)
        self.assertGreater(profile.wild_zerg_town_halls, 0)
        self.assertTrue(profile.prepared)
        self.assertTrue(profile.usable)

    def test_base_map_allows_wild_zerg_for_a_full_lobby(self) -> None:
        if not BASE_MAP.is_file():
            self.skipTest(f"베이스 맵이 없습니다: {BASE_MAP}")
        profile = read_map_profiles(PROJECT_ROOT, BASE_MAP)[0]
        available, reason = profile.wild_zerg_available(14)
        self.assertTrue(available, reason)


if __name__ == "__main__":
    unittest.main()
