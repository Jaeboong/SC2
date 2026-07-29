#!/usr/bin/env node

const fs = require("node:fs");
const path = require("node:path");
const { Archive } = require("@jamiephan/stormlib");
const { parseMapInfoPlayers } = require("./build/mapinfo.cjs");
const { readMapCapabilities } = require("./build/map_capabilities.cjs");

const RESOURCE_REPLACEMENTS = new Map([
  ["MineralField", "RichMineralField"],
  ["MineralField750", "RichMineralField750"],
  ["MineralFieldOpaque", "RichMineralField"],
  ["MineralFieldOpaque900", "RichMineralField"],
  ["VespeneGeyser", "RichVespeneGeyser"],
  ["ProtossVespeneGeyser", "RichVespeneGeyser"],
  ["SpacePlatformGeyser", "RichVespeneGeyser"],
]);

const RESOURCE_AMOUNT = 50000;
const RICH_RESOURCE_TYPES = new Set([
  "RichMineralField",
  "RichMineralField750",
  "PurifierRichMineralField",
  "RichVespeneGeyser",
]);

const REQUIRED_ARCHIVE_FILES = [
  "Objects",
  "MapInfo",
  "MapScript.galaxy",
];

function usage() {
  console.log(
    "Usage: node tools/build_team_map.cjs <source.SC2Map> <output.SC2Map> " +
      "[--players N]"
  );
}

function parseArgs(argv) {
  let players = null;
  const positional = [];
  for (let index = 0; index < argv.length; index += 1) {
    const value = argv[index];
    if (value === "--allow-non-14") {
      console.warn("WARNING: --allow-non-14 is obsolete and ignored; use --players N");
    } else if (value === "--players") {
      players = Number(argv[++index]);
    } else if (value.startsWith("--players=")) {
      players = Number(value.slice("--players=".length));
    } else if (value.startsWith("--")) {
      throw new Error(`Unknown option: ${value}`);
    } else {
      positional.push(value);
    }
  }
  if (positional.length !== 2) {
    usage();
    process.exitCode = 2;
    return null;
  }
  return {
    source: path.resolve(positional[0]),
    output: path.resolve(positional[1]),
    players,
  };
}

function extractStartLocations(objectsXml) {
  const points = [];
  const pointPattern = /<ObjectPoint\b[^>]*\bType="StartLoc"[^>]*\/?\s*>/g;
  for (const match of objectsXml.matchAll(pointPattern)) {
    const position = /\bPosition="([^"]+)"/.exec(match[0]);
    const id = /\bId="(\d+)"/.exec(match[0]);
    if (!position || !id) {
      throw new Error("StartLoc without an Id or Position attribute");
    }
    const [x, y] = position[1].split(",").map(Number);
    if (!Number.isFinite(x) || !Number.isFinite(y)) {
      throw new Error(`Invalid StartLoc position: ${position[1]}`);
    }
    points.push({ id: Number(id[1]), x, y });
  }
  return points;
}

function chooseSideLocations(startLocations, playerCount) {
  if (startLocations.length < playerCount) {
    throw new Error(`At least ${playerCount} start locations are required`);
  }
  const ordered = [...startLocations].sort((a, b) => a.x - b.x || a.y - b.y);
  const westSize = Math.ceil(playerCount / 2);
  const eastSize = Math.floor(playerCount / 2);
  const west = ordered.slice(0, westSize).sort((a, b) => a.y - b.y);
  const east = ordered.slice(-eastSize).sort((a, b) => a.y - b.y);
  return { west, east };
}

