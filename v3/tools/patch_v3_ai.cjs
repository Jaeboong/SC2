// Connect a built V3 map to the pinned custom-AI TriggerLib snapshot.
"use strict";

const fs = require("node:fs");
const { Archive } = require("@jamiephan/stormlib");

const [mapPath, planPath] = process.argv.slice(2);
const V3_DEPENDENCY = "file:Mods/SC2TeamV3AI.SC2Mod";
const BUILD_MARKER = "// SC2TEAM_V3_BUILD_SELECTIONS";

function fail(message) { throw new Error(`V3 map patch failed: ${message}`); }

function loadPlan() {
  const plan = JSON.parse(fs.readFileSync(planPath, "utf8"));
  if (!plan || !Array.isArray(plan.players)) fail("plan.players is missing");
  return plan;
}

function patchDocumentInfo(content) {
  if (!/<Dependencies\b/i.test(content)) {
    content = content.replace(/<\/DocInfo>/i, "    <Dependencies>\n    </Dependencies>\n</DocInfo>");
  }
  content = content.replace(/\s*<Value>[^<]*SC2TeamV3AI\.SC2Mod<\/Value>/ig, "");
  const newline = content.includes("\r\n") ? "\r\n" : "\n";
  return content.replace(
    /[ \t]*<\/Dependencies>/i,
    `        <Value>${V3_DEPENDENCY}</Value>${newline}    </Dependencies>`,
  );
}

function patchDocumentHeader(buffer) {
  if (buffer.subarray(0, 4).toString("latin1") !== "H2CS") fail("unexpected DocumentHeader magic");
  const first = buffer.indexOf(Buffer.from("bnet:", "utf8"));
  if (first < 4) fail("DocumentHeader has no dependencies");
  const countOffset = first - 4;
  const count = buffer.readUInt32LE(countOffset);
  const dependencies = [];
  let cursor = first;
  for (let index = 0; index < count; index += 1) {
    const end = buffer.indexOf(0x00, cursor);
    if (end < 0) fail("unterminated DocumentHeader dependency");
    const value = buffer.subarray(cursor, end).toString("utf8");
    if (!value.includes("SC2TeamV3AI.SC2Mod")) dependencies.push(value);
    cursor = end + 1;
  }
  dependencies.push(V3_DEPENDENCY);
  const countBuffer = Buffer.alloc(4);
  countBuffer.writeUInt32LE(dependencies.length, 0);
  const strings = Buffer.concat(dependencies.map((value) =>
    Buffer.concat([Buffer.from(value, "utf8"), Buffer.from([0])])
  ));
  return Buffer.concat([
    buffer.subarray(0, countOffset), countBuffer, strings, buffer.subarray(cursor),
  ]);
}

function buildSelections(plan) {
  const allowed = new Set([101, 102, 201, 202, 301, 302]);
  return plan.players.filter((entry) => entry.build_id !== undefined).map((entry) => {
    if (!Number.isInteger(entry.runtime) || entry.runtime < 1 || entry.runtime > 14) {
      fail(`invalid runtime player: ${entry.runtime}`);
    }
    if (!allowed.has(entry.build_id)) fail(`invalid build ID: ${entry.build_id}`);
    return `    AISetUserInt(${entry.runtime}, 142, ${entry.build_id}); // slot P${entry.slot}: ${entry.build}`;
  });
}

if (!mapPath || !planPath || process.argv.length !== 4) {
  fail("usage: node patch_v3_ai.cjs <map.SC2Map> <v3-plan.json>");
}

const plan = loadPlan();
const archive = Archive.open(mapPath);
try {
  let script = archive.readFileAsString("MapScript.galaxy", "utf8");
  const matches = script.match(/^[ \t]*MeleeInitAI\s*\(\s*\)\s*;[ \t]*$/gm) || [];
  if (matches.length !== 1) fail(`expected one MeleeInitAI call, found ${matches.length}`);
  if (script.includes(BUILD_MARKER)) fail("build selections already exist");
  const selections = buildSelections(plan);
  if (selections.length === 0 && plan.wild_zerg !== true) {
    fail("no V3 builds selected");
  }
  script = script.replace(
    matches[0],
    `${matches[0]}\n${BUILD_MARKER}\n${selections.join("\n")}`,
  );
  archive.addString("MapScript.galaxy", script, { encoding: "utf8" });
  archive.addString(
    "DocumentInfo",
    patchDocumentInfo(archive.readFileAsString("DocumentInfo", "utf8")),
    { encoding: "utf8" },
  );
  archive.addBuffer("DocumentHeader", patchDocumentHeader(archive.readFile("DocumentHeader")));
  archive.compact();
} finally {
  archive.close();
}

console.log(`V3_MAP_PATCH=PASS dependency=${V3_DEPENDENCY} builds=${buildSelections(plan).length}`);
