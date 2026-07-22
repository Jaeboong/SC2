from __future__ import annotations

from dataclasses import dataclass, field
from math import floor

from .custom_config import CustomLauncherConfig, SlotConfig
from .custom_runtime import runtime_player_id, runtime_slots
from .protocol import Sc2Connection, Sc2ProtocolError


MOVE_ABILITY_ID = 16
COMMAND_COORDINATE_BASE = 100.0
OPCODE_ATTACK_GROUND = 10
# 대상 지정 공격. 새 opcode는 X=100+opcode가 엔진 검증 대역(X≤114)에 머물도록
# 14 이하만 쓴다 — X 111~199 대역은 엔진에서 쏴 본 적이 없다.
OPCODE_ATTACK_TARGETED = 11
MARINE_UNIT_TYPE = 48
GAME_LOOPS_PER_SECOND = 22.4
SUPPORT_DAMAGE_THRESHOLD = 12.0
SUPPORT_THREAT_WINDOW_SECONDS = 4.0
SUPPORT_ENEMY_RADIUS = 20.0
SUPPORT_VICTIM_COOLDOWN_SECONDS = 30.0
SUPPORT_HELPER_COOLDOWN_SECONDS = 45.0
# §70: 치명 위협 하나에 가까운 순서로 함께 보내는 지원자 수. 1명씩은 후반
# 물량전에서 소용이 없었다(사용자 실관측: 팀원이 죽는데 아무도 안 움직임).
SUPPORT_HELPERS_PER_THREAT = 2
# 치명 판정: 피해 중심점 주변 적 전력이 아군의 이 배수 이상이면 지는 싸움으로 본다.
SUPPORT_OUTNUMBER_RATIO = 1.5
# 치명 판정(전력 열세)의 최소 적 전력. 일꾼 견제 같은 소규모 침입(전투력 0인
# 피해자 주변에 마린 두엇)이 열세로 잡혀 지원이 남발되는 것을 막는다.
SUPPORT_MIN_ENEMY_POWER = 8.0
# 치명 판정: 위협 창 동안 잃은 전투력이 (현재+손실) 전력의 이 비율 이상이면
# 치명적 손실로 본다.
SUPPORT_LOSS_RATIO = 0.2
MIN_ATTACK_POWER = 14.0
MAX_ATTACK_POWER = 70.0
ATTACK_POWER_PER_PRODUCER = 6.0
ATTACK_POWER_BASE = 8.0
# 목표 재고의 전투력 환산 합 대비 이 비율을 채우면 출격한다.
ATTACK_STOCK_READINESS_RATIO = 0.7


# 종족 불문 타운홀 합집합. 플레이어는 자기 종족 타운홀만 지으므로 합집합으로 세도
# 안전하고, Random 종족도 판별 없이 완성 기지 수를 셀 수 있다.
TOWN_HALL_TYPES: frozenset[int] = frozenset({
    18, 130, 132,   # 테란: 사령부, 행성 요새, 궤도 사령부
    59,             # 프로토스: 연결체
    86, 100, 101,   # 저그: 부화장, 번식지, 군락
})


GROUND_COMBAT_SUPPLY: dict[int, float] = {
    # Terran
    32: 3.0, 33: 3.0, 48: 1.0, 49: 1.0, 50: 2.0, 51: 2.0,
    52: 6.0, 53: 2.0, 484: 2.0, 498: 2.0, 500: 2.0,
    691: 6.0, 692: 3.0,
    # Protoss
    4: 6.0, 73: 2.0, 74: 2.0, 75: 2.0, 76: 2.0, 77: 2.0,
    83: 4.0, 141: 4.0, 311: 2.0, 694: 3.0,
    # Zerg
    9: 0.5, 105: 0.5, 107: 2.0, 109: 6.0, 110: 2.0,
    111: 2.0, 494: 3.0, 502: 3.0, 503: 3.0, 688: 3.0,
}