function makeAllResourcesRich(objectsXml) {
  const counts = {};
  let updated = objectsXml.replace(
    /(<ObjectUnit\b[^>]*\bUnitType=")([^"]+)(")/g,
    (whole, prefix, type, suffix) => {
      const replacement = RESOURCE_REPLACEMENTS.get(type);
      if (!replacement) {
        return whole;
      }
      counts[`${type}->${replacement}`] =
        (counts[`${type}->${replacement}`] || 0) + 1;
      return `${prefix}${replacement}${suffix}`;
    }
  );

  let amountCount = 0;
  updated = updated.replace(/<ObjectUnit\b[^>]*\/>/g, (objectUnit) => {
    const unitType = /\bUnitType="([^"]+)"/.exec(objectUnit)?.[1];
    if (!RICH_RESOURCE_TYPES.has(unitType)) {
      return objectUnit;
    }
    amountCount += 1;
    if (/\bResources="[^"]*"/.test(objectUnit)) {
      return objectUnit.replace(/\bResources="[^"]*"/, `Resources="${RESOURCE_AMOUNT}"`);
    }
    return objectUnit.replace(/\/>$/, ` Resources="${RESOURCE_AMOUNT}"/>`);
  });

  return { updated, counts, amountCount };
}

function makeDefaultUnitDataWithWorkerFoodZero() {
  // Intentionally discard every map-level unit override. The source map changes
  // Bunker durability and Gateway abilities/card slots; omitting those entries
  // makes SC2 inherit the normal Void/VoidMulti melee data again.
  return `<?xml version="1.0" encoding="utf-8"?>
<Catalog>
    <CUnit id="Drone">
        <Food value="0"/>
    </CUnit>
    <CUnit id="Probe">
        <Food value="0"/>
    </CUnit>
    <CUnit id="SCV">
        <Food value="0"/>
    </CUnit>
</Catalog>
`;
}

function patchFixedPlayerStarts(mapInfo, assigned) {
  const players = parseMapInfoPlayers(mapInfo);
  for (let player = 1; player <= assigned.length; player += 1) {
    const record = players.find((item) => item.id === player);
    if (!record) throw new Error(`MapInfo player ${player} is missing`);
    mapInfo.writeUInt32LE(assigned[player - 1].id, record.startPointOffset);
  }
  return mapInfo;
}

function setLocalizedLines(content, replacements) {
  const newline = content.includes("\r\n") ? "\r\n" : "\n";
  const lines = content.split(/\r?\n/);
  const pending = new Map(Object.entries(replacements));
  const updated = lines.map((line) => {
    const separator = line.indexOf("=");
    if (separator < 0) {
      return line;
    }
    const key = line.slice(0, separator);
    if (!pending.has(key)) {
      return line;
    }
    const value = pending.get(key);
    pending.delete(key);
    return `${key}=${value}`;
  });
  for (const [key, value] of pending) {
    updated.push(`${key}=${value}`);
  }
  return updated.join(newline);
}

function makeLobbyAttributes(playerCount) {
  const westSize = Math.ceil(playerCount / 2);
  const defaults = [];
  for (let slot = 0; slot < playerCount; slot += 1) {
    const west = slot < westSize;
    const index = west ? slot : slot - westSize;
    const valueId = west ? "21553" : "21554";
    const indexAttribute = index === 0 ? "" : ` Index="${index}"`;
    defaults.push(
      `            <Default><Slot Id="${slot}"/><Value Id="${valueId}"${indexAttribute}/></Default>`
    );
  }
  return `<?xml version="1.0" encoding="utf-8"?>
<Attributes>
    <DefaultVariants Value="0"/>
    <Variant>
        <Id Value="1"/>
        <CategoryId Value="6"/>
        <ModeId Value="1"/>
        <ModeName Value="Variant001/ModeName"/>
        <ModeDesc Value="Variant001/ModeDesc"/>
        <MaxTeamSize Value="${westSize}"/>
        <AttributeHidden Namespace="999" Id="3006"/>
        <Attribute Namespace="999" Id="1001">
            <Default>
                <Slot Id="Global"/>
                <Value Id="28271"/>
            </Default>
        </Attribute>
        <Attribute Namespace="999" Id="2000">
            <Default>
                <Slot Id="Global"/>
                <Value Id="29746"/>
            </Default>
        </Attribute>
        <Attribute Namespace="999" Id="2011">
${defaults.join("\n")}
        </Attribute>
    </Variant>
</Attributes>
`;
}

