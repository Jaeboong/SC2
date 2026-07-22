#!/usr/bin/env node

const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { Archive } = require("@jamiephan/stormlib");

// This matches the slot layout used by Blizzard's 14-player 7v7 melee maps.
// Attribute 2011 binds lobby slots 0-6 to team 1 and 7-13 to team 2.
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
            <Default><Slot Id="Global"/><Value Id="28271"/></Default>
        </Attribute>
        <Attribute Namespace="999" Id="2000">
            <Default><Slot Id="Global"/><Value Id="29746"/></Default>
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

function fail(message) {
  throw new Error(message);
}

function readStartLocations(objectsXml) {
  const points = [];
  const pattern = /<ObjectPoint\b[^>]*\bType="StartLoc"[^>]*\/?\s*>/g;
  for (const match of objectsXml.matchAll(pattern)) {
    const idMatch = /\bId="(\d+)"/.exec(match[0]);
    const positionMatch = /\bPosition="([^"]+)"/.exec(match[0]);
    if (!idMatch || !positionMatch) {
      fail("StartLoc without an Id or Position attribute");
    }
    const id = Number(idMatch[1]);
    const [x, y] = positionMatch[1].split(",").map(Number);
    if (!Number.isInteger(id) || !Number.isFinite(x) || !Number.isFinite(y)) {
      fail(`Invalid StartLoc: ${match[0]}`);
    }
    points.push({ id, x, y });
  }
  return points;
}

function chooseSideLocations(points) {
  if (points.length < 14) {
    fail(`At least 14 start locations are required; found ${points.length}`);
  }
  const ordered = [...points].sort((a, b) => a.x - b.x || a.y - b.y);
  return {
    west: ordered.slice(0, 7).sort((a, b) => a.y - b.y),
    east: ordered.slice(-7).sort((a, b) => a.y - b.y),
  };
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
    if (end < 0) fail(`Unterminated MapInfo string at offset ${offset}`);
    const value = buffer.subarray(offset, end).toString("utf8");
    offset = end + 1;
    return value;
  };
  const skip = (length) => {
    offset += length;
    if (offset > buffer.length) fail("MapInfo is truncated");
  };

  const magic = buffer.subarray(0, 4).toString("ascii");
  if (magic !== "IpaM") fail(`Unsupported MapInfo magic: ${magic}`);
  offset = 4;
  const version = readU32();
  if (version !== 0x27) {
    fail(`Unsupported MapInfo version 0x${version.toString(16)}; expected 0x27`);
  }

  readU32();
  readU32();
  readU32();
  readU32();
  let previewType = readU32();
  if (previewType === 2) readCString();
  previewType = readU32();
  if (previewType === 2) readCString();
  readCString();
  readCString();
  readU32();
  readU32();
  readCString();
  readCString();
  for (let index = 0; index < 5; index += 1) readU32();

  const loadScreenType = readU32();
  if (loadScreenType === 2) readCString();
  skip(readU16());
  for (let index = 0; index < 8; index += 1) readU32();
  skip(8);
  skip(9);
  skip(4);
  // MapInfo v0x27 has eight additional bytes before player_count.
  skip(8);

  const playerCount = readU32();
  if (playerCount < 15 || playerCount > 16) {
    fail(`Unexpected MapInfo player count: ${playerCount}`);
  }

  const players = [];
  for (let index = 0; index < playerCount; index += 1) {
    const recordOffset = offset;
    const id = readU8();
    const control = readU32();
    readU32();
    readCString();
    readU32();
    const startPointOffset = offset;
    const startPoint = readU32();
    readU32();
    readCString();
    players.push({ id, control, recordOffset, startPointOffset, startPoint });
  }
  return { version, players };
}

function makeAllianceSupport() {
  return `// SC2TEAM_CUSTOM_BEGIN
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
// SC2TEAM_CUSTOM_END`;
}

function patchMapScript(script) {
  const blockPattern = /\/\/ SC2TEAM_CUSTOM_BEGIN[\s\S]*?\/\/ SC2TEAM_CUSTOM_END/;
  if (!blockPattern.test(script)) {
    fail("The source map does not contain the SC2TEAM custom block");
  }
  const updated = script.replace(blockPattern, makeAllianceSupport());
  if (updated.includes("sc2team_MovePlayerStart")) {
    fail("The unit-teleport function was not completely removed");
  }
  if (!updated.includes("sc2team_Initialize7v7();")) {
    fail("The 7v7 initialization call is missing");
  }
  return updated;
}

function formatPoint(point) {
  return `(${point.x.toFixed(1)}, ${point.y.toFixed(1)}) id=${point.id}`;
}

const [sourceArg, outputArg] = process.argv.slice(2);
if (!sourceArg || !outputArg) {
  console.error(
    "Usage: node tools/fix_player_starts.cjs <source.SC2Map> <output.SC2Map>"
  );
  process.exit(2);
}

const source = path.resolve(sourceArg);
const output = path.resolve(outputArg);
if (!fs.existsSync(source)) fail(`Source map not found: ${source}`);
if (source === output) fail("Source and output paths must be different");

const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "sc2team-fixed-starts-"));
const staged = path.join(tempDir, "map.SC2Map");
try {
  fs.copyFileSync(source, staged);
  const archive = Archive.open(staged);
  let west;
  let east;
  let startCount;
  try {
    const objects = archive.readFileAsString("Objects", "utf8");
    const points = readStartLocations(objects);
    startCount = points.length;
    ({ west, east } = chooseSideLocations(points));
    const assigned = [...west, ...east];

    const mapInfo = archive.readFile("MapInfo");
    const parsed = parseMapInfoPlayers(mapInfo);
    for (let player = 1; player <= 14; player += 1) {
      const record = parsed.players.find((item) => item.id === player);
      if (!record) fail(`MapInfo player ${player} is missing`);
      mapInfo.writeUInt32LE(assigned[player - 1].id, record.startPointOffset);
    }
    archive.addBuffer("MapInfo", mapInfo);

    archive.addString("Attributes", SEVEN_V_SEVEN_ATTRIBUTES, {
      encoding: "utf8",
    });

    const script = archive.readFileAsString("MapScript.galaxy", "utf8");
    archive.addString("MapScript.galaxy", patchMapScript(script), {
      encoding: "utf8",
    });
    archive.compact();
  } finally {
    archive.close();
  }

  fs.mkdirSync(path.dirname(output), { recursive: true });
  fs.copyFileSync(staged, output);
  console.log(`Fixed starts: ${output}`);
  console.log(`Start locations preserved: ${startCount}`);
  console.log(`West P1-P7: ${west.map(formatPoint).join(", ")}`);
  console.log(`East P8-P14: ${east.map(formatPoint).join(", ")}`);
  console.log("Unit teleport code: removed");
  console.log("Lobby teams: slots 0-6 = team 1, slots 7-13 = team 2");
} finally {
  fs.rmSync(tempDir, { recursive: true, force: true });
}
