// Restore the formal V3 source tree from the immutable 03:47 MPQ baseline.
"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { Archive } = require("../../tools/node_modules/@jamiephan/stormlib");
const { RACES, fail, removeV3Hooks, sha256 } = require("./v3_ai_layout.cjs");

const projectRoot = path.resolve(__dirname, "..", "..");
const archivePath = path.join(projectRoot, "runtime", "v3-opening-static-check", "SC2TeamV3AI.SC2Mod");
const aiRoot = path.join(projectRoot, "v3", "ai");

function archivePathFor(virtualPath) {
  return virtualPath.split("/").join("\\");
}

function writeExact(destination, data) {
  fs.mkdirSync(path.dirname(destination), { recursive: true });
  fs.writeFileSync(destination, data);
}

function main() {
  if (!fs.existsSync(archivePath)) fail(`03:47 archive is missing: ${archivePath}`);
  const archive = Archive.open(archivePath);
  try {
    const upstreamManifestBytes = archive.readFile("SC2TeamV3AI.manifest.json");
    const overlayManifestBytes = archive.readFile("SC2TeamV3AI.overlay-manifest.json");
    const upstreamManifest = JSON.parse(upstreamManifestBytes.toString("utf8"));
    const overlayManifest = JSON.parse(overlayManifestBytes.toString("utf8"));
    if (upstreamManifest.files.length !== 54) fail(`expected 54 upstream files, found ${upstreamManifest.files.length}`);
    if (overlayManifest.overlays.length !== 9) fail(`expected 9 overlays, found ${overlayManifest.overlays.length}`);
    if (sha256(upstreamManifestBytes) !== overlayManifest.upstream_manifest_sha256) {
      fail("archive manifests do not agree on the upstream manifest hash");
    }

    for (const entry of upstreamManifest.files) {
      const archived = archive.readFile(archivePathFor(entry.virtual_path));
      let restored = archived;
      const race = Object.entries(RACES).find(([, value]) => value.root === entry.virtual_path)?.[0];
      if (race) restored = Buffer.from(removeV3Hooks(archived.toString("utf8"), race), "utf8");
      if (restored.length !== entry.bytes || sha256(restored) !== entry.sha256) {
        fail(`upstream hash mismatch after restoration: ${entry.virtual_path}`);
      }
      writeExact(path.join(aiRoot, "upstream", entry.vendored_path.replace(/^upstream\//, "")), restored);
    }

    for (const entry of overlayManifest.overlays) {
      const local = path.join(aiRoot, entry.source_path);
      if (!fs.existsSync(local)) fail(`formal overlay is missing: ${entry.source_path}`);
      const data = fs.readFileSync(local);
      if (data.length !== entry.bytes || sha256(data) !== entry.sha256) fail(`formal overlay differs from archive: ${entry.source_path}`);
    }
    writeExact(path.join(aiRoot, "manifest.json"), upstreamManifestBytes);
    writeExact(path.join(aiRoot, "overlay-manifest.json"), overlayManifestBytes);
    console.log(`V3_BASELINE_RESTORE=PASS upstream=54 overlays=9 manifest=${sha256(upstreamManifestBytes)}`);
  } finally {
    archive.close();
  }
}

main();