function patchLobbyVariant(archive, playerCount) {
  archive.addString("Attributes", makeLobbyAttributes(playerCount), { encoding: "utf8" });

  const westSize = Math.ceil(playerCount / 2);
  const eastSize = Math.floor(playerCount / 2);
  const koreanCount = ["", "한", "두", "세", "네", "다섯", "여섯", "일곱"];
  const koreanDescription = playerCount === 14
    ? "두 팀이 각각 일곱 명으로 나뉘어 싸우는 섬멸전입니다."
    : `두 팀이 각각 ${koreanCount[westSize]} 명과 ${koreanCount[eastSize]} 명으로 나뉘어 싸우는 섬멸전입니다.`;
  const englishDescription = playerCount === 14
    ? "Two teams of seven players fight a melee match."
    : `Teams of ${westSize} and ${eastSize} players fight a melee match.`;

  const localized = {
    koKR: {
      "Variant001/ModeName": `${westSize} 대 ${eastSize}`,
      "Variant001/ModeDesc": koreanDescription,
    },
    enUS: {
      "Variant001/ModeName": `${westSize} vs ${eastSize}`,
      "Variant001/ModeDesc": englishDescription,
    },
  };

  for (const [locale, replacements] of Object.entries(localized)) {
    const archiveName = `${locale}.SC2Data\\LocalizedData\\GameStrings.txt`;
    const content = archive.hasFile(archiveName)
      ? archive.readFileAsString(archiveName, "utf8")
      : "";
    archive.addString(archiveName, setLocalizedLines(content, replacements), {
      encoding: "utf8",
    });
  }
}

function makeGalaxySupport(playerCount) {
  const westSize = Math.ceil(playerCount / 2);
  return `
// SC2TEAM_CUSTOM_BEGIN
// Fixed starts are stored in MapInfo. Player 1-${westSize}: west; Player ${westSize + 1}-${playerCount}: east.
void sc2team_Initialize7v7 () {
    int firstPlayer;
    int secondPlayer;

    for (firstPlayer = 1; firstPlayer <= ${playerCount}; firstPlayer += 1) {
        for (secondPlayer = firstPlayer + 1; secondPlayer <= ${playerCount}; secondPlayer += 1) {
            if ((firstPlayer <= ${westSize} && secondPlayer <= ${westSize}) ||
                (firstPlayer >= ${westSize + 1} && secondPlayer >= ${westSize + 1})) {
                libNtve_gf_SetAlliance(firstPlayer, secondPlayer, libNtve_ge_AllianceSetting_AllyWithSharedVision);
            }
            else {
                libNtve_gf_SetAlliance(firstPlayer, secondPlayer, libNtve_ge_AllianceSetting_Enemy);
            }
        }
    }

}
// SC2TEAM_CUSTOM_END
`;
}

function patchMapScript(mapScript, playerCount) {
  if (mapScript.includes("SC2TEAM_CUSTOM_BEGIN")) {
    throw new Error("The source map is already patched by this tool");
  }

  const support = makeGalaxySupport(playerCount);
  const includeLine = 'include "TriggerLibs/NativeLib"';
  if (!mapScript.includes(includeLine)) {
    throw new Error("MapScript.galaxy does not include TriggerLibs/NativeLib");
  }
  let updated = mapScript.replace(includeLine, `${includeLine}\n${support}`);

  const standardInit = /(\s*)MeleeInitResources\(\);\s*MeleeInitUnits\(\);\s*MeleeInitAI\(\);\s*MeleeInitOptions\(\);/;
  const match = standardInit.exec(updated);
  if (!match) {
    throw new Error("Could not find the standard melee initialization block");
  }
  const indent = match[1];
  const replacement =
    `${indent}MeleeInitResources();\n` +
    `${indent}MeleeInitUnits();\n` +
    `${indent}MeleeInitOptions();\n` +
    `${indent}sc2team_Initialize7v7();\n` +
    `${indent}MeleeInitAI();`;
  updated = updated.replace(standardInit, replacement);
  return updated;
}

