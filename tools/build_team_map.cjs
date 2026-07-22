#!/usr/bin/env node

const fs = require("node:fs");
const path = require("node:path");
const { Archive } = require("@jamiephan/stormlib");

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
const SEVEN_V_SEVEN_ATTRIBUTES = `<?xml version="1.0" encoding="utf-8"?>
<Attributes>
    <DefaultVariants Value="0"/>
    <Variant>
        <Id Value="1"/>
        <CategoryId Value="6"/>
        <ModeId Value="1"/>
        <ModeName Value="Variant001/ModeName"/>
        <ModeDesc Value="Variant001/ModeDesc"/>
        <MaxTeamSize Value="7"/>
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
            <Default><Slot Id="0"/><Value Id="21553"/></Default>
            <Default><Slot Id="1"/><Value Id="21553" Index="1"/></Default>
            <Default><Slot Id="2"/><Value Id="21553" Index="2"/></Default>
            <Default><Slot Id="3"/><Value Id="21553" Index="3"/></Default>
            <Default><Slot Id="4"/><Value Id="21553" Index="4"/></Default>
            <Default><Slot Id="5"/><Value Id="21553" Index="5"/></Default>
            <Default><Slot Id="6"/><Value Id="21553" Index="6"/></Default>
            <Default><Slot Id="7"/><Value Id="21554"/></Default>
            <Default><Slot Id="8"/><Value Id="21554" Index="1"/></Default>
            <Default><Slot Id="9"/><Value Id="21554" Index="2"/></Default>
            <Default><Slot Id="10"/><Value Id="21554" Index="3"/></Default>
            <Default><Slot Id="11"/><Value Id="21554" Index="4"/></Default>
            <Default><Slot Id="12"/><Value Id="21554" Index="5"/></Default>
            <Default><Slot Id="13"/><Value Id="21554" Index="6"/></Default>
        </Attribute>
    </Variant>
</Attributes>
`;
const RICH_RESOURCE_TYPES = new Set([
  "RichMineralField",
  "RichMineralField750",
  "PurifierRichMineralField",
  "RichVespeneGeyser",
]);

const REQUIRED_ARCHIVE_FILES = [
  "Objects",
  "Base.SC2Data\\GameData\\UnitData.xml",
  "MapInfo",
  "MapScript.galaxy",
];

function usage() {
  console.log(
    "Usage: node tools/build_team_map.cjs <source.SC2Map> <output.SC2Map> " +
      "[--allow-non-14]"
  );
}

