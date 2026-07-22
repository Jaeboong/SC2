from __future__ import annotations

import unittest

from s2clientprotocol import common_pb2 as common_pb
from s2clientprotocol import sc2api_pb2 as sc_pb

from sc2team.launcher_config import (
    AI_BUILDS,
    BUILD_LABELS,
    LauncherConfig,
    build_display,
    build_key,
    default_config,
)


class LauncherConfigTests(unittest.TestCase):
    def test_requested_defaults(self) -> None:
        config = default_config()
        self.assertEqual(
            tuple(player.slot for player in config.ai_players), tuple(range(2, 15))
        )
        self.assertTrue(all(player.build == "Macro" for player in config.ai_players))
        self.assertTrue(
            all(
                player.difficulty == "VeryHard"
                for player in config.ai_players
                if player.slot != 14
            )
        )
        self.assertEqual(config.ai_players[-1].difficulty, "CheatMoney")

    def test_protocol_values(self) -> None:
        players = default_config().computer_players()
        self.assertEqual(len(players), 13)
        self.assertTrue(all(player.race == common_pb.Random for player in players))
        self.assertTrue(all(player.ai_build == sc_pb.Macro for player in players))
        self.assertEqual(players[-1].difficulty, sc_pb.CheatMoney)
        self.assertTrue(
            all(player.difficulty == sc_pb.VeryHard for player in players[:-1])
        )

    def test_build_labels_round_trip_for_every_race(self) -> None:
        for race, labels in BUILD_LABELS.items():
            for build in labels:
                display = build_display(race, build)
                self.assertEqual(build_key(race, display), build)

    def test_air_build_is_excluded_from_stable_ui(self) -> None:
        self.assertNotIn("Air", AI_BUILDS)

    def test_saved_config_round_trip(self) -> None:
        original = default_config()
        loaded = LauncherConfig.from_dict(original.to_dict())
        self.assertEqual(loaded, original)


if __name__ == "__main__":
    unittest.main()
