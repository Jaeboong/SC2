"""Observe one V3 bootstrap mode through 5, 60, and 300 game seconds.

This is an evidence probe, not a build-order test.  It answers three narrow
questions without inventing observer-unavailable resource assertions:

* Did the generated Galaxy compile and leave all V3 Computer slots with start
  units at 5 seconds?
* Do worker orders remain present at 60 and 300 seconds?
* Relative to the 5-second baseline, did a V3 Computer receive any new,
  non-autonomous unit or structure count?

Zerg Larva is reported separately and is excluded from the last question:
larva growth is autonomous and does not establish production policy.  A
positive delta for every other unit type is conservatively reported as
unsolicited trained/built output; this probe deliberately does not claim the
specific producer or resource state that led to it.

Run one mode at a time on a workstation with SC2 installed:

    python v3/verification/probe_v3_bootstrap_behavior.py \\
        --bootstrap-mode start_town_harvest
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
for extra in (PROJECT_ROOT, PROJECT_ROOT / "v3"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from s2clientprotocol import data_pb2 as data_pb  # noqa: E402
from s2clientprotocol import sc2api_pb2 as sc_pb  # noqa: E402

from sc2team.custom_runtime import player_setups  # noqa: E402
from sc2team.process import (  # noqa: E402
    discover_sc2_executable,
    launch_sc2,
    stop_process,
)
from sc2team.protocol import Sc2Connection  # noqa: E402
from sc2team_v3.config import AI_MODE_BOOTSTRAP, V3BuildConfig  # noqa: E402
from sc2team_v3.runtime import build_v3_map, v3_players  # noqa: E402
from smoke_v3_map import (  # noqa: E402
    BASE_MAP,
    BOOTSTRAP_MODES,
    WORKER_NAMES,
    make_config,
    unit_name_table,
)


GAME_SECONDS = (5, 60, 300)
MODE_PORTS = {
    "marker_only": 14151,
    "start_only": 14152,
    "start_town_harvest": 14153,
}
AUTONOMOUS_TYPES = frozenset({"Larva"})
TOWN_HALL_NAMES = frozenset(
    {
        "CommandCenter",
        "OrbitalCommand",
        "PlanetaryFortress",
        "Nexus",
        "Hatchery",
        "Lair",
        "Hive",
    }
)


@dataclass(frozen=True)
class OwnerSnapshot:
    """Observer-visible state for one runtime owner at one game-time sample."""

    types: Counter[str]
    workers: int
    ordered_workers: int
    worker_order_abilities: Counter[int]
    town_halls: int
    structures: int


@dataclass(frozen=True)
class Snapshot:
    game_seconds: int
    owners: dict[int, OwnerSnapshot]


def probe_map_for(bootstrap_mode: str) -> Path:
    """Keep behavior archives separate from T2 smoke archives for each mode."""

    return (
        PROJECT_ROOT
        / "runtime"
        / "maps"
        / f"v3-bootstrap-behavior-{bootstrap_mode}.SC2Map"
    )


def build_probe_map(bootstrap_mode: str) -> tuple[Path, list[int]]:
    """Build through the V3 public coordinator in observer mode only."""

    config = make_config()
    output_map = probe_map_for(bootstrap_mode)
    output_map.parent.mkdir(parents=True, exist_ok=True)
    runtime_map = build_v3_map(
        PROJECT_ROOT,
        BASE_MAP,
        output_map,
        config,
        V3BuildConfig(ai_mode=AI_MODE_BOOTSTRAP, bootstrap_mode=bootstrap_mode),
        observer_mode=True,
        active_config_file=output_map.with_suffix(".json"),
    )
    # Observer mode makes logical human P1 an actual Computer.  This helper is
    # deliberately used instead of assuming P1..N, so a future fixture cannot
    # accidentally include P15 or an inactive lobby slot in the verdict.
    players = [
        int(entry["runtime"])
        for entry in v3_players(config, observer_mode=True)
    ]
    return runtime_map, players


def observe_snapshot(
    observation: Any,
    names: dict[int, str],
    structure_type_ids: set[int],
    expected_players: list[int],
    game_seconds: int,
) -> Snapshot:
    """Collect only raw-observation facts; resources are not observer assertions."""

    types: dict[int, Counter[str]] = defaultdict(Counter)
    worker_counts: Counter[int] = Counter()
    ordered_worker_counts: Counter[int] = Counter()
    worker_order_abilities: dict[int, Counter[int]] = defaultdict(Counter)
    town_halls: Counter[int] = Counter()
    structures: Counter[int] = Counter()
    target_owners = set(expected_players)

    for unit in observation.observation.raw_data.units:
        if unit.owner not in target_owners:
            continue
        name = names.get(unit.unit_type, str(unit.unit_type))
        types[unit.owner][name] += 1
        if name in WORKER_NAMES:
            worker_counts[unit.owner] += 1
            if unit.orders:
                ordered_worker_counts[unit.owner] += 1
                for order in unit.orders:
                    worker_order_abilities[unit.owner][order.ability_id] += 1
        if name in TOWN_HALL_NAMES:
            town_halls[unit.owner] += 1
        if unit.unit_type in structure_type_ids:
            structures[unit.owner] += 1

    return Snapshot(
        game_seconds=game_seconds,
        owners={
            owner: OwnerSnapshot(
                types=types[owner],
                workers=worker_counts[owner],
                ordered_workers=ordered_worker_counts[owner],
                worker_order_abilities=worker_order_abilities[owner],
                town_halls=town_halls[owner],
                structures=structures[owner],
            )
            for owner in expected_players
        },
    )


async def structure_type_table(connection: Sc2Connection) -> set[int]:
    """Return raw unit-type IDs carrying SC2's Structure attribute."""

    request = sc_pb.Request()
    request.data.CopyFrom(sc_pb.RequestData(unit_type_id=True))
    response = await connection.request(request)
    return {
        unit.unit_id
        for unit in response.data.units
        if data_pb.Structure in unit.attributes
    }


