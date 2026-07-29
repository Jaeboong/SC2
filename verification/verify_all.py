#!/usr/bin/env python
"""Deterministic tiered verification harness (verify_all).

This runner exists so verification is reproducible: it drives every tier from
**checked-in fixture configs constructed in code**, never from the mutable
``runtime/custom_ai_settings.json``. See ``docs/verify/verification-guide.md``
for the tier definitions this mirrors.

Tiers
-----
- ``offline``      : unit tests, syntax checks, doc-link integrity, and per-fixture builder
                    structural verification. Fully runnable without SC2.
- ``short-engine`` : the two retained SC2 probes, each fed a disposable
                    fixture path without mutating user settings. Requires SC2.
- ``release-engine``: opens the versioned map with the saved user configuration
                    and validates runtime mapping plus ordinary race starts.
- ``long-engine``  : the five Tier-4 checks that have no retained runners yet.
                    Reported as NOT_IMPLEMENTED until scripts exist under
                    ``tests/engine/probe_<name>.py`` (honest gap, per the docs).

Usage
-----
    .venv\\Scripts\\python.exe verification\\verify_all.py --tier offline
    .venv\\Scripts\\python.exe verification\\verify_all.py --list
    .venv\\Scripts\\python.exe verification\\verify_all.py --emit-fixtures
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sc2team.custom_config import CustomLauncherConfig, SlotConfig

_VENV_PY = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
PYTHON = str(_VENV_PY if _VENV_PY.exists() else sys.executable)
FIXTURE_DIR = PROJECT_ROOT / "tests" / "fixtures"
BASE_MAP = (
    PROJECT_ROOT
    / "map"
    / "source"
    / "europe-melee-2-7v7-rich-50000-fixed-teams.SC2Map"
)
RUNTIME_MAPS = PROJECT_ROOT / "runtime" / "maps"
BUILDER = PROJECT_ROOT / "tools" / "build_custom_runtime_map.cjs"
BUILD_MODULES = PROJECT_ROOT / "tools" / "build"
APP_DIR = Path("app")
VERIFICATION_DIR = Path("verification")


# --------------------------------------------------------------------- fixtures
def _slots(overrides: dict[int, tuple[str, str, str]]) -> tuple[SlotConfig, ...]:
    """Build all 14 ordered slots; entries default to empty west/east teams."""
    out: list[SlotConfig] = []
    for slot_id in range(1, 15):
        controller, race, build = overrides.get(
            slot_id, ("empty", "Random", "random_ground")
        )
        out.append(
            SlotConfig(
                slot=slot_id,
                controller=controller,
                team=1 if slot_id <= 7 else 2,
                race=race,
                build=build,
            )
        )
    return tuple(out)


def _fixture_default_4v4() -> CustomLauncherConfig:
    """Representative race-diverse 4v4 (deterministic; no Random race).

    Same shape as the launcher default (P1 human + P2-4 vs P8-11) but with
    concrete races/builds so the structural build is reproducible.
    """
    return CustomLauncherConfig(
        version=1,
        slots=_slots(
            {
                1: ("human", "Terran", "random_ground"),
                2: ("custom_ai", "Terran", "bio_tank"),
                3: ("custom_ai", "Protoss", "stalker_immortal"),
                4: ("custom_ai", "Zerg", "roach_hydra"),
                8: ("custom_ai", "Terran", "mech_macro"),
                9: ("custom_ai", "Protoss", "immortal_colossus"),
                10: ("custom_ai", "Zerg", "ultra_ling_bane"),
                11: ("custom_ai", "Terran", "thor_tank"),
            }
        ),
    )


def _fixture_terran_mech_probe() -> CustomLauncherConfig:
    """Minimal config with a Terran ally AI and one enemy AI.

    Satisfies both retained engine probes: bridge (needs an enemy AI) and
    runtime (needs a Terran custom AI). §105: 두 프로브 모두 비컨 브리지를
    전제하므로(runtime 프로브는 StrategyController.initialize가 비컨을 찾는다)
    이 픽스처만 유닛 제어 모듈을 켠다 — on 경로의 구조 검증도 겸한다.
    """
    return CustomLauncherConfig(
        version=1,
        slots=_slots(
            {
                1: ("human", "Terran", "random_ground"),
                2: ("custom_ai", "Terran", "mech_macro"),
                8: ("custom_ai", "Zerg", "roach_hydra"),
            }
        ),
        unit_control=True,
    )


def _fixture_supply_800_1v1() -> CustomLauncherConfig:
    """Smallest 1v1 (human vs one Terran AI) for start-unit / supply assertions."""
    return CustomLauncherConfig(
        version=1,
        slots=_slots(
            {
                1: ("human", "Terran", "random_ground"),
                8: ("custom_ai", "Terran", "mech_macro"),
            }
        ),
    )


def _fixture_protoss_faction(faction: str) -> CustomLauncherConfig:
    return CustomLauncherConfig(
        version=1,
        slots=_slots(
            {
                1: ("human", "Protoss", "random_ground"),
                8: ("custom_ai", "Terran", "mech_macro"),
            }
        ),
        protoss_faction=faction,
    )


def _fixture_wild_zerg_off() -> CustomLauncherConfig:
    """§93: 야생 저그 비활성. P15는 중립 적대로 남고 채취만 한다.

    이 픽스처가 지키는 것은 "생산도 안하게" 라는 요구다. verify()가 비활성
    경로에서 MapInfo 승격이 없는지와 생산·건설·습격 심볼이 스크립트에서
    사라졌는지를 함께 검사한다.
    """
    return CustomLauncherConfig(
        version=1,
        slots=_slots(
            {
                1: ("human", "Terran", "random_ground"),
                2: ("custom_ai", "Terran", "bio_tank"),
                8: ("custom_ai", "Protoss", "stalker_immortal"),
            }
        ),
        wild_zerg=False,
    )


FIXTURES: dict[str, Callable[[], CustomLauncherConfig]] = {
    "default_4v4": _fixture_default_4v4,
    "terran_mech_probe": _fixture_terran_mech_probe,
    "supply_800_1v1": _fixture_supply_800_1v1,
    "protoss_aiur": lambda: _fixture_protoss_faction("Aiur"),
    "protoss_nerazim": lambda: _fixture_protoss_faction("Nerazim"),
    "protoss_purifier": lambda: _fixture_protoss_faction("Purifier"),
    "protoss_taldarim": lambda: _fixture_protoss_faction("Taldarim"),
    "wild_zerg_off": _fixture_wild_zerg_off,
}


def build_fixtures() -> dict[str, CustomLauncherConfig]:
    """Construct and validate every fixture (fails loudly on a bad fixture)."""
    configs: dict[str, CustomLauncherConfig] = {}
    for name, factory in FIXTURES.items():
        config = factory()
        config.validate()
        configs[name] = config
    return configs


def emit_fixtures() -> None:
    """Write the checked-in JSON copies under tests/fixtures/."""
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    for name, config in build_fixtures().items():
        path = FIXTURE_DIR / f"{name}.json"
        path.write_text(
            json.dumps(config.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"  wrote {path.relative_to(PROJECT_ROOT)}")


# ---------------------------------------------------------------------- results
@dataclass
class Result:
    name: str
    status: str  # PASS | FAIL | SKIP | NOT_IMPLEMENTED
    detail: str = ""


@dataclass
class TierReport:
    tier: str
    results: list[Result] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        return any(r.status == "FAIL" for r in self.results)


def _run(cmd: list[str], label: str) -> Result:
    try:
        proc = subprocess.run(
            cmd,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError as exc:
        return Result(label, "FAIL", f"command not found: {exc}")
    if proc.returncode == 0:
        return Result(label, "PASS")
    tail = (proc.stderr or proc.stdout).strip().splitlines()[-6:]
    return Result(label, "FAIL", "\n".join(tail))


# ------------------------------------------------------------------ offline tier
def _node_syntax_check() -> Result:
    """빌더 진입점과 tools/build/*.cjs 모듈 전부의 구문을 검사한다.

    `node --check`는 인자를 하나만 본다 — 파일 목록을 넘기면 두 번째부터는
    조용히 무시되고, 깨진 모듈이 있어도 PASS가 나온다. 그래서 파일마다
    따로 실행한다.
    """
    sources = [BUILDER, *sorted(BUILD_MODULES.glob("*.cjs"))]
    failures: list[str] = []
    for source in sources:
        result = _run(["node", "--check", str(source)], "node_syntax")
        if result.status == "FAIL":
            failures.append(f"{source.name}: {result.detail.splitlines()[0]}")
    if failures:
        return Result("offline/node_syntax", "FAIL", "\n".join(failures))
    return Result("offline/node_syntax", "PASS")


def _fixture_structural_builds() -> list[Result]:
    results: list[Result] = []
    try:
        from sc2team.custom_runtime import build_runtime_map, load_stock_targets
    except Exception as exc:  # import must not crash the whole run
        return [Result("offline/structural_build", "FAIL", f"import failed: {exc}")]
    if not BASE_MAP.is_file():
        return [
            Result(
                "offline/structural_build",
                "SKIP",
                f"base map missing: {BASE_MAP.name}",
            )
        ]
    RUNTIME_MAPS.mkdir(parents=True, exist_ok=True)
    for name, config in build_fixtures().items():
        label = f"offline/structural_build[{name}]"
        out = RUNTIME_MAPS / f"verify-all-{name}.SC2Map"
        try:
            build_runtime_map(
                PROJECT_ROOT,
                BASE_MAP,
                out,
                config,
                strategy_bridge=True,
                campaign_units_pilot=True,
                active_config_file=out.with_suffix(".json"),
            )
            # 목표 재고 사이드카: 모든 custom_ai 슬롯이 있고, random_ground 이외의
            # 빌드는 비어 있지 않은 재고 표를 실어야 한다.
            entries = {
                entry["logical_slot"]: entry for entry in load_stock_targets(out)
            }
            for slot in config.custom_ai_slots:
                entry = entries.get(slot.slot)
                if entry is None:
                    raise RuntimeError(f"사이드카에 P{slot.slot} 항목이 없습니다")
                if slot.build != "random_ground" and not entry["stock"]:
                    raise RuntimeError(
                        f"P{slot.slot} ({slot.build}) 재고 표가 비어 있습니다"
                    )
            results.append(Result(label, "PASS"))
        except Exception as exc:
            last = str(exc).strip().splitlines()[-1] if str(exc).strip() else repr(exc)
            results.append(Result(label, "FAIL", last))
    return results


def offline_tier() -> TierReport:
    report = TierReport("offline")
    report.results.append(
        _run([PYTHON, "-m", "unittest", "discover", "-s", "tests"], "offline/unit_tests")
    )
    report.results.append(
        _run(
            [PYTHON, "-m", "unittest", "tests/test_worker_supply_proxy.py"],
            "offline/worker_supply_tests",
        )
    )
    report.results.append(_node_syntax_check())
    report.results.append(
        _run(
            [
                PYTHON,
                "-m",
                "py_compile",
                str(APP_DIR / "play_custom_ai.py"),
                str(VERIFICATION_DIR / "verify_strategy_runtime.py"),
                str(VERIFICATION_DIR / "verify_strategy_bridge.py"),
                str(VERIFICATION_DIR / "verify_campaign_dependency.py"),
                str(VERIFICATION_DIR / "verify_torrasque_pilot.py"),
                str(VERIFICATION_DIR / "verify_torrasque_ai_production.py"),
                str(VERIFICATION_DIR / "verify_campaign_roster.py"),
                str(VERIFICATION_DIR / "verify_campaign_ai_production.py"),
                str(VERIFICATION_DIR / "verify_campaign_combat.py"),
                str(VERIFICATION_DIR / "verify_protoss_factions.py"),
                str(VERIFICATION_DIR / "verify_release_map.py"),
                str(VERIFICATION_DIR / "verify_all.py"),
                str(Path("sc2team") / "custom_runtime.py"),
                str(Path("sc2team") / "strategy_controller.py"),
            ],
            "offline/py_compile",
        )
    )
    report.results.append(
        _run(
            [PYTHON, str(VERIFICATION_DIR / "check_doc_links.py")],
            "offline/doc_links",
        )
    )
    report.results.extend(_fixture_structural_builds())
    return report


# ------------------------------------------------------------- short engine tier
def _with_fixture_settings(fixture: str, body: Callable[[], Result]) -> Result:
    """Run a probe against a disposable settings path, never user state."""
    config = build_fixtures()[fixture]
    fixture_path = PROJECT_ROOT / "runtime" / f"verify-all-{fixture}-settings.json"
    fixture_path.parent.mkdir(parents=True, exist_ok=True)
    fixture_path.write_text(
        json.dumps(config.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    old_path = os.environ.get("SC2TEAM_SETTINGS_FILE")
    os.environ["SC2TEAM_SETTINGS_FILE"] = str(fixture_path)
    try:
        return body()
    finally:
        if old_path is None:
            os.environ.pop("SC2TEAM_SETTINGS_FILE", None)
        else:
            os.environ["SC2TEAM_SETTINGS_FILE"] = old_path
        fixture_path.unlink(missing_ok=True)


def _run_probe(script: str, marker: str, label: str) -> Result:
    proc = subprocess.run(
        [PYTHON, "-u", script],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    # SC2's child process can disappear from tasklist slightly before the
    # singleton/client resources are ready for the next launch.  Consecutive
    # engine probes otherwise fail intermittently while opening their API port.
    deadline = time.monotonic() + 10.0
    while _sc2_running() and time.monotonic() < deadline:
        time.sleep(0.25)
    time.sleep(1.5)
    if marker in (proc.stdout or ""):
        return Result(label, "PASS")
    tail = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip().splitlines()[-8:]
    return Result(label, "FAIL", "\n".join(tail))


def short_engine_tier() -> TierReport:
    report = TierReport("short-engine")
    if _sc2_running():
        report.results.append(
            Result(
                "short-engine/precondition",
                "FAIL",
                "SC2/Editor process is running; free the fixed API ports first.",
            )
        )
        return report
    report.results.append(
        _with_fixture_settings(
            "terran_mech_probe",
            lambda: _run_probe(
                str(VERIFICATION_DIR / "verify_strategy_bridge.py"),
                # 프로브의 마지막 출력 — 일꾼 명령 검증과 opcode 11 검증을 모두
                # 통과해야만 찍힌다.
                "GALAXY_TARGETED_ATTACK_TEST=PASS",
                "short-engine/bridge_probe",
            ),
        )
    )
    report.results.append(
        _with_fixture_settings(
            "terran_mech_probe",
            lambda: _run_probe(
                str(VERIFICATION_DIR / "verify_strategy_runtime.py"),
                "STRATEGY_RUNTIME_TEST=PASS",
                "short-engine/strategy_runtime",
            ),
        )
    )
    return report


# ----------------------------------------------------------- release engine tier
def release_engine_tier() -> TierReport:
    report = TierReport("release-engine")
    if _sc2_running():
        report.results.append(
            Result(
                "release-engine/precondition",
                "FAIL",
                "SC2/Editor process is running; free API port 14126 first.",
            )
        )
        return report
    report.results.append(
        _run_probe(
            str(VERIFICATION_DIR / "verify_release_map.py"),
            "RELEASE_ENGINE_SMOKE=PASS",
            "release-engine/versioned_map",
        )
    )
    return report


# -------------------------------------------------------------- long engine tier
# The five Tier-4 checks documented in docs/verify/engine-tests.md that passed
# during development but were never retained as runners. A future runner should
# live at tests/engine/probe_<name>.py and print "<NAME>=PASS".
LONG_ENGINE_CHECKS: tuple[str, ...] = (
    "supply_800_and_normal_start",
    "fast_first_expansion",
    "adaptive_multi_expansion",
    "ground_composition_cap",
    "ally_support_matrix",
)


def long_engine_tier() -> TierReport:
    report = TierReport("long-engine")
    for name in LONG_ENGINE_CHECKS:
        script = PROJECT_ROOT / "tests" / "engine" / f"probe_{name}.py"
        label = f"long-engine/{name}"
        if script.is_file():
            if _sc2_running():
                report.results.append(
                    Result(label, "FAIL", "SC2/Editor running; free the API ports.")
                )
                continue
            report.results.append(
                _run_probe(str(script), f"{name.upper()}=PASS", label)
            )
        else:
            report.results.append(
                Result(
                    label,
                    "NOT_IMPLEMENTED",
                    "no retained runner; see docs/verify/engine-tests.md",
                )
            )
    return report


# ----------------------------------------------------------------------- shared
def _sc2_running() -> bool:
    try:
        proc = subprocess.run(
            ["tasklist"], capture_output=True, text=True, errors="replace"
        )
    except Exception:
        return False
    names = (proc.stdout or "").lower()
    return any(
        exe in names
        for exe in ("sc2_x64.exe", "sc2.exe", "sc2switcher.exe", "sc2editor.exe")
    )


def print_report(report: TierReport) -> None:
    icon = {"PASS": "OK ", "FAIL": "XX ", "SKIP": "-- ", "NOT_IMPLEMENTED": "?? "}
    print(f"\n=== tier: {report.tier} ===")
    for result in report.results:
        print(f"  [{icon.get(result.status, '?? ')}] {result.name}  {result.status}")
        if result.detail and result.status in ("FAIL", "SKIP"):
            for line in result.detail.splitlines():
                print(f"        {line}")


TIERS: dict[str, Callable[[], TierReport]] = {
    "offline": offline_tier,
    "short-engine": short_engine_tier,
    "release-engine": release_engine_tier,
    "long-engine": long_engine_tier,
}


def run_tiers(selected: list[str]) -> int:
    reports = [TIERS[name]() for name in selected]
    for report in reports:
        print_report(report)
    total = sum(len(r.results) for r in reports)
    failed = sum(1 for r in reports for x in r.results if x.status == "FAIL")
    pending = sum(
        1 for r in reports for x in r.results if x.status == "NOT_IMPLEMENTED"
    )
    label = "+".join(selected)
    verdict = "PASS" if failed == 0 else "FAIL"
    print(
        f"\nVERIFY_ALL[{label}]={verdict} "
        f"({total} checks, {failed} failed, {pending} not-implemented)"
    )
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Deterministic tiered verify harness")
    parser.add_argument(
        "--tier",
        choices=[*TIERS, "all"],
        default="offline",
        help="tier to run (default: offline)",
    )
    parser.add_argument(
        "--emit-fixtures",
        action="store_true",
        help="write checked-in fixture JSON under tests/fixtures/ and exit",
    )
    parser.add_argument(
        "--list", action="store_true", help="list fixtures and checks, then exit"
    )
    args = parser.parse_args()

    if args.emit_fixtures:
        print("Emitting fixtures:")
        emit_fixtures()
        return 0

    if args.list:
        print("Fixtures (constructed in code, checked in under tests/fixtures/):")
        for name, config in build_fixtures().items():
            active = len(config.active_slots)
            print(f"  {name}: {active} active slots, human at P{config.human.slot}")
        print("\nTiers:")
        print("  offline      : unit_tests, worker_supply_tests, node_syntax, "
              "py_compile, doc_links, structural_build[per fixture]")
        print("  short-engine : bridge_probe, strategy_runtime (needs SC2)")
        print("  release-engine: versioned_map saved-config start smoke (needs SC2)")
        print("  long-engine  : " + ", ".join(LONG_ENGINE_CHECKS) + " (Tier-4)")
        return 0

    selected = list(TIERS) if args.tier == "all" else [args.tier]
    return run_tiers(selected)


if __name__ == "__main__":
    raise SystemExit(main())