function parseArgs(argv) {
  const allowNon14 = argv.includes("--allow-non-14");
  const positional = argv.filter((value) => !value.startsWith("--"));
  if (positional.length !== 2) {
    usage();
    process.exitCode = 2;
    return null;
  }
  return {
    source: path.resolve(positional[0]),
    output: path.resolve(positional[1]),
    allowNon14,
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

function chooseSideLocations(startLocations) {
  const ordered = [...startLocations].sort((a, b) => a.x - b.x || a.y - b.y);
  const west = ordered.slice(0, 7).sort((a, b) => a.y - b.y);
  const east = ordered.slice(-7).sort((a, b) => a.y - b.y);
  if (west.length !== 7 || east.length !== 7) {
    throw new Error("At least fourteen start locations are required for 7v7");
  }
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

function parseMapInfoPlayers(buffer) {
  let offset = 0;
  const readU8 = () => buffer.readUInt8(offset++);
  const readU16 = () => {
    const value = buffer.readUInt16LE(offset);
    offset += 2;
    return value;
  };
  const readU32 = () => {
    const value = buffer.readUInt32LE(offset);
    offset += 4;
    return value;
  };
  const readCString = () => {
    const end = buffer.indexOf(0, offset);
    if (end < 0) throw new Error(`Unterminated MapInfo string at ${offset}`);
    const value = buffer.subarray(offset, end).toString("utf8");
    offset = end + 1;
    return value;
  };
  const skip = (length) => {
    offset += length;
    if (offset > buffer.length) throw new Error("MapInfo is truncated");
  };

  if (buffer.subarray(0, 4).toString("ascii") !== "IpaM") {
    throw new Error("Unsupported MapInfo magic");
  }
  offset = 4;
  const version = readU32();
  if (version !== 0x27) {
    throw new Error(`Unsupported MapInfo version 0x${version.toString(16)}`);
  }
  readU32(); readU32(); readU32(); readU32();
  let previewType = readU32();
  if (previewType === 2) readCString();
  previewType = readU32();
  if (previewType === 2) readCString();
  readCString(); readCString(); readU32(); readU32(); readCString(); readCString();
  for (let index = 0; index < 5; index += 1) readU32();
  const loadScreenType = readU32();
  if (loadScreenType === 2) readCString();
  skip(readU16());
  for (let index = 0; index < 8; index += 1) readU32();
  skip(8); skip(9); skip(4); skip(8);

  const playerCount = readU32();
  if (playerCount < 15 || playerCount > 16) {
    throw new Error(`Unexpected MapInfo player count: ${playerCount}`);
  }
  const players = [];
  for (let index = 0; index < playerCount; index += 1) {
    const id = readU8();
    readU32(); readU32(); readCString(); readU32();
    const startPointOffset = offset;
    readU32(); readU32(); readCString();
    players.push({ id, startPointOffset });
  }
  return players;
}

function patchFixedPlayerStarts(mapInfo, west, east) {
  const players = parseMapInfoPlayers(mapInfo);
  const assigned = [...west, ...east];
  for (let player = 1; player <= 14; player += 1) {
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

function patchLobbyVariant(archive) {
  archive.addString("Attributes", SEVEN_V_SEVEN_ATTRIBUTES, { encoding: "utf8" });

  const localized = {
    koKR: {
      "Variant001/ModeName": "7 대 7",
      "Variant001/ModeDesc": "두 팀이 각각 일곱 명으로 나뉘어 싸우는 섬멸전입니다.",
    },
    enUS: {
      "Variant001/ModeName": "7 vs 7",
      "Variant001/ModeDesc": "Two teams of seven players fight a melee match.",
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

function makeGalaxySupport() {
  return `
// SC2TEAM_CUSTOM_BEGIN
// Fixed starts are stored in MapInfo. Player 1-7: west; Player 8-14: east.
void sc2team_Initialize7v7 () {
    int firstPlayer;
    int secondPlayer;

    for (firstPlayer = 1; firstPlayer <= 14; firstPlayer += 1) {
        for (secondPlayer = firstPlayer + 1; secondPlayer <= 14; secondPlayer += 1) {
            if ((firstPlayer <= 7 && secondPlayer <= 7) ||
                (firstPlayer >= 8 && secondPlayer >= 8)) {
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

function patchMapScript(mapScript) {
  if (mapScript.includes("SC2TEAM_CUSTOM_BEGIN")) {
    throw new Error("The source map is already patched by this tool");
  }

  const support = makeGalaxySupport();
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

function buildMap({ source, output, allowNon14 }) {
  if (!fs.existsSync(source)) {
    throw new Error(`Source map not found: ${source}`);
  }
  if (source === output) {
    throw new Error("Source and output paths must be different");
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
    if (startLocations.length < 14 && !allowNon14) {
      throw new Error(
        `Expected at least 14 start locations, found ${startLocations.length}. ` +
          "Use the exact 유럽 섬멸전_2 source map."
      );
    }
    const { west, east } = chooseSideLocations(startLocations);
    const resourceResult = makeAllResourcesRich(objectsXml);

    const unitDataName = "Base.SC2Data\\GameData\\UnitData.xml";
    const mapScript = archive.readFileAsString("MapScript.galaxy", "utf8");
    const mapInfo = archive.readFile("MapInfo");

    archive.addString("Objects", resourceResult.updated, { encoding: "utf8" });
    archive.addString(unitDataName, makeDefaultUnitDataWithWorkerFoodZero(), {
      encoding: "utf8",
    });
    archive.addBuffer("MapInfo", patchFixedPlayerStarts(mapInfo, west, east));
    archive.addString("MapScript.galaxy", patchMapScript(mapScript), {
      encoding: "utf8",
    });
    patchLobbyVariant(archive);
    archive.compact();

    console.log(`Built: ${output}`);
    console.log(`Start locations preserved: ${startLocations.length}`);
    console.log(`West team (players 1-7): ${west.map(formatPoint).join(", ")}`);
    console.log(`East team (players 8-14): ${east.map(formatPoint).join(", ")}`);
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
    console.log("Lobby variant: melee 7 vs 7 (two teams, seven slots per team)");
  } finally {
    archive.close();
  }
}

const args = parseArgs(process.argv.slice(2));
if (args) {
  try {
    buildMap(args);
  } catch (error) {
    if (fs.existsSync(args.output)) {
      fs.rmSync(args.output, { force: true });
    }
    console.error(`ERROR: ${error.message}`);
    process.exitCode = 1;
  }
}
