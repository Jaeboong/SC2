from __future__ import annotations

import unittest
from pathlib import Path

from app.play_custom_ai_v3 import _default_state, _resize_config, map_blocker
from sc2team.custom_config import SlotConfig
from sc2team.map_profile import MapProfile


def profile(players: int) -> MapProfile:
    return MapProfile(
        name="test",
        path=Path("test.SC2Map"),
        readable=True,
        reason="",
        map_info_slots=players,
        max_players=players,
        geometry=None,
        start_locations=(),
        player_starts=(),
        wild_zerg_town_halls=0,
        has_minimap=False,
        prepared=True,
        preparable=True,
    )


class V3LauncherSizingTests(unittest.TestCase):
    def test_prepared_two_player_map_is_not_blocked(self) -> None:
        self.assertEqual(map_blocker(profile(2)), "")
        self.assertIn("최소 2명", map_blocker(profile(1)))

    def test_default_state_keeps_fourteen_defaults_and_scales_down(self) -> None:
        fourteen, fourteen_builds = _default_state()
        self.assertEqual(tuple(slot.team for slot in fourteen.slots), (1,) * 7 + (2,) * 7)
        self.assertEqual(set(fourteen_builds), {2, 3, 4, 8, 9, 10, 11})
        two, two_builds = _default_state(2)
        self.assertEqual(len(two.slots), 2)
        self.assertEqual(tuple(slot.team for slot in two.slots), (1, 2))
        self.assertEqual(set(two_builds), {2})
        two.validate()

    def test_resize_preserves_front_slots_and_restores_human(self) -> None:
        original, builds = _default_state()
        shrunk, shrunk_builds = _resize_config(original, builds, 4, 2)
        self.assertEqual([slot.controller for slot in shrunk.slots], ["human", "custom_ai", "custom_ai", "custom_ai"])
        self.assertEqual(set(shrunk_builds), {2, 3, 4})
        no_human = original.__class__(
            **{**original.__dict__, "slots": tuple(
                SlotConfig(**{**slot.__dict__, "controller": "empty"})
                if slot.controller == "human" else slot
                for slot in original.slots
            )}
        )
        restored, _ = _resize_config(no_human, builds, 2, 2)
        self.assertEqual(restored.slots[0].controller, "human")
        self.assertEqual(restored.slots[1].controller, "custom_ai")


if __name__ == "__main__":
    unittest.main()
