"""P1 무명령 참가 + 6 AI 대 6 일반 저그 AI의 실전 전력 측정.

야생 저그(P15)는 명시적으로 끈다.
사용법: .venv\\Scripts\\python.exe verification\\measure_zerg_7v6.py terran|protoss [게임분]
"""

from __future__ import annotations

import asyncio
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sc2team.custom_config import CustomLauncherConfig, SlotConfig
from sc2team.custom_runtime import RACE_VALUES, build_runtime_map, player_setups
from sc2team.process import discover_sc2_executable, launch_sc2, stop_process
from sc2team.protocol import Sc2Connection
from sc2team.strategy_controller import GAME_LOOPS_PER_SECOND, StrategyController
from s2clientprotocol import sc2api_pb2 as sc_pb


BASE_MAP = PROJECT_ROOT / "map" / "source" / "europe-melee-2-7v7-rich-50000-fixed-teams.SC2Map"
PORT = 14152
WORKERS = {"Terran": 45, "Protoss": 84, "Zerg": 104}
TOWN_HALLS = {
    "Terran": {18, 130, 132},
    "Protoss": {59},
    "Zerg": {86, 100, 101},
}
BUILDS = {
    "Terran": ("bio", "bio_tank", "hellion_tank", "thor_tank", "mech_macro", "random_ground"),
    "Protoss": ("gateway", "stalker_immortal", "zealot_archon", "immortal_colossus", "disruptor_ground", "random_ground"),
    "Zerg": ("ling_bane", "roach_ravager", "roach_hydra", "hydra_lurker", "ultra_ling_bane", "random_ground"),
}


@dataclass(frozen=True)
class UnitInfo:
    food: float
    minerals: int
    gas: int
    structure: bool


def kind(unit_type: int, race: str, catalog: dict[int, UnitInfo]) -> str:
    info = catalog.get(unit_type, UnitInfo(0.0, 0, 0, False))
    if info.structure:
        return "structure"
    if unit_type == WORKERS[race]:
        return "worker"
    if info.food > 0.0:
        return "army"
    return "other"


class TeamTracker:
    def __init__(self, players: range, race: str, catalog: dict[int, UnitInfo]) -> None:
        self.players = set(players)
        self.race = race
        self.catalog = catalog
        self.previous: dict[int, int] = {}
        self.produced: Counter[str] = Counter()
        self.produced_value = 0
        self.lost: Counter[str] = Counter()
        self.lost_value = 0

    def capture(self, observation, record: bool) -> None:
        current: dict[int, int] = {}
        for unit in observation.observation.raw_data.units:
            if unit.owner in self.players:
                current[unit.tag] = unit.unit_type
                if record and unit.tag not in self.previous:
                    unit_kind = kind(unit.unit_type, self.race, self.catalog)
                    if unit_kind in {"army", "structure"}:
                        self.produced[unit_kind] += 1
                        info = self.catalog.get(unit.unit_type, UnitInfo(0.0, 0, 0, False))
                        self.produced_value += info.minerals + info.gas
        if record:
            for tag, unit_type in self.previous.items():
                if tag not in current:
                    unit_kind = kind(unit_type, self.race, self.catalog)
                    if unit_kind in {"army", "structure"}:
                        self.lost[unit_kind] += 1
                        info = self.catalog.get(unit_type, UnitInfo(0.0, 0, 0, False))
                        self.lost_value += info.minerals + info.gas
        self.previous = current

    def snapshot(self, observation) -> dict[str, int | float]:
        values: Counter[str] = Counter()
        army_supply = 0.0
        army_value = 0
        for unit in observation.observation.raw_data.units:
            if unit.owner not in self.players or unit.build_progress < 1.0:
                continue
            unit_kind = kind(unit.unit_type, self.race, self.catalog)
            values[unit_kind] += 1
            info = self.catalog.get(unit.unit_type, UnitInfo(0.0, 0, 0, False))
            if unit_kind == "army":
                army_supply += info.food
                army_value += info.minerals + info.gas
        bases = sum(
            unit.owner in self.players and unit.build_progress >= 1.0 and unit.unit_type in TOWN_HALLS[self.race]
            for unit in observation.observation.raw_data.units
        )
        return {
            "bases": bases,
            "workers": values["worker"],
            "army": values["army"],
            "supply": army_supply,
            "structures": values["structure"],
            "army_value": army_value,
            "produced_army": self.produced["army"],
            "produced_structures": self.produced["structure"],
            "lost_army": self.lost["army"],
            "lost_structures": self.lost["structure"],
            "produced_value": self.produced_value,
            "lost_value": self.lost_value,
        }


