"""T2 V3 compile/startup smoke; run manually on a workstation with SC2 installed.

This is intentionally a two-part result:

* ``V3_COMPILE_BOOT=PASS`` means the generated Galaxy compiled far enough for
  normal map start units to exist at game-time 5 seconds.
* ``V3_ECONOMY_SIGNAL=PASS`` means the V3 computer slots still have workers and
  at least one worker has an engine order at game-time 30 seconds.

Neither assertion expects default melee production, an attack wave, a custom
unit, or any policy decision.  Those belong to later V3 probes.

    python v3/verification/smoke_v3_map.py
"""

from __future__ import annotations

import asyncio
import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
for extra in (PROJECT_ROOT, PROJECT_ROOT / "v3"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from s2clientprotocol import sc2api_pb2 as sc_pb  # noqa: E402

from sc2team.custom_config import CustomLauncherConfig, SlotConfig  # noqa: E402
from sc2team.custom_runtime import player_setups  # noqa: E402
from sc2team.process import (  # noqa: E402
    discover_sc2_executable,
    launch_sc2,
    stop_process,
)
from sc2team.protocol import Sc2Connection  # noqa: E402


BASE_MAP = (
    PROJECT_ROOT
    / "map"
    / "source"
    / "europe-melee-2-7v7-rich-50000-fixed-teams.SC2Map"
)
# Kept distinct from V1/V2 verification ports.  Do not share it with a launcher.
PORT = 14141
WORKER_NAMES = frozenset({"SCV", "Probe", "Drone"})
BOOTSTRAP_MODES = ("marker_only", "start_only", "start_town_harvest")


def make_config() -> CustomLauncherConfig:
    """Small mixed-race fixture; P15 remains outside V3 Phase-1 scope."""

    layout = {
        1: ("human", "Terran"),
        2: ("custom_ai", "Terran"),
        3: ("custom_ai", "Protoss"),
        9: ("custom_ai", "Zerg"),
    }
    slots = []
    for slot in range(1, 15):
        controller, race = layout.get(slot, ("empty", "Random"))
        slots.append(
            SlotConfig(
                slot=slot,
                controller=controller,
                team=1 if slot <= 7 else 2,
                race=race,
                build="random_ground",
            )
        )
    config = CustomLauncherConfig(version=1, slots=tuple(slots), wild_zerg=False)
    config.validate()
    return config


def probe_map_for(bootstrap_mode: str) -> Path:
    """Keep each bootstrap experiment's archive and sidecar as evidence."""

    return PROJECT_ROOT / "runtime" / "maps" / f"v3-smoke-{bootstrap_mode}.SC2Map"


def build_probe_map(config: CustomLauncherConfig, bootstrap_mode: str) -> Path:
    """Build through the V3 public runtime API, never via V1/V2 patchers."""

    try:
        from sc2team_v3.config import AI_MODE_BOOTSTRAP, V3BuildConfig
        from sc2team_v3.runtime import build_v3_map
    except ImportError as error:  # pragma: no cover - V3 runtime lands separately.
        raise RuntimeError(
            "V3 runtime is unavailable. Expected sc2team_v3.runtime.build_v3_map "
            "and sc2team_v3.config.V3BuildConfig; "
            "build Phase 1 before running this smoke."
        ) from error

    probe_map = probe_map_for(bootstrap_mode)
    probe_map.parent.mkdir(parents=True, exist_ok=True)
    return build_v3_map(
        PROJECT_ROOT,
        BASE_MAP,
        probe_map,
        config,
        V3BuildConfig(ai_mode=AI_MODE_BOOTSTRAP, bootstrap_mode=bootstrap_mode),
        observer_mode=True,
        active_config_file=probe_map.with_suffix(".json"),
    )


async def unit_name_table(connection: Sc2Connection) -> dict[int, str]:
    request = sc_pb.Request()
    request.data.CopyFrom(sc_pb.RequestData(unit_type_id=True))
    return {unit.unit_id: unit.name for unit in (await connection.request(request)).data.units}


def observed_owners(observation) -> Counter[int]:
    owners: Counter[int] = Counter()
    for unit in observation.observation.raw_data.units:
        if 1 <= unit.owner <= 14:
            owners[unit.owner] += 1
    return owners


def unit_names_by_owner(observation, names: dict[int, str]) -> dict[int, dict[str, int]]:
    """Detailed failure context; it is not a build-order assertion."""

    by_owner: dict[int, Counter[str]] = defaultdict(Counter)
    for unit in observation.observation.raw_data.units:
        if 1 <= unit.owner <= 14:
            by_owner[unit.owner][names.get(unit.unit_type, str(unit.unit_type))] += 1
    return {
        owner: dict(sorted(counts.items()))
        for owner, counts in sorted(by_owner.items())
    }


def worker_order_counts(observation, names: dict[int, str]) -> tuple[Counter[int], Counter[int]]:
    workers: Counter[int] = Counter()
    ordered_workers: Counter[int] = Counter()
    for unit in observation.observation.raw_data.units:
        if not 1 <= unit.owner <= 14:
            continue
        if names.get(unit.unit_type) not in WORKER_NAMES:
            continue
        workers[unit.owner] += 1
        if unit.orders:
            ordered_workers[unit.owner] += 1
    return workers, ordered_workers


async def run(bootstrap_mode: str) -> int:
    config = make_config()
    runtime_map = build_probe_map(config, bootstrap_mode)
    expected_runtime_players = tuple(range(1, len(player_setups(config, observer=True))))
    print(f"V3 smoke map built: {runtime_map} bootstrap_mode={bootstrap_mode}")
    print(f"V3 observer runtime players: {expected_runtime_players}")

    process = launch_sc2(discover_sc2_executable(), PORT, 0)
    connection: Sc2Connection | None = None
    try:
        connection = await Sc2Connection.open(PORT)
        await connection.create_game_with_setups(
            runtime_map.name,
            runtime_map.read_bytes(),
            player_setups(config, observer=True),
            realtime=False,
        )
        await connection.join_as_observer()
        names = await unit_name_table(connection)

        # Game-time uses 16 loops per second.  This is a compile/startup signal,
        # not evidence that any V3 policy produced a unit.
        await connection.step(5 * 16)
        at_five = await connection.observation(disable_fog=True)
        owners_at_five = observed_owners(at_five)
        print(f"[5s] units_by_owner={dict(sorted(owners_at_five.items()))}")
        missing = [player for player in expected_runtime_players if owners_at_five[player] == 0]
        if missing:
            print(f"V3_COMPILE_BOOT=FAIL missing_start_units={missing}")
            print(f"[5s] unit_names_by_owner={unit_names_by_owner(at_five, names)}")
            return 1
        print("V3_COMPILE_BOOT=PASS")

        # Do not assert a particular build order or new-unit count.  We only
        # require the minimum economy liveness signal that Phase 2 will refine.
        await connection.step(25 * 16)
        at_thirty = await connection.observation(disable_fog=True)
        workers, ordered_workers = worker_order_counts(at_thirty, names)
        print(
            "[30s] workers=" + str(dict(sorted(workers.items()))) +
            " ordered_workers=" + str(dict(sorted(ordered_workers.items())))
        )
        missing_workers = [player for player in expected_runtime_players if workers[player] == 0]
        no_economy_order = [
            player for player in expected_runtime_players if ordered_workers[player] == 0
        ]
        if missing_workers or no_economy_order:
            print(
                "V3_ECONOMY_SIGNAL=FAIL "
                f"missing_workers={missing_workers} no_worker_order={no_economy_order}"
            )
            return 1
        print("V3_ECONOMY_SIGNAL=PASS")
        return 0
    finally:
        if connection is not None:
            try:
                await connection.quit()
            except Exception:
                pass
            try:
                await connection.close()
            except Exception:
                pass
        stop_process(process)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bootstrap-mode",
        choices=BOOTSTRAP_MODES,
        default="start_town_harvest",
        help="V3 bootstrap experiment (default: start_town_harvest)",
    )
    return parser.parse_args(argv)


async def main() -> int:
    return await run(parse_args(sys.argv[1:]).bootstrap_mode)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
