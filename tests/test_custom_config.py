from __future__ import annotations

import unittest
from dataclasses import replace

from sc2team.custom_config import (
    CustomLauncherConfig,
    GROUND_BUILDS,
    PROTOSS_FACTIONS,
    default_custom_config,
)


class CustomConfigTests(unittest.TestCase):
    def test_default_is_four_vs_four(self) -> None:
        config = default_custom_config()
        self.assertEqual(config.human.slot, 1)
        self.assertEqual(
            tuple(slot.slot for slot in config.active_slots),
            (1, 2, 3, 4, 8, 9, 10, 11),
        )
        self.assertEqual(len(config.custom_ai_slots), 7)

    def test_human_can_move_to_any_slot(self) -> None:
        config = default_custom_config()
        slots = tuple(
            replace(
                slot,
                controller=(
                    "human"
                    if slot.slot == 12
                    else "custom_ai"
                    if slot.slot == 1
                    else slot.controller
                ),
            )
            for slot in config.slots
        )
        moved = replace(config, slots=slots)
        moved.validate()
        self.assertEqual(moved.human.slot, 12)

    def test_only_one_human_is_allowed(self) -> None:
        config = default_custom_config()
        slots = tuple(
            replace(slot, controller="human") if slot.slot == 2 else slot
            for slot in config.slots
        )
        with self.assertRaisesRegex(ValueError, "정확히 한 명"):
            replace(config, slots=slots).validate()

    def test_builds_are_race_specific_and_ground_only(self) -> None:
        self.assertIn("thor_tank", GROUND_BUILDS["Terran"])
        self.assertIn("immortal_colossus", GROUND_BUILDS["Protoss"])
        self.assertIn("hydra_lurker", GROUND_BUILDS["Zerg"])
        joined = " ".join(
            key for builds in GROUND_BUILDS.values() for key in builds
        )
        self.assertNotIn("carrier", joined)
        self.assertNotIn("battlecruiser", joined)
        self.assertNotIn("mutalisk", joined)

    def test_saved_config_round_trip(self) -> None:
        original = default_custom_config()
        loaded = CustomLauncherConfig.from_dict(original.to_dict())
        self.assertEqual(loaded, original)

    def test_protoss_faction_is_global_and_validated(self) -> None:
        config = replace(default_custom_config(), protoss_faction="Taldarim")
        config.validate()
        self.assertEqual(config.protoss_faction, "Taldarim")
        self.assertEqual(len(PROTOSS_FACTIONS), 5)
        with self.assertRaisesRegex(ValueError, "프로토스 진영"):
            replace(config, protoss_faction="Unknown").validate()

    def test_wild_zerg_defaults_on_and_survives_a_round_trip(self) -> None:
        # §93: 야생 저그 토글. 기본값은 켜기(지금까지의 동작)이고, 이 키가 없는
        # 옛 프리셋도 켜진 상태로 읽혀야 한다.
        default = default_custom_config()
        self.assertTrue(default.wild_zerg)
        off = replace(default, wild_zerg=False)
        off.validate()
        self.assertFalse(CustomLauncherConfig.from_dict(off.to_dict()).wild_zerg)
        legacy = default.to_dict()
        del legacy["wild_zerg"]
        self.assertTrue(CustomLauncherConfig.from_dict(legacy).wild_zerg)

    def test_legacy_preset_defaults_to_standard_protoss(self) -> None:
        data = default_custom_config().to_dict()
        del data["protoss_faction"]
        self.assertEqual(
            CustomLauncherConfig.from_dict(data).protoss_faction,
            "Standard",
        )


if __name__ == "__main__":
    unittest.main()
