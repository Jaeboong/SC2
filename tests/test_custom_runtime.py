from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from s2clientprotocol import common_pb2 as common_pb
from s2clientprotocol import sc2api_pb2 as sc_pb

from sc2team.custom_config import default_custom_config
from sc2team.custom_runtime import (
    AI_BUILD_BY_STRATEGY,
    RACE_VALUES,
    load_stock_targets,
    player_setups,
    runtime_player_id,
    runtime_slots,
)


class CustomRuntimeTests(unittest.TestCase):
    def test_default_setup_starts_with_the_human_participant(self) -> None:
        config = default_custom_config()
        setups = player_setups(config)
        # 7 로비 슬롯 + §90 야생 저그(맵 플레이어 15, 실제 컴퓨터 슬롯).
        self.assertEqual(len(setups), 9)
        self.assertEqual(setups[0].player_type, sc_pb.Participant)
        self.assertTrue(all(item.player_type == sc_pb.Computer for item in setups[1:]))
        self.assertTrue(
            all(item.difficulty == sc_pb.VeryHard for item in setups[1:])
        )

    def test_wild_zerg_is_the_last_lobby_computer(self) -> None:
        # §90: 중립 적대(P15)는 전투 유닛을 어떤 경로로도 생산할 수 없다는 것이
        # 프로브로 확정됐다. 실제 로비 컴퓨터 슬롯이어야 하며, 플레이 가능한 맵
        # 슬롯 순서상 마지막(맵 플레이어 15)이므로 설정도 맨 뒤여야 한다.
        config = default_custom_config()
        setups = player_setups(config)
        wild = setups[-1]
        self.assertEqual(wild.player_type, sc_pb.Computer)
        self.assertEqual(wild.race, RACE_VALUES["Zerg"])
        observed = player_setups(config, observer=True)
        self.assertEqual(observed[-1].player_type, sc_pb.Observer)
        self.assertEqual(observed[-2].race, RACE_VALUES["Zerg"])

    def test_disabling_wild_zerg_drops_its_lobby_slot(self) -> None:
        # §93: 야생 저그를 끄면 빌더가 MapInfo 승격을 하지 않으므로 P15는 더 이상
        # 플레이 가능한 맵 슬롯이 아니다. 설정에 항목이 남아 있으면 슬롯 수가
        # 어긋나고, 무엇보다 P15가 로비 컴퓨터로 남으면 우리가 맵 트리거를
        # 비워도 블리자드 멜레 AI가 대신 생산한다.
        config = replace(default_custom_config(), wild_zerg=False)
        setups = player_setups(config)
        self.assertEqual(len(setups), 8)
        self.assertEqual(setups[0].player_type, sc_pb.Participant)
        self.assertNotIn(
            "야생", " ".join(item.player_name for item in setups if item.player_name)
        )

    def test_detailed_builds_map_to_ground_focused_ai_profiles(self) -> None:
        self.assertEqual(AI_BUILD_BY_STRATEGY["bio"], sc_pb.Rush)
        self.assertEqual(AI_BUILD_BY_STRATEGY["bio_tank"], sc_pb.Timing)
        self.assertEqual(AI_BUILD_BY_STRATEGY["thor_tank"], sc_pb.Power)
        self.assertEqual(AI_BUILD_BY_STRATEGY["mech_macro"], sc_pb.Macro)

    def test_human_is_promoted_ahead_of_lower_logical_ai_slots(self) -> None:
        config = default_custom_config()
        slots = tuple(
            replace(
                slot,
                controller=(
                    "human"
                    if slot.slot == 10
                    else "custom_ai"
                    if slot.slot == 1
                    else "empty"
                    if slot.slot == 11
                    else slot.controller
                ),
                race="Terran" if slot.slot == 1 else slot.race,
                build="bio_tank" if slot.slot == 1 else slot.build,
            )
            for slot in config.slots
        )
        moved = replace(config, slots=slots)
        moved.validate()
        setups = player_setups(moved)
        self.assertEqual(setups[0].player_type, sc_pb.Participant)
        self.assertEqual(setups[1].player_type, sc_pb.Computer)
        self.assertEqual(setups[1].race, common_pb.Terran)
        participant_index = next(
            index for index, setup in enumerate(setups)
            if setup.player_type == sc_pb.Participant
        )
        runtime_ids = [slot.slot for slot in runtime_slots(moved)]
        self.assertEqual(runtime_ids[participant_index], 10)
        self.assertEqual(runtime_player_id(moved, 10), 1)
        self.assertEqual(runtime_player_id(moved, 1), 2)

    def test_first_sparse_logical_slot_becomes_runtime_player_one(self) -> None:
        config = default_custom_config()
        slots = tuple(
            replace(
                slot,
                controller=(
                    "human"
                    if slot.slot == 2
                    else "empty"
                    if slot.slot == 1
                    else slot.controller
                ),
            )
            for slot in config.slots
        )
        moved = replace(config, slots=slots)
        moved.validate()
        self.assertEqual(moved.human.slot, 2)
        self.assertEqual(runtime_player_id(moved, 2), 1)

    def test_load_stock_targets_reads_builder_sidecar(self) -> None:
        # 빌더가 출력 맵 옆에 남기는 <맵>.targets.json 사이드카를 읽는다.
        with tempfile.TemporaryDirectory() as tmp:
            output_map = Path(tmp) / "map.SC2Map"
            sidecar = Path(tmp) / "map.SC2Map.targets.json"
            sidecar.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "slots": [
                            {
                                "runtime_player": 2,
                                "logical_slot": 2,
                                "build": "bio",
                                "race": "Terran",
                                "stock": {
                                    "Marine": {"count": 24, "perExpansion": 15},
                                    "SC2TeamMedic": {"count": 4, "perExpansion": 3},
                                },
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            slots = load_stock_targets(output_map)

            self.assertEqual(len(slots), 1)
            self.assertEqual(slots[0]["logical_slot"], 2)
            self.assertEqual(slots[0]["stock"]["Marine"]["count"], 24)
            self.assertEqual(slots[0]["stock"]["SC2TeamMedic"]["perExpansion"], 3)

    def test_load_stock_targets_rejects_unknown_version(self) -> None:
        # 사이드카 스키마 버전이 다르면 조용히 진행하지 않고 실패해야 한다.
        with tempfile.TemporaryDirectory() as tmp:
            output_map = Path(tmp) / "map.SC2Map"
            sidecar = Path(tmp) / "map.SC2Map.targets.json"
            sidecar.write_text(
                json.dumps({"version": 2, "slots": []}),
                encoding="utf-8",
            )

            with self.assertRaises(RuntimeError):
                load_stock_targets(output_map)

    def test_human_is_always_runtime_player_one(self) -> None:
        config = default_custom_config()
        slots = tuple(
            replace(
                slot,
                controller=(
                    "human"
                    if slot.slot == 3
                    else "custom_ai"
                    if slot.slot == 1
                    else slot.controller
                ),
            )
            for slot in config.slots
        )
        moved = replace(config, slots=slots)
        moved.validate()
        self.assertEqual(runtime_player_id(moved, 3), 1)
        self.assertEqual(runtime_slots(moved)[0].slot, 3)


if __name__ == "__main__":
    unittest.main()