function formatPoint(point) {
  return `(${point.x.toFixed(1)}, ${point.y.toFixed(1)})`;
}

function buildMap({ source, output, players: requestedPlayers }) {
  if (!fs.existsSync(source)) {
    throw new Error(`Source map not found: ${source}`);
  }
  if (source === output) {
    throw new Error("Source and output paths must be different");
  }
  const capabilities = readMapCapabilities(source);
  if (!capabilities.readable) {
    throw new Error(`Cannot read map capabilities: ${capabilities.reason}`);
  }
  const playerCount = requestedPlayers === null ? capabilities.maxPlayers : requestedPlayers;
  if (!Number.isInteger(playerCount) || playerCount < 2 || playerCount > 14) {
    throw new Error("--players must be an integer between 2 and 14");
  }
  if (playerCount > capabilities.maxPlayers) {
    throw new Error(
      `Map supports ${capabilities.maxPlayers} players but --players requested ${playerCount}`
    );
  }

  fs.mkdirSync(path.dirname(output), { recursive: true });
  fs.copyFileSync(source, output);

  const archive = Archive.open(output);
  try {
    for (const archiveName of REQUIRED_ARCHIVE_FILES) {
      if (!archive.hasFile(archiveName)) {
        throw new Error(`Required file is missing from the map: ${archiveName}`);
      }
    }

    const objectsXml = archive.readFileAsString("Objects", "utf8");
    const startLocations = extractStartLocations(objectsXml);
    const { west, east } = chooseSideLocations(startLocations, playerCount);
    const assigned = [...west, ...east];
    const resourceResult = makeAllResourcesRich(objectsXml);

    const unitDataName = "Base.SC2Data\\GameData\\UnitData.xml";
    const mapScript = archive.readFileAsString("MapScript.galaxy", "utf8");
    const mapInfo = archive.readFile("MapInfo");

    archive.addString("Objects", resourceResult.updated, { encoding: "utf8" });
    archive.addString(unitDataName, makeDefaultUnitDataWithWorkerFoodZero(), {
      encoding: "utf8",
    });
    archive.addBuffer("MapInfo", patchFixedPlayerStarts(mapInfo, assigned));
    archive.addString("MapScript.galaxy", patchMapScript(mapScript, playerCount), {
      encoding: "utf8",
    });
    patchLobbyVariant(archive, playerCount);
    archive.compact();

    console.log(`Built: ${output}`);
    console.log(`Start locations preserved: ${startLocations.length}`);
    console.log(`Players prepared: ${playerCount}`);
    console.log(`West team (players 1-${west.length}): ${west.map(formatPoint).join(", ")}`);
    console.log(`East team (players ${west.length + 1}-${playerCount}): ${east.map(formatPoint).join(", ")}`);
    console.log("Resource replacements:");
    for (const [replacement, count] of Object.entries(resourceResult.counts)) {
      console.log(`  ${replacement}: ${count}`);
    }
    console.log(
      `Resource amount: ${resourceResult.amountCount} mineral/geyser objects set to ${RESOURCE_AMOUNT}`
    );
    console.log("Map-level unit overrides removed: all normal melee defaults restored");
    console.log("Worker supply: Drone=0, Probe=0, SCV=0");
    console.log("Player start points: fixed in MapInfo (no unit teleport)");
    console.log(`Lobby variant: melee ${west.length} vs ${east.length} (two teams)`);
  } finally {
    archive.close();
  }
}

if (require.main === module) {
  let args;
  try {
    args = parseArgs(process.argv.slice(2));
    if (args) buildMap(args);
  } catch (error) {
    if (args && fs.existsSync(args.output)) {
      fs.rmSync(args.output, { force: true });
    }
    console.error(`ERROR: ${error.message}`);
    process.exitCode = 1;
  }
}

module.exports = {
  chooseSideLocations,
  makeGalaxySupport,
  makeLobbyAttributes,
  patchFixedPlayerStarts,
};
