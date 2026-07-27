from __future__ import annotations

import unittest
from dataclasses import replace

from sc2team.custom_config import (
    CustomLauncherConfig,
    GROUND_BUILDS,
    PROTOSS_FACTIONS,
    TEAM_LAYOUTS,
    default_custom_config,
    team_for_slot,
    team_label_for_slot,
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

    def test_fixed_team_modes_use_existing_p1_through_p14_locations(self) -> None:
        expected = {
            2: (1, 1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 2, 2, 2),
            3: (3, 3, 3, 1, 1, 1, 1, 3, 3, 3, 2, 2, 2, 3),
            4: (3, 3, 3, 1, 1, 1, 1, 4, 4, 4, 2, 2, 2, 4),
        }
        default = default_custom_config()
        for team_mode, layout in expected.items():
            with self.subTest(team_mode=team_mode):
                slots = tuple(
                    replace(slot, team=team_for_slot(slot.slot, team_mode))
                    for slot in default.slots
                )
                config = replace(default, slots=slots, wild_zerg=False)
                config.validate()
                self.assertEqual(config.team_mode, team_mode)
                self.assertEqual(tuple(slot.team for slot in slots), layout)
                self.assertEqual(TEAM_LAYOUTS[team_mode], layout)
                self.assertEqual(
                    CustomLauncherConfig.from_dict(config.to_dict()).team_mode,
                    team_mode,
                )

    def test_three_and_four_team_region_labels_match_fixed_starts(self) -> None:
        self.assertEqual(team_label_for_slot(14, 3), "3팀·남부")
        self.assertEqual(team_label_for_slot(14, 4), "4팀·남동")
        self.assertEqual(team_label_for_slot(4, 4), "1팀·북서")
        self.assertEqual(team_label_for_slot(10, 4), "4팀·남동")
        self.assertEqual(team_label_for_slot(11, 4), "2팀·북동")

    def test_legacy_east_team_layout_is_migrated_without_losing_slots(self) -> None:
        config = default_custom_config()
        data = config.to_dict()
        legacy_layout = (3, 3, 3, 1, 1, 1, 1, 4, 4, 2, 2, 2, 2, 4)
        for slot, legacy_team in zip(data["slots"], legacy_layout, strict=True):
            slot["team"] = legacy_team
        data["slots"][9]["race"] = "Protoss"

        migrated = CustomLauncherConfig.from_dict(data)

        self.assertEqual(migrated.team_mode, 4)
        self.assertEqual(migrated.slots[9].team, 4)
        self.assertEqual(migrated.slots[9].race, "Protoss")
        self.assertEqual(migrated.slots[10].team, 2)

    def test_arbitrary_team_mix_is_rejected(self) -> None:
        config = default_custom_config()
        slots = tuple(
            replace(slot, team=4) if slot.slot == 1 else slot
            for slot in config.slots
        )
        with self.assertRaisesRegex(ValueError, "고정 프리셋"):
            replace(config, slots=slots).validate()

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
