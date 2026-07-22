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
    if len(overlay_manifest["overlays"]) != 9:
        failures.append(f"overlay manifest must contain 9 files, found {len(overlay_manifest['overlays'])}")
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

    if failures:
        print("V3_STRUCTURE=FAIL")
        print(*[f"- {failure}" for failure in failures], sep="\n")
        return 1
    print(
        "V3_STRUCTURE=PASS upstream=54 overlays=9 roots=3 "
        f"manifest={sha256(manifest_bytes)} snapshot_present={(AI_ROOT / 'snapshot').exists()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