def positive_type_deltas(
    baseline: OwnerSnapshot, current: OwnerSnapshot
) -> tuple[dict[str, int], dict[str, int]]:
    """Return non-autonomous and autonomous positive count changes separately."""

    normal: dict[str, int] = {}
    autonomous: dict[str, int] = {}
    for unit_type in sorted(set(baseline.types) | set(current.types)):
        delta = current.types[unit_type] - baseline.types[unit_type]
        if delta <= 0:
            continue
        destination = autonomous if unit_type in AUTONOMOUS_TYPES else normal
        destination[unit_type] = delta
    return normal, autonomous


def snapshot_delta(baseline: OwnerSnapshot, current: OwnerSnapshot) -> dict[str, object]:
    """Compact, readable changes from 5 seconds without inferring resources."""

    non_autonomous, autonomous = positive_type_deltas(baseline, current)
    return {
        "new_non_autonomous_types": non_autonomous,
        "autonomous_larva_delta": autonomous,
        "workers_delta": current.workers - baseline.workers,
        "ordered_workers_delta": current.ordered_workers - baseline.ordered_workers,
        "town_halls_delta": current.town_halls - baseline.town_halls,
        "structures_delta": current.structures - baseline.structures,
    }


def print_snapshot(snapshot: Snapshot) -> None:
    """Emit per-owner type, worker/order, town-hall, and structure facts."""

    print(f"\n[{snapshot.game_seconds}s]")
    for owner, state in sorted(snapshot.owners.items()):
        print(
            f"  P{owner}: types={dict(sorted(state.types.items()))} "
            f"workers={state.workers} ordered_workers={state.ordered_workers} "
            f"worker_order_ability_ids={dict(sorted(state.worker_order_abilities.items()))} "
            f"town_halls={state.town_halls} structures={state.structures}"
        )