PRODUCER_TYPES_BY_BUILD: dict[str, frozenset[int]] = {
    "bio": frozenset({21}),
    "bio_tank": frozenset({21, 27}),
    "hellion_tank": frozenset({27}),
    "thor_tank": frozenset({27}),
    "mech_macro": frozenset({27}),
    "gateway": frozenset({62, 133}),
    "stalker_immortal": frozenset({62, 133, 71}),
    "zealot_archon": frozenset({62, 133}),
    "immortal_colossus": frozenset({62, 133, 71}),
    "disruptor_ground": frozenset({62, 133, 71}),
    "ling_bane": frozenset({86, 100, 101}),
    "roach_ravager": frozenset({86, 100, 101}),
    "roach_hydra": frozenset({86, 100, 101}),
    "hydra_lurker": frozenset({86, 100, 101}),
    "ultra_ling_bane": frozenset({86, 100, 101}),
    "random_ground": frozenset({21, 27, 62, 71, 86, 100, 101, 133}),
}


def command_target(opcode: int, runtime_player: int) -> tuple[float, float]:
    if not 0 <= opcode <= 99:
        raise ValueError(f"opcode out of range: {opcode}")
    if not 1 <= runtime_player <= 14:
        raise ValueError(f"runtime player out of range: {runtime_player}")
    return (
        COMMAND_COORDINATE_BASE + opcode,
        COMMAND_COORDINATE_BASE + runtime_player,
    )


def command_target_with_param(
    opcode: int,
    runtime_player: int,
    param: int,
) -> tuple[float, float]:
    """Y 소수부(1/100 자리)에 0~99 정수 하나를 추가로 싣는 확장 인코딩.

    X 소수부는 0으로 유지되어 지원 분기(X 소수부 1~14 검사)와 충돌하지 않고,
    Y 정수부 복호(FixedToInt 버림)도 소수부 존재와 무관하게 동작한다.
    """

    if not 0 <= param <= 99:
        raise ValueError(f"command param out of range: {param}")
    x, y = command_target(opcode, runtime_player)
    return (x, y + param / 100.0)


def support_target(
    runtime_player: int,
    destination: tuple[float, float],
) -> tuple[float, float]:
    """Encode the helper ID in the X hundredths and preserve the map point."""

    if not 1 <= runtime_player <= 14:
        raise ValueError(f"runtime player out of range: {runtime_player}")
    x, y = destination
    return (float(floor(x)) + runtime_player / 100.0, float(y))


@dataclass(frozen=True)
class StrategyUpdate:
    attack_slots: tuple[int, ...] = ()
    supports: tuple[tuple[int, int], ...] = ()


@dataclass
class _Threat:
    damage: float = 0.0
    weighted_x: float = 0.0
    weighted_y: float = 0.0
    last_seen: float = 0.0
    # 위협 창 동안 타운홀이 맞았는지, 잃은 지상 전투력이 얼마인지 함께 누적한다.
    hall_damage: bool = False
    lost_power: float = 0.0

    def add(
        self,
        damage: float,
        x: float,
        y: float,
        elapsed: float,
        *,
        hall: bool = False,
        lost: float = 0.0,
    ) -> None:
        if elapsed - self.last_seen > SUPPORT_THREAT_WINDOW_SECONDS:
            self.damage = 0.0
            self.weighted_x = 0.0
            self.weighted_y = 0.0
            self.hall_damage = False
            self.lost_power = 0.0
        self.damage += damage
        self.weighted_x += x * damage
        self.weighted_y += y * damage
        self.last_seen = elapsed
        self.hall_damage = self.hall_damage or hall
        self.lost_power += lost

    @property
    def destination(self) -> tuple[float, float]:
        return (self.weighted_x / self.damage, self.weighted_y / self.damage)


