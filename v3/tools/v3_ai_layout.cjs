"use strict";

const crypto = require("node:crypto");

const RACES = {
  Terran: { root: "Base.SC2Data/TriggerLibs/Terran/Terran.galaxy", hook: "TriggerLibs/V3/Terran", runner: "V3RunTerranBuild" },
  Protoss: { root: "Base.SC2Data/TriggerLibs/Protoss/Protoss.galaxy", hook: "TriggerLibs/V3/Protoss", runner: "V3RunProtossBuild" },
  Zerg: { root: "Base.SC2Data/TriggerLibs/Zerg/Zerg.galaxy", hook: "TriggerLibs/V3/Zerg", runner: "V3RunZergBuild" },
};

function sha256(data) {
  return crypto.createHash("sha256").update(data).digest("hex");
}

function fail(message) {
  throw new Error(`V3 AI layout failed: ${message}`);
}

function injectV3Hooks(source, race) {
  const config = RACES[race];
  if (!config) fail(`unknown race ${race}`);
  if (source.includes(`include "${config.hook}"`)) fail(`${race} root already has a V3 hook`);
  const includeAnchor = `include "TriggerLibs/${race}/${race}ChIn"\r\n`;
  if (!source.includes(includeAnchor)) fail(`${race} root include anchor is missing`);
  // The 03:47 baseline was created by the historical builder, whose inserted
  // strings used LF while the upstream root uses CRLF. Preserve that exact
  // byte layout so generated roots can be checked against the archive hash.
  let patched = source.replace(includeAnchor, `include "TriggerLibs/${race}/${race}ChIn"\ninclude "${config.hook}"\r\n`);
  for (const [functionName, phase] of [[`${race}Open`, 0], [`${race}Mid`, 1], [`${race}Late`, 2]]) {
    const anchor = `void ${functionName} (int player) {\r\n    int diff = AIPlayerDifficulty(player);\r\n`;
    const replacement = `void ${functionName} (int player) {\r\n    int diff = AIPlayerDifficulty(player);\n    if (${config.runner}(player, ${phase})) { return; }\r\n`;
    if (!patched.includes(anchor)) fail(`${race} ${functionName} dispatcher anchor is missing`);
    patched = patched.replace(anchor, replacement);
  }
  return patched;
}

function removeV3Hooks(source, race) {
  const config = RACES[race];
  if (!config) fail(`unknown race ${race}`);
  const include = `\ninclude "${config.hook}"\r\n`;
  if (!source.includes(include)) fail(`${race} root V3 include is missing`);
  let restored = source.replace(include, "\r\n");
  for (const [functionName, phase] of [[`${race}Open`, 0], [`${race}Mid`, 1], [`${race}Late`, 2]]) {
    const dispatcher = `void ${functionName} (int player) {\r\n    int diff = AIPlayerDifficulty(player);\n    if (${config.runner}(player, ${phase})) { return; }\r\n`;
    const original = `void ${functionName} (int player) {\r\n    int diff = AIPlayerDifficulty(player);\r\n`;
    if (!restored.includes(dispatcher)) fail(`${race} ${functionName} V3 dispatcher is missing`);
    restored = restored.replace(dispatcher, original);
  }
  return restored;
}

module.exports = { RACES, fail, injectV3Hooks, removeV3Hooks, sha256 };
