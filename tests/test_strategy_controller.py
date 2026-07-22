from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace

from sc2team.custom_config import default_custom_config
from sc2team.strategy_controller import (
    StrategyController,
    command_target,
    command_target_with_param,
    support_target,
)


def observation(game_loop: int, units=()):
    return SimpleNamespace(
        observation=SimpleNamespace(
            game_loop=game_loop,
            raw_data=SimpleNamespace(units=list(units)),
        )
    )


class FakeConnection:
    def __init__(self) -> None:
        self.commands = []

    async def raw_unit_command(self, tags, ability_id, **kwargs):
        self.commands.append((tuple(tags), ability_id, kwargs))
        return (1,)


class StrategyControllerTests(unittest.TestCase):
    def test_command_encoding(self) -> None:
        self.assertEqual(command_target(10, 5), (110.0, 105.0))
        with self.assertRaises(ValueError):
            command_target(10, 15)
        self.assertEqual(support_target(5, (26.8, 91.25)), (26.05, 91.25))

    def test_command_encoding_with_param(self) -> None:
        # 대상 지정 공격(opcode 11)은 Y 소수부에 대상 런타임 플레이어를 싣는다.
        x, y = command_target_with_param(11, 5, 8)
        self.assertEqual(x, 111.0)
        self.assertAlmostEqual(y, 105.08)
        with self.assertRaises(ValueError):
            command_target_with_param(11, 5, 100)
        with self.assertRaises(ValueError):
            command_target_with_param(11, 5, -1)

    def test_attack_targets_weakest_living_enemy(self) -> None:
        # 공격은 살아있는(완성 타운홀 보유) 적 중 지상 전투력이 가장 약한 플레이어를
        # 노린다(opcode 11). 살아있는 적이 없으면 opcode 10(정적 목적지) 폴백.
        connection = FakeConnection()
        config = default_custom_config()
        controller = StrategyController(connection, config)
        beacon = SimpleNamespace(owner=1, unit_type=48, tag=12345)
        # 적팀(런타임 5~8, 논리 P8~P11): 5는 강한 생존자, 6은 약한 생존자,
        # 7은 타운홀 없이 병력만 남은 탈락자.
        strong_hall = self._unit(500, 5, 1500.0, 180.0, 50.0, unit_type=18)
        strong_army = [
            self._unit(510 + index, 5, 45.0, 180.0, 50.0, unit_type=48)
            for index in range(10)
        ]
        weak_hall = self._unit(600, 6, 1500.0, 200.0, 50.0, unit_type=18)
        weak_army = [self._unit(610, 6, 45.0, 200.0, 50.0, unit_type=48)]
        dead_army = [
            self._unit(710 + index, 7, 45.0, 220.0, 50.0, unit_type=48)
            for index in range(5)
        ]
        state = observation(
            0, [beacon, strong_hall, *strong_army, weak_hall, *weak_army, *dead_army]
        )
        controller.initialize(state)
        controller.army_readiness = lambda _observation, _slot: (100.0, 14.0, 1)

        result = asyncio.run(controller.update(observation(1, list(state.observation.raw_data.units))))

        self.assertEqual(
            result.attack_slots,
            tuple(slot.slot for slot in config.custom_ai_slots),
        )
        # 1팀 공격자(첫 명령 = 논리 P2, 런타임 2)는 가장 약한 생존 적(런타임 6)을 노린다.
        first_x, first_y = connection.commands[0][2]["target_position"]
        self.assertEqual(first_x, 111.0)
        self.assertAlmostEqual(first_y, 102.06)
        # 2팀 공격자는 1팀에 살아있는 타운홀이 없으므로 opcode 10으로 폴백한다.
        last_x, last_y = connection.commands[-1][2]["target_position"]
        self.assertEqual(last_x, 110.0)
        # 마지막 명령 = 마지막 AI 슬롯, 런타임 번호 = 1(인간) + AI 슬롯 수
        self.assertEqual(last_y, 100.0 + 1 + len(config.custom_ai_slots))

    def test_controller_caches_beacon_and_dispatches_due_players(self) -> None:
        connection = FakeConnection()
        config = default_custom_config()
        controller = StrategyController(connection, config)
        beacon = SimpleNamespace(owner=1, unit_type=48, tag=12345)
        controller.initialize(observation(0, [beacon]))
        controller.army_readiness = lambda _observation, _slot: (100.0, 14.0, 1)

        commanded = asyncio.run(controller.update(observation(1, [beacon])))

        self.assertEqual(
            commanded.attack_slots,
            tuple(slot.slot for slot in config.custom_ai_slots),
        )
        self.assertEqual(commanded.supports, ())
        self.assertEqual(len(connection.commands), len(config.custom_ai_slots))
        self.assertTrue(all(command[0] == (12345,) for command in connection.commands))

    def test_attack_readiness_scales_with_production_and_ignores_medivacs(self) -> None:
        connection = FakeConnection()
        config = default_custom_config()
        controller = StrategyController(connection, config)
        beacon = SimpleNamespace(owner=1, unit_type=48, tag=12345)
        barracks = self._unit(200, 2, 1000.0, 10.0, 10.0, unit_type=21)
        marines = [
            self._unit(300 + index, 2, 45.0, 10.0, 10.0, unit_type=48)
            for index in range(13)
        ]
        medivacs = [
            self._unit(
                400 + index,
                2,
                150.0,
                10.0,
                10.0,
                unit_type=54,
                is_flying=True,
            )
            for index in range(15)
        ]
        state = observation(0, [beacon, barracks, *marines, *medivacs])
        controller.initialize(state)

        power, required, producers = controller.army_readiness(state, 2)

        self.assertEqual(power, 13.0)
        self.assertEqual(required, 14.0)
        self.assertEqual(producers, 1)

        second_barracks = self._unit(201, 2, 1000.0, 12.0, 10.0, unit_type=21)
        larger = observation(
            0, [beacon, barracks, second_barracks, *marines, *medivacs]
        )
        power, required, producers = controller.army_readiness(larger, 2)
        self.assertEqual(power, 13.0)
        self.assertEqual(required, 20.0)
        self.assertEqual(producers, 2)

    def test_one_observation_is_scanned_once_and_never_reused_across_states(
        self,
    ) -> None:
        # §95: army_readiness가 슬롯마다 전체 유닛을 다시 순회하던 것을 관측당
        # 1패스로 합쳤다. 두 가지를 함께 고정한다.
        #  (1) 한 관측 안에서 몇 번을 물어봐도 순회는 한 번이다.
        #  (2) **다른** 관측이면 game_loop가 같아도 절대 재사용하지 않는다.
        #      캐시를 game_loop로 키잡았을 때 실제로 낡은 값을 반환했다.
        class CountingUnits(list):
            passes = 0

            def __iter__(self):
                type(self).passes += 1
                return super().__iter__()

        connection = FakeConnection()
        config = default_custom_config()
        controller = StrategyController(connection, config)
        beacon = SimpleNamespace(owner=1, unit_type=48, tag=12345)
        barracks = self._unit(200, 2, 1000.0, 10.0, 10.0, unit_type=21)
        marines = [
            self._unit(300 + index, 2, 45.0, 10.0, 10.0, unit_type=48)
            for index in range(13)
        ]
        state = observation(0, [beacon, barracks, *marines])
        controller.initialize(state)

        state.observation.raw_data.units = CountingUnits(
            state.observation.raw_data.units
        )
        CountingUnits.passes = 0
        for slot in config.custom_ai_slots:
            controller.army_readiness(state, slot.slot)
        controller._player_statuses(state)
        self.assertEqual(CountingUnits.passes, 1)

        # 같은 game_loop, 다른 관측 — 병영 하나가 더 있으므로 결과가 달라야 한다.
        second_barracks = self._unit(201, 2, 1000.0, 12.0, 10.0, unit_type=21)
        larger = observation(0, [beacon, barracks, second_barracks, *marines])
        self.assertEqual(controller.army_readiness(larger, 2)[2], 2)

    def test_readiness_uses_stock_completion_ratio_when_targets_set(self) -> None:
        # 재고 표가 주입된 슬롯은 producer 공식 대신 목표재고 달성률(70%) 문턱을 쓴다.
        connection = FakeConnection()
        config = default_custom_config()
        controller = StrategyController(connection, config)
        beacon = SimpleNamespace(owner=1, unit_type=48, tag=12345)
        controller.set_stock_targets(2, {48: (30.0, 12.0)})
        townhall = self._unit(500, 2, 1500.0, 10.0, 10.0, unit_type=18)
        barracks = self._unit(200, 2, 1000.0, 10.0, 10.0, unit_type=21)
        marines = [
            self._unit(300 + index, 2, 45.0, 10.0, 10.0, unit_type=48)
            for index in range(13)
        ]
        state = observation(0, [beacon, townhall, barracks, *marines])
        controller.initialize(state)

        power, required, producers = controller.army_readiness(state, 2)

        # 1기지: 목표 30기 × 마린 1.0 = 30 → 문턱 21.0 (producer 공식이면 14.0)
        self.assertEqual(power, 13.0)
        self.assertAlmostEqual(required, 21.0)
        self.assertEqual(producers, 1)

    def test_stock_threshold_scales_with_completed_bases(self) -> None:
        # 완성 확장마다 perExpansion만큼 목표가 커지고, 미완성 타운홀은 세지 않는다.
        connection = FakeConnection()
        config = default_custom_config()
        controller = StrategyController(connection, config)
        beacon = SimpleNamespace(owner=1, unit_type=48, tag=12345)
        controller.set_stock_targets(2, {48: (30.0, 12.0)})
        main_base = self._unit(500, 2, 1500.0, 10.0, 10.0, unit_type=18)
        expansion = self._unit(501, 2, 1500.0, 40.0, 10.0, unit_type=132)
        unfinished = self._unit(
            502, 2, 700.0, 70.0, 10.0, unit_type=18, build_progress=0.5
        )
        state = observation(0, [beacon, main_base, expansion, unfinished])
        controller.initialize(state)

        _power, required, _producers = controller.army_readiness(state, 2)

        # 완성 2기지: 목표 30 + 12 = 42 → 문턱 29.4
        self.assertAlmostEqual(required, 29.4)

    def test_stock_threshold_clamps_bases_and_power_bounds(self) -> None:
        # 타운홀 0개는 1기지로 취급하고, 문턱은 [14, 70]을 벗어나지 않는다.
        connection = FakeConnection()
        config = default_custom_config()
        controller = StrategyController(connection, config)
        beacon = SimpleNamespace(owner=1, unit_type=48, tag=12345)
        state = observation(0, [beacon])
        controller.initialize(state)

        controller.set_stock_targets(2, {48: (10.0, 1.0)})
        _, required, _ = controller.army_readiness(state, 2)
        self.assertEqual(required, 14.0)

        controller.set_stock_targets(2, {48: (200.0, 1.0)})
        _, required, _ = controller.army_readiness(state, 2)
        self.assertEqual(required, 70.0)

    def test_stock_targets_reject_non_ai_slot(self) -> None:
        # 인간 슬롯(P1)에는 재고 표를 주입할 수 없다.
        connection = FakeConnection()
        config = default_custom_config()
        controller = StrategyController(connection, config)

        with self.assertRaises(ValueError):
            controller.set_stock_targets(1, {48: (10.0, 1.0)})

    def test_nearest_ai_supports_damaged_human_ally(self) -> None:
        connection = FakeConnection()
        config = default_custom_config()
        controller = StrategyController(connection, config)
        beacon = SimpleNamespace(owner=1, unit_type=48, tag=12345)
        human = self._unit(1, 1, 100.0, 10.0, 10.0)
        near_helper = self._unit(2, 2, 100.0, 13.0, 10.0)
        far_helper = self._unit(3, 3, 100.0, 70.0, 70.0)
        enemy = self._unit(5, 5, 100.0, 18.0, 10.0)
        initial = observation(0, [beacon, human, near_helper, far_helper, enemy])
        controller.initialize(initial)

        damaged = self._unit(1, 1, 80.0, 10.0, 10.0)
        result = asyncio.run(
            controller.update(
                observation(22, [beacon, damaged, near_helper, far_helper, enemy])
            )
        )

        # §70: 치명 위협에는 가까운 순서로 최대 2명이 함께 간다.
        self.assertEqual(result.supports, ((2, 1), (3, 1)))
        self.assertEqual(connection.commands[-2][2]["target_position"], (10.02, 10.0))
        self.assertEqual(connection.commands[-1][2]["target_position"], (10.03, 10.0))

    def test_enemy_team_ais_support_each_other(self) -> None:
        connection = FakeConnection()
        config = default_custom_config()
        controller = StrategyController(connection, config)
        beacon = SimpleNamespace(owner=1, unit_type=48, tag=12345)
        victim = self._unit(50, 5, 100.0, 180.0, 50.0)  # logical P8
        helper = self._unit(60, 6, 100.0, 175.0, 50.0)  # logical P9
        enemy = self._unit(10, 2, 100.0, 188.0, 50.0)
        initial = observation(0, [beacon, victim, helper, enemy])
        controller.initialize(initial)

        damaged = self._unit(50, 5, 75.0, 180.0, 50.0)
        result = asyncio.run(
            controller.update(observation(22, [beacon, damaged, helper, enemy]))
        )

        self.assertEqual(result.supports, ((9, 8),))
        self.assertEqual(connection.commands[-1][2]["target_position"], (180.06, 50.0))

    def test_support_dispatch_does_not_block_same_cycle_attack(self) -> None:
        # 지원 발동으로 helper 쿨다운이 걸려도, 문턱을 충족한 공격은 같은 사이클에 나가야 한다.
        connection = FakeConnection()
        config = default_custom_config()
        controller = StrategyController(connection, config)
        beacon = SimpleNamespace(owner=1, unit_type=48, tag=12345)
        human = self._unit(1, 1, 100.0, 10.0, 10.0)
        helper = self._unit(2, 2, 100.0, 13.0, 10.0)
        enemy = self._unit(5, 5, 100.0, 18.0, 10.0)
        controller.initialize(observation(0, [beacon, human, helper, enemy]))
        controller.army_readiness = lambda _observation, _slot: (100.0, 14.0, 1)

        damaged = self._unit(1, 1, 80.0, 10.0, 10.0)
        result = asyncio.run(
            controller.update(observation(22, [beacon, damaged, helper, enemy]))
        )

        self.assertEqual(result.supports, ((2, 1),))
        self.assertEqual(
            result.attack_slots,
            tuple(slot.slot for slot in config.custom_ai_slots),
        )

    def test_supported_victim_still_attacks_when_ready(self) -> None:
        # 피지원자(victim) 쿨다운도 공격을 막지 않아야 한다.
        connection = FakeConnection()
        config = default_custom_config()
        controller = StrategyController(connection, config)
        beacon = SimpleNamespace(owner=1, unit_type=48, tag=12345)
        victim = self._unit(50, 5, 100.0, 180.0, 50.0)  # 논리 P8
        helper = self._unit(60, 6, 100.0, 175.0, 50.0)  # 논리 P9
        enemy = self._unit(10, 2, 100.0, 188.0, 50.0)
        controller.initialize(observation(0, [beacon, victim, helper, enemy]))
        controller.army_readiness = lambda _observation, _slot: (100.0, 14.0, 1)

        damaged = self._unit(50, 5, 75.0, 180.0, 50.0)
        result = asyncio.run(
            controller.update(observation(22, [beacon, damaged, helper, enemy]))
        )

        self.assertEqual(result.supports, ((9, 8),))
        self.assertIn(8, result.attack_slots)
        self.assertIn(9, result.attack_slots)

    def test_attack_repeats_after_attack_cooldown_expires(self) -> None:
        # 공격 자체 쿨다운(45초)은 유지되고, 만료되면 재공격이 나가야 한다.
        connection = FakeConnection()
        config = default_custom_config()
        controller = StrategyController(connection, config)
        beacon = SimpleNamespace(owner=1, unit_type=48, tag=12345)
        controller.initialize(observation(0, [beacon]))
        controller.army_readiness = lambda _observation, _slot: (100.0, 14.0, 1)
        every_slot = tuple(slot.slot for slot in config.custom_ai_slots)

        first = asyncio.run(controller.update(observation(22, [beacon])))
        during = asyncio.run(controller.update(observation(672, [beacon])))  # 30초
        after = asyncio.run(controller.update(observation(1120, [beacon])))  # 50초

        self.assertEqual(first.attack_slots, every_slot)
        self.assertEqual(during.attack_slots, ())
        self.assertEqual(after.attack_slots, every_slot)

    def test_support_repeats_after_support_cooldowns_expire(self) -> None:
        # victim 30초·helper 45초 쿨다운이 만료되면 같은 피해 상황에 재지원해야 한다.
        connection = FakeConnection()
        config = default_custom_config()
        controller = StrategyController(connection, config)
        beacon = SimpleNamespace(owner=1, unit_type=48, tag=12345)
        helper = self._unit(2, 2, 100.0, 13.0, 10.0)
        enemy = self._unit(5, 5, 100.0, 18.0, 10.0)
        controller.initialize(
            observation(0, [beacon, self._unit(1, 1, 100.0, 10.0, 10.0), helper, enemy])
        )

        first = asyncio.run(
            controller.update(
                observation(22, [beacon, self._unit(1, 1, 80.0, 10.0, 10.0), helper, enemy])
            )
        )
        during = asyncio.run(  # 10초: victim(30초)·helper(45초) 쿨다운 진행 중
            controller.update(
                observation(224, [beacon, self._unit(1, 1, 60.0, 10.0, 10.0), helper, enemy])
            )
        )
        after = asyncio.run(  # 50초: 두 쿨다운 모두 만료
            controller.update(
                observation(1120, [beacon, self._unit(1, 1, 40.0, 10.0, 10.0), helper, enemy])
            )
        )

        self.assertEqual(first.supports, ((2, 1),))
        self.assertEqual(during.supports, ())
        self.assertEqual(after.supports, ((2, 1),))

    def test_support_skipped_when_victim_winning_engagement(self) -> None:
        # 이기고 있는 교전은 피해가 나도 지원하지 않는다: 전력 우세, 기지 무관,
        # 손실 없음이면 치명 판정을 통과하지 못한다(§56 지원 남발 억제).
        connection = FakeConnection()
        config = default_custom_config()
        controller = StrategyController(connection, config)
        beacon = SimpleNamespace(owner=1, unit_type=48, tag=12345)
        # P1 병력은 마린(48)을 쓰면 비컨 식별과 충돌하므로 불곰(51)을 쓴다.
        army = [
            self._unit(100 + index, 1, 45.0, 10.0, 10.0, unit_type=51)
            for index in range(10)
        ]
        helper = self._unit(2, 2, 45.0, 13.0, 10.0, unit_type=48)
        enemy = self._unit(5, 5, 45.0, 18.0, 10.0, unit_type=48)
        controller.initialize(observation(0, [beacon, *army, helper, enemy]))

        survivors = [self._unit(100, 1, 20.0, 10.0, 10.0, unit_type=51), *army[1:]]
        result = asyncio.run(
            controller.update(observation(22, [beacon, *survivors, helper, enemy]))
        )

        self.assertEqual(result.supports, ())

    def test_support_fires_when_locally_outnumbered(self) -> None:
        # 피해 지점 주변에서 적 전력이 아군의 1.5배 이상이고 최소 규모(8)를
        # 넘으면 지는 싸움으로 보고 지원한다.
        connection = FakeConnection()
        config = default_custom_config()
        controller = StrategyController(connection, config)
        beacon = SimpleNamespace(owner=1, unit_type=48, tag=12345)
        victim = self._unit(1, 1, 45.0, 10.0, 10.0, unit_type=51)
        helper = self._unit(2, 2, 45.0, 13.0, 10.0, unit_type=48)
        enemies = [
            self._unit(50 + index, 5, 45.0, 12.0, 10.0, unit_type=48)
            for index in range(8)
        ]
        controller.initialize(observation(0, [beacon, victim, helper, *enemies]))

        damaged = self._unit(1, 1, 30.0, 10.0, 10.0, unit_type=51)
        result = asyncio.run(
            controller.update(observation(22, [beacon, damaged, helper, *enemies]))
        )

        self.assertEqual(result.supports, ((2, 1),))

    def test_small_poke_does_not_trigger_support(self) -> None:
        # 마린 두엇 수준의 견제는 열세여도 최소 적 전력(8)에 못 미쳐 지원하지 않는다.
        connection = FakeConnection()
        config = default_custom_config()
        controller = StrategyController(connection, config)
        beacon = SimpleNamespace(owner=1, unit_type=48, tag=12345)
        victim = self._unit(1, 1, 45.0, 10.0, 10.0, unit_type=51)
        helper = self._unit(2, 2, 45.0, 13.0, 10.0, unit_type=48)
        enemies = [
            self._unit(50 + index, 5, 45.0, 12.0, 10.0, unit_type=48)
            for index in range(2)
        ]
        controller.initialize(observation(0, [beacon, victim, helper, *enemies]))

        damaged = self._unit(1, 1, 30.0, 10.0, 10.0, unit_type=51)
        result = asyncio.run(
            controller.update(observation(22, [beacon, damaged, helper, *enemies]))
        )

        self.assertEqual(result.supports, ())

    def test_support_fires_on_townhall_damage_even_when_winning(self) -> None:
        # 기지(타운홀) 피격은 전력 우세와 무관하게 지원 대상이다.
        connection = FakeConnection()
        config = default_custom_config()
        controller = StrategyController(connection, config)
        beacon = SimpleNamespace(owner=1, unit_type=48, tag=12345)
        hall = self._unit(1, 1, 1500.0, 10.0, 10.0)  # 기본 unit_type=18(사령부)
        army = [
            self._unit(100 + index, 1, 45.0, 10.0, 10.0, unit_type=51)
            for index in range(10)
        ]
        helper = self._unit(2, 2, 45.0, 13.0, 10.0, unit_type=48)
        enemy = self._unit(5, 5, 45.0, 18.0, 10.0, unit_type=48)
        controller.initialize(observation(0, [beacon, hall, *army, helper, enemy]))

        damaged_hall = self._unit(1, 1, 1480.0, 10.0, 10.0)
        result = asyncio.run(
            controller.update(
                observation(22, [beacon, damaged_hall, *army, helper, enemy])
            )
        )

        self.assertEqual(result.supports, ((2, 1),))

    def test_support_fires_on_rapid_army_loss(self) -> None:
        # 전력 우세라도 위협 창 안에 군대의 20% 이상을 잃으면 치명적 손실로 지원한다.
        # 사라진 유닛(전사)은 생존자 HP가 안 깎여도 감지되어야 한다.
        connection = FakeConnection()
        config = default_custom_config()
        controller = StrategyController(connection, config)
        beacon = SimpleNamespace(owner=1, unit_type=48, tag=12345)
        army = [
            self._unit(100 + index, 1, 45.0, 10.0, 10.0, unit_type=51)
            for index in range(5)
        ]
        helper = self._unit(2, 2, 45.0, 13.0, 10.0, unit_type=48)
        enemy = self._unit(5, 5, 45.0, 12.0, 10.0, unit_type=48)
        controller.initialize(observation(0, [beacon, *army, helper, enemy]))

        result = asyncio.run(
            controller.update(observation(22, [beacon, *army[2:], helper, enemy]))
        )

        self.assertEqual(result.supports, ((2, 1),))

    def test_skirmishing_helper_still_supports(self) -> None:
        # §70 회귀: 지원 후보가 같은 틱에 (타운홀이 아닌) 피해를 입었어도
        # 지원은 나가야 한다. 예전에는 피해 슬롯 전부를 제외해 후반 대규모
        # 교전에서 지원이 사실상 봉쇄됐다.
        connection = FakeConnection()
        config = default_custom_config()
        controller = StrategyController(connection, config)
        beacon = SimpleNamespace(owner=1, unit_type=48, tag=12345)
        hall = self._unit(1, 1, 1500.0, 10.0, 10.0)  # 피해자: 사람 슬롯 타운홀
        helper_unit = self._unit(2, 2, 45.0, 13.0, 10.0, unit_type=51)
        enemy = self._unit(5, 5, 100.0, 18.0, 10.0)
        controller.initialize(observation(0, [beacon, hall, helper_unit, enemy]))

        damaged_hall = self._unit(1, 1, 1480.0, 10.0, 10.0)
        skirmishing_helper = self._unit(2, 2, 30.0, 13.0, 10.0, unit_type=51)
        result = asyncio.run(
            controller.update(
                observation(22, [beacon, damaged_hall, skirmishing_helper, enemy])
            )
        )

        self.assertEqual(result.supports, ((2, 1),))

    def test_helper_defending_own_hall_is_excluded(self) -> None:
        # §70: 자기 타운홀이 맞고 있는 슬롯은 제 코가 석 자라 지원을 보내지 않는다.
        connection = FakeConnection()
        config = default_custom_config()
        controller = StrategyController(connection, config)
        beacon = SimpleNamespace(owner=1, unit_type=48, tag=12345)
        hall = self._unit(1, 1, 1500.0, 10.0, 10.0)
        helper_hall = self._unit(2, 2, 1500.0, 60.0, 60.0)  # 타운홀(기본 18)
        enemy = self._unit(5, 5, 100.0, 18.0, 10.0)
        enemy_at_helper = self._unit(6, 5, 100.0, 62.0, 60.0)
        controller.initialize(
            observation(0, [beacon, hall, helper_hall, enemy, enemy_at_helper])
        )

        damaged_hall = self._unit(1, 1, 1480.0, 10.0, 10.0)
        damaged_helper_hall = self._unit(2, 2, 1480.0, 60.0, 60.0)
        result = asyncio.run(
            controller.update(
                observation(
                    22,
                    [beacon, damaged_hall, damaged_helper_hall, enemy, enemy_at_helper],
                )
            )
        )

        self.assertEqual(result.supports, ())

    def test_damage_without_nearby_enemy_does_not_request_support(self) -> None:
        connection = FakeConnection()
        config = default_custom_config()
        controller = StrategyController(connection, config)
        beacon = SimpleNamespace(owner=1, unit_type=48, tag=12345)
        human = self._unit(1, 1, 100.0, 10.0, 10.0)
        helper = self._unit(2, 2, 100.0, 13.0, 10.0)
        controller.initialize(observation(0, [beacon, human, helper]))

        damaged = self._unit(1, 1, 70.0, 10.0, 10.0)
        result = asyncio.run(
            controller.update(observation(22, [beacon, damaged, helper]))
        )

        self.assertEqual(result.supports, ())

    @staticmethod
    def _unit(
        tag: int,
        owner: int,
        health: float,
        x: float,
        y: float,
        *,
        unit_type: int = 18,
        is_flying: bool = False,
        build_progress: float = 1.0,
    ):
        return SimpleNamespace(
            tag=tag,
            owner=owner,
            unit_type=unit_type,
            health=health,
            shield=0.0,
            build_progress=build_progress,
            is_flying=is_flying,
            pos=SimpleNamespace(x=x, y=y),
        )


if __name__ == "__main__":
    unittest.main()