@dataclass(frozen=True)
class _ObservationScan:
    """한 관측을 한 번만 훑어 얻은 런타임 플레이어별 집계.

    §95: 종전에는 update() 한 번에 전체 유닛 리스트를 최소 N+4회 순회했다
    (N = 지휘 슬롯 수). _player_statuses가 1회, _health_snapshot이 1회,
    그리고 army_readiness가 **슬롯마다** 1회씩 — 12 AI면 매초 14패스다.
    세 통계(완성 타운홀·지상 전투력·생산 건물 수)는 필터가 같으므로 한
    패스에서 함께 집계한다.

    캐시 키는 관측 **객체 자기 자신**이다(game_loop가 아니다). game_loop로
    키를 잡으면 같은 loop 값을 가진 서로 다른 관측이 낡은 집계를 돌려받는다 —
    실제 게임에서는 loop가 단조 증가해 드러나지 않지만 테스트가 바로 잡아냈고,
    무엇보다 조용히 틀리는 종류의 캐시다. 동일성 비교는 값이 같을 수만 있고
    다를 수는 없으므로 안전하다. 런처가 상태 표시줄에서 army_readiness를 한 번
    더 부르는 것도 같은 객체라 순회가 늘지 않는다.
    """

    townhalls: dict[int, int]
    power: dict[int, float]
    producers: dict[int, int]


