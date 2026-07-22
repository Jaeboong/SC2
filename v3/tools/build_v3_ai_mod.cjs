// Build a V3 AI mod from the formal upstream + overlay layout.
"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { Archive } = require("../../tools/node_modules/@jamiephan/stormlib");
const { RACES, fail, injectV3Hooks, sha256 } = require("./v3_ai_layout.cjs");

const [outputPath, planPath] = process.argv.slice(2);
const aiRoot = path.join(__dirname, "..", "ai");
const upstreamRoot = path.join(aiRoot, "upstream");

function readJson(relativePath) {
  return JSON.parse(fs.readFileSync(path.join(aiRoot, relativePath), "utf8"));
}

function readVerified(relativePath, expectedBytes, expectedHash) {
  const data = fs.readFileSync(path.join(aiRoot, relativePath));
  if (data.length !== expectedBytes || sha256(data) !== expectedHash) {
    fail(`source verification failed: ${relativePath}`);
  }
  return data;
}

function archivePathFor(virtualPath) {
  return virtualPath.split("/").join("\\");
}

if (!outputPath || !planPath || process.argv.length !== 4) {
  fail("usage: node build_v3_ai_mod.cjs <output.SC2Mod> <v3-plan.json>");
}
JSON.parse(fs.readFileSync(planPath, "utf8"));

const manifestBytes = fs.readFileSync(path.join(aiRoot, "manifest.json"));
const manifest = JSON.parse(manifestBytes.toString("utf8"));
const overlayManifestBytes = fs.readFileSync(path.join(aiRoot, "overlay-manifest.json"));
const overlayManifest = JSON.parse(overlayManifestBytes.toString("utf8"));
if (manifest.files.length !== 54) fail(`expected 54 upstream files, found ${manifest.files.length}`);
if (overlayManifest.overlays.length !== 9) fail(`expected 9 overlays, found ${overlayManifest.overlays.length}`);
if (sha256(manifestBytes) !== overlayManifest.upstream_manifest_sha256) {
  fail("manifest.json does not match the overlay manifest's upstream hash");
}

const rootPatchHashes = new Map(overlayManifest.generated_root_patches.map((entry) => [entry.virtual_path, entry.sha256]));
fs.mkdirSync(path.dirname(outputPath), { recursive: true });
if (fs.existsSync(outputPath)) fs.unlinkSync(outputPath);
const archive = Archive.create(outputPath, { maxFileCount: 96 });
try {
  for (const entry of manifest.files) {
    const localPath = path.relative("upstream", entry.vendored_path);
    const source = readVerified(path.join("upstream", localPath), entry.bytes, entry.sha256);
    const race = Object.entries(RACES).find(([, value]) => value.root === entry.virtual_path)?.[0];
    const output = race ? Buffer.from(injectV3Hooks(source.toString("utf8"), race), "utf8") : source;
    if (race && sha256(output) !== rootPatchHashes.get(entry.virtual_path)) {
      fail(`generated ${race} root does not match the 03:47 archive hash`);
    }
    archive.addBuffer(archivePathFor(entry.virtual_path), output);
  }
  for (const entry of overlayManifest.overlays) {
    const source = readVerified(entry.source_path, entry.bytes, entry.sha256);
    archive.addBuffer(archivePathFor(entry.virtual_path), source);
  }
  archive.addBuffer("SC2TeamV3AI.manifest.json", manifestBytes);
  archive.addBuffer("SC2TeamV3AI.overlay-manifest.json", overlayManifestBytes);
  archive.compact();
} finally {
  archive.close();
}

console.log(`V3_AI_MOD_BUILD=PASS upstream=54 overlays=9 generated_roots=3 manifest=${sha256(manifestBytes)}`);
