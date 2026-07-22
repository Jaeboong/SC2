#!/usr/bin/env node

const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { Archive } = require("@jamiephan/stormlib");

function fail(message) {
  throw new Error(message);
}

const [mapArg] = process.argv.slice(2);
if (!mapArg) {
  console.error("Usage: node tools/verify_team_archive.cjs <map.SC2Map>");
  process.exit(2);
}

const source = path.resolve(mapArg);
if (!fs.existsSync(source)) fail(`Map not found: ${source}`);

const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "sc2team-verify-"));
const staged = path.join(tempDir, "map.SC2Map");
try {
  fs.copyFileSync(source, staged);
  const archive = Archive.open(staged);
  try {
    const attributes = archive.readFileAsString("Attributes", "utf8");
    const script = archive.readFileAsString("MapScript.galaxy", "utf8");

    if (!attributes.includes('<CategoryId Value="6"/>')) {
      fail("Lobby category is not melee CategoryId 6");
    }
    if (!attributes.includes('<MaxTeamSize Value="7"/>')) {
      fail("Lobby max team size is not 7");
    }
    if (!attributes.includes('<Attribute Namespace="999" Id="2011">')) {
      fail("Lobby team-slot attribute 2011 is missing");
    }

    for (let slot = 0; slot < 14; slot += 1) {
      const teamValue = slot < 7 ? 21553 : 21554;
      const index = slot < 7 ? slot : slot - 7;
      const indexText = index === 0 ? "" : ` Index="${index}"`;
      const expected =
        `<Slot Id="${slot}"/><Value Id="${teamValue}"${indexText}/>`;
      if (!attributes.includes(expected)) {
        fail(`Incorrect team mapping for lobby slot ${slot}`);
      }
    }

    if (script.includes("UnitSetPosition") || script.includes("sc2team_MovePlayerStart")) {
      fail("Obsolete start-unit teleport code is still present");
    }
    if (!script.includes("sc2team_Initialize7v7();")) {
      fail("7v7 alliance initialization call is missing");
    }

    console.log("Lobby category: PASS (melee CategoryId 6)");
    console.log("Lobby teams: PASS (slots 0-6 vs 7-13)");
    console.log("Start script: PASS (fixed starts, no unit teleport)");
  } finally {
    archive.close();
  }
} finally {
  fs.rmSync(tempDir, { recursive: true, force: true });
}
