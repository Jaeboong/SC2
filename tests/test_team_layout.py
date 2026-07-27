from __future__ import annotations

import unittest

from sc2team.team_layout import (
    SlotPosition,
    derive_team_layout,
    team_sizes,
)


def square_positions() -> list[SlotPosition]:
    """네 모서리에 하나씩. 사분면 배정이 명확한 최소 사례."""

    return [
        SlotPosition(slot=1, x=0.0, y=100.0),    # 북서
        SlotPosition(slot=2, x=100.0, y=100.0),  # 북동
        SlotPosition(slot=3, x=0.0, y=0.0),      # 남서
        SlotPosition(slot=4, x=100.0, y=0.0),    # 남동
    ]


class TeamSizeTests(unittest.TestCase):
    def test_even_split(self) -> None:
        self.assertEqual(team_sizes(8, 4), [2, 2, 2, 2])

    def test_remainder_goes_to_the_first_teams(self) -> None:
        self.assertEqual(team_sizes(14, 4), [4, 4, 3, 3])

    def test_three_teams_of_fourteen(self) -> None:
        self.assertEqual(team_sizes(14, 3), [5, 5, 4])

    def test_too_few_players_for_the_mode(self) -> None:
        with self.assertRaises(ValueError):
            team_sizes(3, 4)


class CompassAssignmentTests(unittest.TestCase):
    def test_four_corners_map_to_four_quadrants(self) -> None:
        layout = derive_team_layout(square_positions(), 4)
        # 팀 번호는 TEAM_REGION_LABELS 와 같다: 1 북서, 2 북동, 3 남서, 4 남동.
        self.assertEqual(layout, {1: 1, 2: 2, 3: 3, 4: 4})

    def test_two_teams_split_west_and_east(self) -> None:
        layout = derive_team_layout(square_positions(), 2)
        self.assertEqual(layout[1], 1)
        self.assertEqual(layout[3], 1)
        self.assertEqual(layout[2], 2)
        self.assertEqual(layout[4], 2)

    def test_three_teams_use_north_pair_and_south(self) -> None:
        positions = [
            SlotPosition(slot=1, x=0.0, y=100.0),
            SlotPosition(slot=2, x=100.0, y=100.0),
            SlotPosition(slot=3, x=50.0, y=0.0),
        ]
        self.assertEqual(derive_team_layout(positions, 3), {1: 1, 2: 2, 3: 3})

    def test_teams_stay_balanced(self) -> None:
        positions = [
            SlotPosition(slot=index + 1, x=float(index % 4) * 50.0, y=float(index // 4) * 50.0)
            for index in range(12)
        ]
        layout = derive_team_layout(positions, 4)
        counts = [list(layout.values()).count(team) for team in (1, 2, 3, 4)]
        self.assertEqual(sorted(counts), [3, 3, 3, 3])

    def test_result_is_deterministic(self) -> None:
        positions = square_positions()
        first = derive_team_layout(positions, 4)
        second = derive_team_layout(list(reversed(positions)), 4)
        self.assertEqual(first, second)

    def test_more_teams_than_players_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            derive_team_layout(square_positions()[:3], 4)

    def test_unsupported_team_mode_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            derive_team_layout(square_positions(), 5)


class BaseMapRegressionTests(unittest.TestCase):
    """실제 베이스 맵 좌표에서 손으로 검증된 배치가 그대로 나와야 한다.

    2팀·4팀은 지금까지 사람이 쓰던 고정표와 정확히 같다. 유도 로직이 바뀌어
    이 배치가 흔들리면 실제 게임의 팀 구성이 바뀐다.
    """

    # maps/generated/europe-melee-2-7v7-rich-50000-fixed-teams.SC2Map 의
    # MapInfo 가 각 슬롯에 물려둔 시작 지점 좌표.
    POSITIONS = [
        SlotPosition(slot=1, x=28.5, y=11.5),
        SlotPosition(slot=2, x=32.5, y=64.5),
        SlotPosition(slot=3, x=11.5, y=119.5),
        SlotPosition(slot=4, x=22.5, y=176.5),
        SlotPosition(slot=5, x=61.5, y=181.5),
        SlotPosition(slot=6, x=47.5, y=221.5),
        SlotPosition(slot=7, x=8.5, y=245.5),
        SlotPosition(slot=8, x=199.5, y=14.5),
        SlotPosition(slot=9, x=246.5, y=32.5),
        SlotPosition(slot=10, x=186.5, y=60.5),
        SlotPosition(slot=11, x=176.5, y=127.5),
        SlotPosition(slot=12, x=231.5, y=159.5),
        SlotPosition(slot=13, x=158.5, y=205.5),
        SlotPosition(slot=14, x=136.5, y=17.5),
    ]

    def test_two_team_layout_matches_the_hand_table(self) -> None:
        layout = derive_team_layout(self.POSITIONS, 2)
        expected = (1, 1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 2, 2, 2)
        self.assertEqual(tuple(layout[slot] for slot in range(1, 15)), expected)

    def test_four_team_layout_matches_the_hand_table(self) -> None:
        layout = derive_team_layout(self.POSITIONS, 4)
        expected = (3, 3, 3, 1, 1, 1, 1, 4, 4, 4, 2, 2, 2, 4)
        self.assertEqual(tuple(layout[slot] for slot in range(1, 15)), expected)

    def test_three_team_layout_is_balanced_not_south_heavy(self) -> None:
        # 손으로 만든 3팀 표는 남부 7 / 북서 4 / 북동 3 인 비대칭 배치였다.
        # 임의 맵에 쓸 일반 규칙은 균등 분배이므로 여기서 갈라진다.
        layout = derive_team_layout(self.POSITIONS, 3)
        counts = sorted(list(layout.values()).count(team) for team in (1, 2, 3))
        self.assertEqual(counts, [4, 5, 5])


if __name__ == "__main__":
    unittest.main()
