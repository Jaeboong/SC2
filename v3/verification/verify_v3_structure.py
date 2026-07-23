"""Verify the formal V3 upstream + overlay source layout against 03:47 metadata."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
AI_ROOT = PROJECT_ROOT / "v3" / "ai"
UPSTREAM_ROOT = AI_ROOT / "upstream"
OVERLAY_ROOT = AI_ROOT / "overlay"
MANIFEST_PATH = AI_ROOT / "manifest.json"
OVERLAY_MANIFEST_PATH = AI_ROOT / "overlay-manifest.json"
BUILDER = PROJECT_ROOT / "v3" / "tools" / "build_v3_ai_mod.cjs"
LAYOUT = PROJECT_ROOT / "v3" / "tools" / "v3_ai_layout.cjs"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def checked_file(path: Path, expected_bytes: int, expected_hash: str) -> str | None:
    if not path.is_file():
        return f"missing: {path.relative_to(PROJECT_ROOT)}"
    data = path.read_bytes()
    if len(data) != expected_bytes:
        return f"size differs: {path.relative_to(PROJECT_ROOT)} expected={expected_bytes} actual={len(data)}"
    if sha256(data) != expected_hash:
        return f"hash differs: {path.relative_to(PROJECT_ROOT)}"
    return None


def main() -> int:
    failures: list[str] = []
    manifest_bytes = MANIFEST_PATH.read_bytes() if MANIFEST_PATH.is_file() else b""
    overlay_manifest_bytes = OVERLAY_MANIFEST_PATH.read_bytes() if OVERLAY_MANIFEST_PATH.is_file() else b""
    if not manifest_bytes:
        failures.append("missing: v3/ai/manifest.json")
    if not overlay_manifest_bytes:
        failures.append("missing: v3/ai/overlay-manifest.json")
    if failures:
        print("V3_STRUCTURE=FAIL")
        print(*[f"- {failure}" for failure in failures], sep="\n")
        return 1

    manifest = json.loads(manifest_bytes)
    overlay_manifest = json.loads(overlay_manifest_bytes)
    if len(manifest["files"]) != 54:
        failures.append(f"upstream manifest must contain 54 files, found {len(manifest['files'])}")
    if len(overlay_manifest["overlays"]) != 10:
        failures.append(f"overlay manifest must contain 10 files, found {len(overlay_manifest['overlays'])}")
    if sha256(manifest_bytes) != overlay_manifest["upstream_manifest_sha256"]:
        failures.append("overlay manifest does not authenticate manifest.json")

    roots = {
        "Base.SC2Data/TriggerLibs/Terran/Terran.galaxy": "Terran",
        "Base.SC2Data/TriggerLibs/Protoss/Protoss.galaxy": "Protoss",
        "Base.SC2Data/TriggerLibs/Zerg/Zerg.galaxy": "Zerg",
    }
    for entry in manifest["files"]:
        relative = Path(entry["vendored_path"]).relative_to("upstream")
        error = checked_file(UPSTREAM_ROOT / relative, entry["bytes"], entry["sha256"])
        if error:
            failures.append(error)
            continue
        race = roots.get(entry["virtual_path"])
        if race:
            root_text = (UPSTREAM_ROOT / relative).read_text(encoding="utf-8")
            if f'include "TriggerLibs/V3/{race}"' in root_text or f"V3Run{race}Build" in root_text:
                failures.append(f"permanent V3 hook remains in upstream {race} root")

    for entry in overlay_manifest["overlays"]:
        error = checked_file(OVERLAY_ROOT / Path(entry["source_path"]).relative_to("overlay"), entry["bytes"], entry["sha256"])
        if error:
            failures.append(error)

    builder_source = BUILDER.read_text(encoding="utf-8") if BUILDER.is_file() else ""
    for required in ("upstreamRoot", "overlay-manifest.json", "injectV3Hooks", "generated_roots=3"):
        if required not in builder_source:
            failures.append(f"formal builder contract missing: {required}")
    if "snapshot" in builder_source:
        failures.append("snapshot dependency remains in formal builder")

    for source in (BUILDER, LAYOUT):
        result = subprocess.run(["node", "--check", str(source)], cwd=PROJECT_ROOT, capture_output=True, text=True)
        if result.returncode:
            failures.append(f"Node syntax failed for {source.name}: {(result.stderr or result.stdout).strip()}")

    layout_source = LAYOUT.read_text(encoding="utf-8") if LAYOUT.is_file() else ""
    if "player == 15 && AIGetUserInt(player, 145) == 0" not in layout_source:
        failures.append("Zerg root is missing the P15 pre-420 AI entry guard")

    # The six policies must use the race-local wrappers that in turn call the
    # native town stock API.  A bare AISetStockExpand is intentionally not
    # sufficient: it only creates a town and cannot place production there.
    town_helpers = {
        "Terran.galaxy": "V3SetTerranTownProduction",
        "Protoss.galaxy": "V3SetProtossTownProduction",
        "Zerg.galaxy": "V3SetZergMainMacroHatcheries",
    }
    for filename, helper in town_helpers.items():
        text = (OVERLAY_ROOT / "Base.SC2Data" / "TriggerLibs" / "V3" / filename).read_text(encoding="utf-8")
        for required in (helper, "AISetStockEx", "AIGetTownState", "c_townStateEstablished"):
            if required not in text:
                failures.append(f"town-local helper missing {required}: {filename}")

    policy_helpers = {
        "TerranBionic.galaxy": "V3SetTerranTownProduction",
        "TerranMechanic.galaxy": "V3SetTerranTownProduction",
        "ProtossGateway.galaxy": "V3SetProtossTownProduction",
        "ProtossGatewayRobo.galaxy": "V3SetProtossTownProduction",
        "ZergRoachHydraUltra.galaxy": "V3SetZergMainMacroHatcheries",
        "ZergLingBaneUltra.galaxy": "V3SetZergMainMacroHatcheries",
    }
    v3_root = OVERLAY_ROOT / "Base.SC2Data" / "TriggerLibs" / "V3"
    for filename, helper in policy_helpers.items():
        if helper not in (v3_root / filename).read_text(encoding="utf-8"):
            failures.append(f"policy has no town-local production path: {filename}")

    gas_policy = v3_root / "ExpansionGas.galaxy"
    if not gas_policy.is_file():
        failures.append("missing shared expansion gas policy")
    else:
        gas_text = gas_policy.read_text(encoding="utf-8")
        for required in (
            "V3SetExpansionGasPolicy",
            "AIGetRawGasNumSpots",
            "AIGetHarvestableGasNumSpots",
            "AISetStockEx(player, town, rawGas, gasType, c_makeDefault, 0)",
            "AISetGasPeonCountOverride(player, town, harvestableGas * 3)",
            "V3MiningWorkerCapacity",
            "capacity = capacity + (mineralSpots * 2) + (gasSpots * 3)",
            "V3WorkerTarget",
            "V3EnsureMiningExpansion",
            "established < maximumTowns",
            "currentWorkers >= requiredWorkers",
            "AIExpand(player, AIGetTownLocation(player, c_townMain), expandType)",
        ):
            if required not in gas_text:
                failures.append(f"expansion economy policy missing {required}")
    for filename in ("Terran.galaxy", "Protoss.galaxy", "Zerg.galaxy"):
        text = (v3_root / filename).read_text(encoding="utf-8")
        for required in (
            'include "TriggerLibs/V3/ExpansionGas"',
            "V3SetExpansionGasPolicy",
            "V3EnsureMiningExpansion",
        ):
            if required not in text:
                failures.append(f"race runner has no expansion economy policy {required}: {filename}")

    worker_types = ("c_TU_SCV", "c_PU_Probe", "c_ZU_Drone")
    for filename in policy_helpers:
        text = (v3_root / filename).read_text(encoding="utf-8")
        if "AISetStockExpand(" in text or "AIDefaultExpansion(" in text:
            failures.append(f"policy retains time/stock-driven expansion target: {filename}")
        # The Ling/Bane/Ultra overlay is a literal upstream-state-machine
        # derivative: each copied upstream routine owns one complete stock
        # list and therefore enables it internally.  V3RunZergBuild returns
        # immediately for build 302, so no shared V3 stock is appended.
        if filename != "ZergLingBaneUltra.galaxy" and "AIEnableStock(player)" in text:
            failures.append(f"policy enables stock before shared economy targets: {filename}")
        for line in text.splitlines():
            if ("AISetStock(" in line or "AISetStockPeons(" in line) and any(
                worker in line for worker in worker_types
            ) and "V3WorkerTarget(player," not in line:
                failures.append(f"worker target bypasses live town capacity: {filename}: {line.strip()}")

    forbidden = ("AITrain(", "AIResearch(")
    for source in v3_root.glob("*.galaxy"):
        text = source.read_text(encoding="utf-8")
        for call in forbidden:
            if call in text:
                failures.append(f"forbidden forced production call {call}: {source.name}")

    if failures:
        print("V3_STRUCTURE=FAIL")
        print(*[f"- {failure}" for failure in failures], sep="\n")
        return 1
    print(
        "V3_STRUCTURE=PASS upstream=54 overlays=10 roots=3 "
        f"manifest={sha256(manifest_bytes)} snapshot_present={(AI_ROOT / 'snapshot').exists()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
