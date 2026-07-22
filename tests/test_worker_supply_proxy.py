from __future__ import annotations

import unittest

from s2clientprotocol import sc2api_pb2 as sc_pb

from sc2team.worker_supply_proxy import restore_worker_supply


class RestoreWorkerSupplyTests(unittest.TestCase):
    def test_restores_worker_and_used_supply_for_own_workers(self) -> None:
        response = sc_pb.Response()
        observation = response.observation.observation
        observation.player_common.player_id = 2
        observation.player_common.food_cap = 15
        observation.player_common.food_used = 0
        observation.player_common.food_workers = 0

        for owner, unit_type in (
            (2, 84),
            (2, 84),
            (1, 84),
            (2, 59),
            (2, 1994),
        ):
            unit = observation.raw_data.units.add()
            unit.owner = owner
            unit.unit_type = unit_type
            unit.build_progress = 1.0

        count = restore_worker_supply(response)

        self.assertEqual(count, 2)
        self.assertEqual(observation.player_common.food_workers, 2)
        self.assertEqual(observation.player_common.food_used, 2)
        self.assertEqual(observation.player_common.food_cap, 17)
        self.assertIn(61, [unit.unit_type for unit in observation.raw_data.units])
        self.assertNotIn(1994, [unit.unit_type for unit in observation.raw_data.units])

    def test_leaves_non_observation_response_unchanged(self) -> None:
        response = sc_pb.Response()
        response.ping.game_version = "5.0.16"

        self.assertIsNone(restore_worker_supply(response))
        self.assertEqual(response.ping.game_version, "5.0.16")


if __name__ == "__main__":
    unittest.main()