def print_deltas(baseline: Snapshot, current: Snapshot) -> list[str]:
    """Print 5-second deltas and return unsolicited non-autonomous findings."""

    findings: list[str] = []
    print(f"\n[delta 5s->{current.game_seconds}s]")
    for owner in sorted(current.owners):
        delta = snapshot_delta(baseline.owners[owner], current.owners[owner])
        print(f"  P{owner}: {delta}")
        for unit_type, amount in delta["new_non_autonomous_types"].items():
            findings.append(f"{current.game_seconds}s P{owner} {unit_type} +{amount}")
    return findings


def compile_verdict(at_five: Snapshot) -> tuple[bool, list[int]]:
    missing = [owner for owner, state in at_five.owners.items() if not state.types]
    return not missing, missing


def persistent_worker_orders_verdict(
    snapshots: list[Snapshot], expected_players: list[int]
) -> tuple[bool, list[str]]:
    """Require a worker and an active worker order at both post-baseline samples.

    The five-second sample is retained as diagnostic context because startup
    order issuance can race that first observation.  At 60 and 300 seconds an
    orderless owner is a meaningful failure of persistence, while this test
    still avoids assuming which harvesting ability or resource target it is.
    """

    failures: list[str] = []
    for snapshot in snapshots:
        if snapshot.game_seconds == 5:
            continue
        for owner in expected_players:
            state = snapshot.owners[owner]
            if state.workers == 0:
                failures.append(f"{snapshot.game_seconds}s P{owner} has no worker")
            elif state.ordered_workers == 0:
                failures.append(f"{snapshot.game_seconds}s P{owner} has no worker order")
    return not failures, failures


async def run(bootstrap_mode: str) -> int:
    config = make_config()
    runtime_map, expected_players = build_probe_map(bootstrap_mode)
    port = MODE_PORTS[bootstrap_mode]
    print(
        "V3 bootstrap behavior map built: "
        f"{runtime_map} mode={bootstrap_mode} port={port} players={expected_players}"
    )

    process = launch_sc2(discover_sc2_executable(), port, 0)
    connection: Sc2Connection | None = None
    try:
        connection = await Sc2Connection.open(port)
        await connection.create_game_with_setups(
            runtime_map.name,
            runtime_map.read_bytes(),
            player_setups(config, observer=True),
            realtime=False,
        )
        await connection.join_as_observer()
        names = await unit_name_table(connection)
        structure_type_ids = await structure_type_table(connection)

        snapshots: list[Snapshot] = []
        elapsed = 0
        for game_seconds in GAME_SECONDS:
            await connection.step((game_seconds - elapsed) * 16)
            elapsed = game_seconds
            observation = await connection.observation(disable_fog=True)
            snapshot = observe_snapshot(
                observation,
                names,
                structure_type_ids,
                expected_players,
                game_seconds,
            )
            snapshots.append(snapshot)
            print_snapshot(snapshot)

        compile_ok, missing_start_units = compile_verdict(snapshots[0])
        print(
            "V3_BOOTSTRAP_COMPILE="
            + ("PASS" if compile_ok else "FAIL")
            + ("" if compile_ok else f" missing_start_units={missing_start_units}")
        )

        workers_ok, worker_failures = persistent_worker_orders_verdict(
            snapshots, expected_players
        )
        print(
            "V3_BOOTSTRAP_WORKER_ORDERS="
            + ("PASS" if workers_ok else "FAIL")
            + ("" if workers_ok else " " + "; ".join(worker_failures))
        )

        unsolicited: list[str] = []
        for snapshot in snapshots[1:]:
            unsolicited.extend(print_deltas(snapshots[0], snapshot))
        production_ok = not unsolicited
        print(
            "V3_BOOTSTRAP_NO_UNSOLICITED_PRODUCTION="
            + ("PASS" if production_ok else "FAIL")
            + ("" if production_ok else " " + "; ".join(unsolicited))
        )

        passed = compile_ok and workers_ok and production_ok
        print("V3_BOOTSTRAP_BEHAVIOR=" + ("PASS" if passed else "FAIL"))
        return 0 if passed else 1
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
        help="single V3 bootstrap mode to observe",
    )
    return parser.parse_args(argv)


async def main() -> int:
    return await run(parse_args(sys.argv[1:]).bootstrap_mode)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