def probe_config(left_race: str) -> CustomLauncherConfig:
    slots: list[SlotConfig] = []
    for slot in range(1, 15):
        if slot == 1:
            controller, race, build = "human", left_race, BUILDS[left_race][0]
        elif 2 <= slot <= 7:
            controller, race, build = "custom_ai", left_race, BUILDS[left_race][slot - 2]
        elif 8 <= slot <= 13:
            controller, race, build = "custom_ai", "Zerg", BUILDS["Zerg"][slot - 8]
        else:
            controller, race, build = "empty", "Random", "random_ground"
        slots.append(SlotConfig(slot, controller, 1 if slot <= 7 else 2, race, build))
    return CustomLauncherConfig(
        version=1,
        slots=tuple(slots),
        allow_support_air=True,
        protoss_faction="Aiur",
        wild_zerg=False,
        fullscreen=False,
    )


async def main(left_race: str, minutes: float) -> None:
    config = probe_config(left_race)
    probe_map = PROJECT_ROOT / "runtime" / "maps" / f"combat-{left_race.lower()}-zerg-7v6.SC2Map"
    print(f"COMBAT_7V6_BUILDING left={left_race} right=Zerg wild_zerg={config.wild_zerg}", flush=True)
    build_runtime_map(
        PROJECT_ROOT, BASE_MAP, probe_map, config,
        strategy_bridge=True, campaign_units_pilot=True,
        active_config_file=probe_map.with_suffix(".json"),
    )
    process = launch_sc2(discover_sc2_executable(), PORT, 0)
    connection: Sc2Connection | None = None
    try:
        connection = await Sc2Connection.open(PORT)
        await connection.create_game_with_setups(probe_map.name, probe_map.read_bytes(), player_setups(config), realtime=False)
        await connection.join_game(RACE_VALUES[left_race], f"{left_race} vs Zerg 7v6", None)
        data_request = sc_pb.Request()
        data_request.data.CopyFrom(sc_pb.RequestData(unit_type_id=True))
        game_data = (await connection.request(data_request)).data
        catalog = {
            row.unit_id: UnitInfo(
                row.food_required,
                row.mineral_cost,
                row.vespene_cost,
                8 in row.attributes,  # data_pb.Attribute.Structure
            )
            for row in game_data.units
        }
        controller = StrategyController(connection, config)
        initial = await connection.observation(disable_fog=True)
        controller.initialize(initial)
        left_tracker = TeamTracker(range(1, 8), left_race, catalog)
        zerg_tracker = TeamTracker(range(8, 14), "Zerg", catalog)
        left_tracker.capture(initial, record=False)
        zerg_tracker.capture(initial, record=False)
        print("COMBAT_7V6_RUNNING", flush=True)
        limit = int(minutes * 60 * GAME_LOOPS_PER_SECOND)
        last_report = -60.0
        final_observation = None
        while True:
            await connection.step(224)
            final_observation = await connection.observation(disable_fog=True)
            await controller.update(final_observation)
            left_tracker.capture(final_observation, record=True)
            zerg_tracker.capture(final_observation, record=True)
            elapsed = final_observation.observation.game_loop / GAME_LOOPS_PER_SECOND
            if elapsed >= last_report + 60.0:
                left = left_tracker.snapshot(final_observation)
                zerg = zerg_tracker.snapshot(final_observation)
                print(f"t={elapsed:5.1f}s {left_race}={left} Zerg={zerg}", flush=True)
                last_report = elapsed
            if final_observation.player_result or final_observation.observation.game_loop >= limit:
                break
        assert final_observation is not None
        left = left_tracker.snapshot(final_observation)
        zerg = zerg_tracker.snapshot(final_observation)
        result = [(row.player_id, row.result) for row in final_observation.player_result]
        print(f"COMBAT_7V6_FINAL left={left_race}:{left} zerg:{zerg} player_result={result}")
        print("COMBAT_7V6_TEST=PASS")
    finally:
        if connection is not None:
            await connection.quit()
            await connection.close()
        stop_process(process)


if __name__ == "__main__":
    requested_race = sys.argv[1].capitalize() if len(sys.argv) > 1 else "Terran"
    if requested_race not in {"Terran", "Protoss"}:
        raise SystemExit("첫 인수는 terran 또는 protoss여야 합니다.")
    requested_minutes = float(sys.argv[2]) if len(sys.argv) > 2 else 15.0
    asyncio.run(main(requested_race, requested_minutes))
