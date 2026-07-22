"""P1 참가자(무명령) + 테란 AI 6 vs 프로토스 AI 6 확장 장기 검증.

사용법: .venv\Scripts\python.exe verification\verify_expansion_7v6.py [게임분]
"""

from __future__ import annotations

import asyncio
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sc2team.custom_config import CustomLauncherConfig, SlotConfig
from sc2team.custom_runtime import RACE_VALUES, build_runtime_map, player_setups
from sc2team.process import discover_sc2_executable, launch_sc2, stop_process
from sc2team.protocol import Sc2Connection
from sc2team.strategy_controller import GAME_LOOPS_PER_SECOND, StrategyController


BASE_MAP = PROJECT_ROOT / "maps" / "generated" / "europe-melee-2-7v7-rich-50000-fixed-teams.SC2Map"
PROBE_MAP = PROJECT_ROOT / "runtime" / "maps" / "expansion-7v6-probe.SC2Map"
PORT = 14150
TERRAN_TOWN_HALLS = {18, 130, 132}
PROTOSS_TOWN_HALLS = {59}


def probe_config() -> CustomLauncherConfig:
    slots = []
    for slot in range(1, 15):
        if slot == 1:
            controller, race, build = "human", "Terran", "bio_tank"
        elif 2 <= slot <= 7:
            controller, race, build = "custom_ai", "Terran", "mech_macro"
        elif 8 <= slot <= 13:
            controller, race, build = "custom_ai", "Protoss", "immortal_colossus"
        else:
            controller, race, build = "empty", "Random", "random_ground"
        slots.append(
            SlotConfig(
                slot=slot,
                controller=controller,
                team=1 if slot <= 7 else 2,
                race=race,
                build=build,
            )
        )
    return CustomLauncherConfig(
        version=1,
        slots=tuple(slots),
        allow_support_air=True,
        protoss_faction="Aiur",
        wild_zerg=False,
        fullscreen=False,
    )


def base_counts(observation) -> dict[int, int]:
    counts: Counter[int] = Counter()
    for unit in observation.observation.raw_data.units:
        if unit.build_progress < 1.0:
            continue
        if unit.owner <= 7 and unit.unit_type in TERRAN_TOWN_HALLS:
            counts[unit.owner] += 1
        elif 8 <= unit.owner <= 13 and unit.unit_type in PROTOSS_TOWN_HALLS:
            counts[unit.owner] += 1
    return {player: counts[player] for player in range(1, 14)}


def worker_counts(observation) -> dict[int, int]:
    counts: Counter[int] = Counter()
    for unit in observation.observation.raw_data.units:
        if unit.owner <= 7 and unit.unit_type == 45:  # SCV
            counts[unit.owner] += 1
        elif 8 <= unit.owner <= 13 and unit.unit_type == 84:  # Probe
            counts[unit.owner] += 1
    return {player: counts[player] for player in range(1, 14)}


async def main(minutes: float) -> None:
    config = probe_config()
    print("EXPANSION_7V6_BUILDING", flush=True)
    build_runtime_map(
        PROJECT_ROOT,
        BASE_MAP,
        PROBE_MAP,
        config,
        strategy_bridge=True,
        campaign_units_pilot=True,
        active_config_file=PROBE_MAP.with_suffix(".json"),
    )
    process = launch_sc2(discover_sc2_executable(), PORT, 0)
    connection: Sc2Connection | None = None
    try:
        connection = await Sc2Connection.open(PORT)
        print("EXPANSION_7V6_CREATING_GAME", flush=True)
        await connection.create_game_with_setups(
            PROBE_MAP.name,
            PROBE_MAP.read_bytes(),
            player_setups(config),
            realtime=False,
        )
        await connection.join_game(RACE_VALUES["Terran"], "Expansion 7v6 Probe", None)
        print("EXPANSION_7V6_RUNNING", flush=True)
        controller = StrategyController(connection, config)
        controller.initialize(await connection.observation(disable_fog=True))
        limit = int(minutes * 60 * GAME_LOOPS_PER_SECOND)
        last_report = -30.0
        while True:
            await connection.step(224)  # 게임 시간 10초
            observation = await connection.observation(disable_fog=True)
            await controller.update(observation)
            elapsed = observation.observation.game_loop / GAME_LOOPS_PER_SECOND
            counts = base_counts(observation)
            workers = worker_counts(observation)
            terran = [counts[player] for player in range(2, 8)]
            protoss = [counts[player] for player in range(8, 14)]
            if elapsed >= last_report + 30.0:
                print(
                    f"t={elapsed:5.1f}s terran(P2-P7)={terran} w={[workers[p] for p in range(2, 8)]} "
                    f"protoss(P8-P13)={protoss} w={[workers[p] for p in range(8, 14)]}",
                    flush=True,
                )
                last_report = elapsed
            if observation.player_result or observation.observation.game_loop >= limit:
                break
        terran_max = max(base_counts(observation)[player] for player in range(2, 8))
        protoss_max = max(base_counts(observation)[player] for player in range(8, 14))
        print(f"EXPANSION_7V6_MAX terran={terran_max} protoss={protoss_max}")
        if terran_max < 4 or protoss_max < 4:
            raise RuntimeError("EXPANSION_7V6_TEST=FAIL")
        print("EXPANSION_7V6_TEST=PASS")
    finally:
        if connection is not None:
            await connection.quit()
            await connection.close()
        stop_process(process)


if __name__ == "__main__":
    requested_minutes = float(sys.argv[1]) if len(sys.argv) > 1 else 12.0
    asyncio.run(main(requested_minutes))