@dataclass
class StrategyController:
    connection: Sc2Connection
    config: CustomLauncherConfig
    attack_cooldown_seconds: float = 45.0
    _beacon_tag: int | None = None
    _scan_cache: _ObservationScan | None = None
    _scan_source: object | None = None
    _producer_types_by_runtime: dict[int, frozenset[int]] = field(
        default_factory=dict
    )
    _attack_cooldown_until: dict[int, float] = field(default_factory=dict)
    _health: dict[int, tuple[int, int, float, float, float]] = field(
        default_factory=dict
    )
    _threats: dict[int, _Threat] = field(default_factory=dict)
    _victim_cooldown_until: dict[int, float] = field(default_factory=dict)
    _helper_cooldown_until: dict[int, float] = field(default_factory=dict)
    _custom_ground_combat_supply: dict[int, float] = field(default_factory=dict)
    _stock_targets: dict[int, dict[int, tuple[float, float]]] = field(
        default_factory=dict
    )

    def _is_commanded(self, slot: SlotConfig) -> bool:
        # §66 옵저버 게임은 관전 연결이라 유닛 명령이 불가능해 제어기 자체를
        # 만들지 않는다. 지휘 대상은 언제나 커스텀 AI 슬롯이다.
        return slot.controller == "custom_ai"

    @property
    def commanded_slots(self) -> tuple[SlotConfig, ...]:
        return tuple(
            slot for slot in self.config.active_slots if self._is_commanded(slot)
        )

    def register_ground_combat_unit(self, unit_type: int, supply: float) -> None:
        """Register a generated unit whose numeric ID is assigned by SC2."""

        if unit_type <= 0:
            raise ValueError(f"invalid unit type: {unit_type}")
        if supply <= 0:
            raise ValueError(f"invalid combat supply: {supply}")
        self._custom_ground_combat_supply[unit_type] = supply

    def set_stock_targets(
        self,
        logical_slot: int,
        targets: dict[int, tuple[float, float]],
    ) -> None:
        """목표 재고 주입: 유닛 타입 ID → (기준 수량, 완성 확장당 증가량)."""

        if all(slot.slot != logical_slot for slot in self.commanded_slots):
            raise ValueError(f"P{logical_slot} is not an active custom AI slot")
        for unit_type, (count, per_expansion) in targets.items():
            if unit_type <= 0 or count <= 0 or per_expansion < 0:
                raise ValueError(
                    f"invalid stock target: {unit_type}={count}/{per_expansion}"
                )
        self._stock_targets[logical_slot] = dict(targets)

    def initialize(self, observation) -> None:
        """Capture the invisible command carrier before normal Marines exist."""

        candidates = [
            unit
            for unit in observation.observation.raw_data.units
            if unit.owner == 1 and unit.unit_type == MARINE_UNIT_TYPE
        ]
        if len(candidates) != 1:
            raise RuntimeError(
                "전략 제어기 명령 매개체를 식별하지 못했습니다 "
                f"(후보 {len(candidates)}개)."
            )
        self._beacon_tag = candidates[0].tag
        self._attack_cooldown_until = {
            slot.slot: 0.0 for slot in self.commanded_slots
        }
        self._health = self._health_snapshot(observation)

    async def update(self, observation) -> StrategyUpdate:
        if self._beacon_tag is None:
            self.initialize(observation)

        elapsed = observation.observation.game_loop / GAME_LOOPS_PER_SECOND
        supports = await self._dispatch_supports(observation, elapsed)
        commanded: list[int] = []
        statuses = self._player_statuses(observation)
        for slot in self.commanded_slots:
            # 지원(helper/victim) 쿨다운은 지원 시스템 전용이다. 공격까지 막으면
            # 교전이 이어지는 동안 재발동하는 지원이 출격을 영구 봉쇄한다(§51 실측).
            if elapsed < self._attack_cooldown_until[slot.slot]:
                continue
            combat_power, required_power, _producers = self.army_readiness(
                observation, slot.slot
            )
            if combat_power < required_power:
                continue
            target = self._select_attack_target(slot.team, statuses)
            await self.command_ground_attack(slot.slot, target)
            commanded.append(slot.slot)
            self._attack_cooldown_until[slot.slot] = (
                elapsed + self.attack_cooldown_seconds
            )
        return StrategyUpdate(tuple(commanded), supports)

    def _scan(self, observation) -> _ObservationScan:
        """관측 1회당 유닛 리스트를 한 번만 훑어 플레이어별 집계를 만든다."""

        cached = self._scan_cache
        if cached is not None and self._scan_source is observation:
            return cached
        slots = runtime_slots(self.config)
        if not self._producer_types_by_runtime:
            self._producer_types_by_runtime = {
                runtime: PRODUCER_TYPES_BY_BUILD.get(slot.build, frozenset())
                for runtime, slot in enumerate(slots, start=1)
            }
        producer_types = self._producer_types_by_runtime
        townhalls = {runtime: 0 for runtime in range(1, len(slots) + 1)}
        power = {runtime: 0.0 for runtime in range(1, len(slots) + 1)}
        producers = {runtime: 0 for runtime in range(1, len(slots) + 1)}
        beacon_tag = self._beacon_tag
        for unit in observation.observation.raw_data.units:
            owner = getattr(unit, "owner", 0)
            if not 1 <= owner <= len(slots) or unit.tag == beacon_tag:
                continue
            if getattr(unit, "build_progress", 1.0) < 0.99:
                continue
            unit_type = unit.unit_type
            if unit_type in TOWN_HALL_TYPES:
                townhalls[owner] += 1
            if unit_type in producer_types[owner]:
                producers[owner] += 1
            if getattr(unit, "is_flying", False):
                continue
            power[owner] += self._combat_weight(unit_type)
        scan = _ObservationScan(townhalls, power, producers)
        self._scan_cache = scan
        self._scan_source = observation
        return scan

    def _player_statuses(self, observation) -> dict[int, tuple[int, float]]:
        """런타임 플레이어별 (완성 타운홀 수, 지상 전투력 합)."""

        scan = self._scan(observation)
        return {
            runtime: (scan.townhalls[runtime], scan.power[runtime])
            for runtime in scan.townhalls
        }

    def _select_attack_target(
        self,
        attacker_team: int,
        statuses: dict[int, tuple[int, float]],
    ) -> int | None:
        """살아있는(완성 타운홀 보유) 적 중 지상 전투력이 가장 약한 플레이어."""

        best_runtime: int | None = None
        best_power = 0.0
        for runtime, slot in enumerate(runtime_slots(self.config), start=1):
            if slot.team == attacker_team:
                continue
            halls, enemy_power = statuses.get(runtime, (0, 0.0))
            if halls == 0:
                continue
            if best_runtime is None or enemy_power < best_power:
                best_runtime = runtime
                best_power = enemy_power
        return best_runtime

    def army_readiness(
        self,
        observation,
        logical_slot: int,
    ) -> tuple[float, float, int]:
        slot = next(
            (item for item in self.commanded_slots if item.slot == logical_slot),
            None,
        )
        if slot is None:
            raise ValueError(f"P{logical_slot} is not an active custom AI slot")
        runtime_player = runtime_player_id(self.config, logical_slot)
        # §95: 여기서 다시 전체 유닛을 순회하지 않는다. 같은 틱의 집계를 쓴다 —
        # 슬롯마다 한 패스씩 돌던 것이 12 AI에서 매초 12패스였다.
        scan = self._scan(observation)
        combat_power = scan.power[runtime_player]
        producers = scan.producers[runtime_player]
        bases = scan.townhalls[runtime_player]
        stock = self._stock_targets.get(logical_slot)
        if stock:
            # 목표 재고 달성률 문턱: 기지 수에 비례해 커지는 목표 재고를 전투력으로
            # 환산한 값의 일정 비율을 채우면 출격한다. 빌드가 달라도 "자기 목표 대비
            # 몇 %"라는 같은 잣대를 쓴다.
            expansions = max(bases, 1) - 1
            target_power = sum(
                (count + expansions * per_expansion)
                * self._combat_weight(unit_type)
                for unit_type, (count, per_expansion) in stock.items()
            )
            required_power = max(
                MIN_ATTACK_POWER,
                min(
                    MAX_ATTACK_POWER,
                    target_power * ATTACK_STOCK_READINESS_RATIO,
                ),
            )
        else:
            # 재고 표가 없는 슬롯(random_ground 빌드 등)은 생산 건물 수 공식 폴백.
            required_power = max(
                MIN_ATTACK_POWER,
                min(
                    MAX_ATTACK_POWER,
                    ATTACK_POWER_BASE + producers * ATTACK_POWER_PER_PRODUCER,
                ),
            )
        return combat_power, required_power, producers

    async def command_ground_attack(
        self,
        logical_slot: int,
        target_runtime: int | None = None,
    ) -> None:
        """지상군 출격. 대상이 있으면 opcode 11(동적 목적지), 없으면 10(정적)."""

        slot = next(
            (item for item in self.commanded_slots if item.slot == logical_slot),
            None,
        )
        if slot is None:
            raise ValueError(f"P{logical_slot} is not an active custom AI slot")
        attacker = runtime_player_id(self.config, logical_slot)
        if target_runtime is None:
            await self._send(OPCODE_ATTACK_GROUND, attacker)
        else:
            await self._send(OPCODE_ATTACK_TARGETED, attacker, target_runtime)

    async def command_support(
        self,
        helper_logical_slot: int,
        destination: tuple[float, float],
    ) -> None:
        slot = next(
            (
                item
                for item in self.commanded_slots
                if item.slot == helper_logical_slot
            ),
            None,
        )
        if slot is None:
            raise ValueError(f"P{helper_logical_slot} is not an active custom AI slot")
        assert self._beacon_tag is not None
        result = await self.connection.raw_unit_command(
            [self._beacon_tag],
            MOVE_ABILITY_ID,
            target_position=support_target(
                runtime_player_id(self.config, helper_logical_slot),
                destination,
            ),
        )
        if result != (1,):
            raise Sc2ProtocolError(
                f"지원 명령 거부: P{helper_logical_slot}, result={result}"
            )

    async def _dispatch_supports(
        self,
        observation,
        elapsed: float,
    ) -> tuple[tuple[int, int], ...]:
        current = self._health_snapshot(observation)
        for tag, (owner, unit_type, health, x, y) in current.items():
            previous = self._health.get(tag)
            if previous is None or previous[0] != owner:
                continue
            damage = previous[2] - health
            if damage <= 0.0:
                continue
            if not self._enemy_near(owner, x, y, current):
                continue
            self._threats.setdefault(owner, _Threat()).add(
                damage, x, y, elapsed, hall=unit_type in TOWN_HALL_TYPES
            )
        # 사라진 유닛(전사)은 남은 체력을 피해로, 지상 전투력을 손실로 누적한다.
        # 생존자 HP가 안 깎여도 한 방에 죽는 유닛의 손실이 위협에 잡히게 한다.
        for tag, (owner, unit_type, health, x, y) in self._health.items():
            if tag in current:
                continue
            if not self._enemy_near(owner, x, y, current):
                continue
            self._threats.setdefault(owner, _Threat()).add(
                health,
                x,
                y,
                elapsed,
                hall=unit_type in TOWN_HALL_TYPES,
                lost=self._combat_weight(unit_type),
            )
        self._health = current

        runtime = runtime_slots(self.config)
        supports: list[tuple[int, int]] = []
        for victim_runtime, threat in tuple(self._threats.items()):
            if elapsed - threat.last_seen > SUPPORT_THREAT_WINDOW_SECONDS:
                del self._threats[victim_runtime]
                continue
            if threat.damage < SUPPORT_DAMAGE_THRESHOLD:
                continue
            if elapsed < self._victim_cooldown_until.get(victim_runtime, 0.0):
                continue
            if not 1 <= victim_runtime <= len(runtime):
                continue
            # 피해가 났다는 사실만으로 지원하지 않는다(§56 지원 남발).
            # 기지 위협·국지 전력 열세·급격한 손실 중 하나여야 치명으로 본다.
            if not self._threat_is_critical(victim_runtime, threat, current):
                continue
            victim = runtime[victim_runtime - 1]
            destination = threat.destination
            candidates = []
            for helper_runtime, helper in enumerate(runtime, start=1):
                if not self._is_commanded(helper) or helper.team != victim.team:
                    continue
                if helper_runtime == victim_runtime:
                    continue
                # §70: "그 틱에 피해를 입은 슬롯 전부 제외"는 후반 대규모 교전에서
                # 매 틱 거의 전원을 걸러 지원이 사실상 한 번도 못 나가게 했다
                # (사용자 실관측). 자기 타운홀이 맞고 있는 슬롯만 제외한다.
                helper_threat = self._threats.get(helper_runtime)
                if helper_threat is not None and helper_threat.hall_damage:
                    continue
                if elapsed < self._helper_cooldown_until.get(helper_runtime, 0.0):
                    continue
                center = self._player_center(current, helper_runtime)
                if center is None:
                    continue
                distance_sq = (
                    (center[0] - destination[0]) ** 2
                    + (center[1] - destination[1]) ** 2
                )
                candidates.append((distance_sq, helper_runtime, helper))
            if not candidates:
                continue
            candidates.sort(key=lambda item: item[0])
            for _, helper_runtime, helper in candidates[:SUPPORT_HELPERS_PER_THREAT]:
                await self.command_support(helper.slot, destination)
                supports.append((helper.slot, victim.slot))
                self._helper_cooldown_until[helper_runtime] = (
                    elapsed + SUPPORT_HELPER_COOLDOWN_SECONDS
                )
            self._victim_cooldown_until[victim_runtime] = (
                elapsed + SUPPORT_VICTIM_COOLDOWN_SECONDS
            )
            del self._threats[victim_runtime]
        return tuple(supports)

    def _combat_weight(self, unit_type: int) -> float:
        return GROUND_COMBAT_SUPPLY.get(
            unit_type, self._custom_ground_combat_supply.get(unit_type, 0.0)
        )

    def _threat_is_critical(
        self,
        victim_runtime: int,
        threat: _Threat,
        snapshot: dict[int, tuple[int, int, float, float, float]],
    ) -> bool:
        """치명 판정: 타운홀 피격, 국지 전력 열세, 급격한 손실 중 하나면 참.

        멜레 AI의 교전은 대부분 기지 앞에서 벌어지므로 "기지 근처 피해" 같은
        위치 기준은 사실상 모든 교전을 통과시킨다(실측 111→109회). 타운홀이
        실제로 맞았는지와 전력 수치만 본다.
        """

        if threat.hall_damage:
            return True
        slots = runtime_slots(self.config)
        victim_team = slots[victim_runtime - 1].team
        center_x, center_y = threat.destination
        fight_radius_sq = SUPPORT_ENEMY_RADIUS * SUPPORT_ENEMY_RADIUS
        friendly_power = 0.0
        enemy_power = 0.0
        victim_power = 0.0
        for owner, unit_type, _health, x, y in snapshot.values():
            if not 1 <= owner <= len(slots):
                continue
            weight = self._combat_weight(unit_type)
            if weight <= 0.0:
                continue
            if owner == victim_runtime:
                victim_power += weight
            distance_sq = (x - center_x) ** 2 + (y - center_y) ** 2
            if distance_sq > fight_radius_sq:
                continue
            if slots[owner - 1].team == victim_team:
                friendly_power += weight
            else:
                enemy_power += weight
        if enemy_power >= max(
            friendly_power * SUPPORT_OUTNUMBER_RATIO, SUPPORT_MIN_ENEMY_POWER
        ):
            return True
        total_power = victim_power + threat.lost_power
        return (
            threat.lost_power > 0.0
            and total_power > 0.0
            and threat.lost_power >= total_power * SUPPORT_LOSS_RATIO
        )

    def _health_snapshot(
        self, observation
    ) -> dict[int, tuple[int, int, float, float, float]]:
        active_count = len(self.config.active_slots)
        snapshot = {}
        for unit in observation.observation.raw_data.units:
            owner = getattr(unit, "owner", 0)
            if not 1 <= owner <= active_count or unit.tag == self._beacon_tag:
                continue
            health = float(getattr(unit, "health", 0.0)) + float(
                getattr(unit, "shield", 0.0)
            )
            if health <= 0.0:
                continue
            snapshot[unit.tag] = (
                owner, unit.unit_type, health, unit.pos.x, unit.pos.y
            )
        return snapshot

    @staticmethod
    def _player_center(
        snapshot: dict[int, tuple[int, int, float, float, float]],
        runtime_player: int,
    ) -> tuple[float, float] | None:
        points = [
            (x, y)
            for owner, _unit_type, _health, x, y in snapshot.values()
            if owner == runtime_player
        ]
        if not points:
            return None
        return (
            sum(point[0] for point in points) / len(points),
            sum(point[1] for point in points) / len(points),
        )

    def _enemy_near(
        self,
        victim_runtime: int,
        x: float,
        y: float,
        snapshot: dict[int, tuple[int, int, float, float, float]],
    ) -> bool:
        slots = runtime_slots(self.config)
        if not 1 <= victim_runtime <= len(slots):
            return False
        victim_team = slots[victim_runtime - 1].team
        radius_sq = SUPPORT_ENEMY_RADIUS * SUPPORT_ENEMY_RADIUS
        for owner, _unit_type, _health, enemy_x, enemy_y in snapshot.values():
            if not 1 <= owner <= len(slots):
                continue
            if slots[owner - 1].team == victim_team:
                continue
            if (enemy_x - x) ** 2 + (enemy_y - y) ** 2 <= radius_sq:
                return True
        return False

    async def _send(
        self,
        opcode: int,
        runtime_player: int,
        param: int | None = None,
    ) -> None:
        assert self._beacon_tag is not None
        result = await self.connection.raw_unit_command(
            [self._beacon_tag],
            MOVE_ABILITY_ID,
            target_position=(
                command_target(opcode, runtime_player)
                if param is None
                else command_target_with_param(opcode, runtime_player, param)
            ),
        )
        if result != (1,):
            raise Sc2ProtocolError(
                f"전략 명령 거부: opcode={opcode}, P{runtime_player}, result={result}"
            )
