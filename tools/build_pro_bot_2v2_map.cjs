#!/usr/bin/env node

const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { Archive } = require("@jamiephan/stormlib");

const MAP_NAME_KO = "유럽 섬멸전 Pro Bot v0.2_test";
const MAP_NAME_EN = "Europe Melee Pro Bot v0.2_test";

const TWO_V_TWO_ATTRIBUTES = `<?xml version="1.0" encoding="utf-8"?>
<Attributes>
    <DefaultVariants Value="0"/>
    <Variant>
        <Id Value="1"/>
        <CategoryId Value="6"/>
        <ModeId Value="1"/>
        <ModeName Value="Variant001/ModeName"/>
        <ModeDesc Value="Variant001/ModeDesc"/>
        <MaxTeamSize Value="2"/>
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
            <Default><Slot Id="2"/><Value Id="21554"/></Default>
            <Default><Slot Id="3"/><Value Id="21554" Index="1"/></Default>
        </Attribute>
    </Variant>
</Attributes>
`;

function fail(message) {
  throw new Error(message);
}

function parseMapInfoPlayers(buffer) {
  let offset = 4;
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

  if (buffer.subarray(0, 4).toString("ascii") !== "IpaM") {
    fail("Unsupported MapInfo magic");
  }
  const version = readU32();
  if (version !== 0x27) fail(`Unsupported MapInfo version 0x${version.toString(16)}`);

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
    fail(`Unexpected MapInfo player count: ${playerCount}`);
  }

  const players = [];
  for (let index = 0; index < playerCount; index += 1) {
    const id = readU8();
    const controlOffset = offset;
    const control = readU32();
    readU32();
    readCString();
    readU32();
    const startPointOffset = offset;
    const startPoint = readU32();
    readU32();
    readCString();
    players.push({ id, control, controlOffset, startPoint, startPointOffset });
  }
  return players;
}

function readStartLocations(objectsXml) {
  const locations = new Map();
  const pattern = /<ObjectPoint\b[^>]*\bType="StartLoc"[^>]*\/?\s*>/g;
  for (const match of objectsXml.matchAll(pattern)) {
    const idMatch = /\bId="(\d+)"/.exec(match[0]);
    const positionMatch = /\bPosition="([^"]+)"/.exec(match[0]);
    if (!idMatch || !positionMatch) fail("StartLoc is missing its id or position");
    const [x, y] = positionMatch[1].split(",").map(Number);
    locations.set(Number(idMatch[1]), { id: Number(idMatch[1]), x, y });
  }
  return locations;
}

function selectTeamStarts(players, locations) {
  // The source's fixed-team MapInfo already assigns P1-P7 to the west and
  // P8-P14 to the east. Reuse P1/P2 and P8/P9 so no coordinate heuristic can
  // accidentally select a center/decorative start location.
  const sourceIds = [1, 2, 8, 9].map((playerId) => {
    const player = players.find((candidate) => candidate.id === playerId);
    if (!player || !player.startPoint) fail(`Source P${playerId} has no fixed start`);
    return player.startPoint;
  });
  const starts = sourceIds.map((id) => locations.get(id));
  if (starts.some((start) => !start)) fail("A fixed source start is absent from Objects");
  if (!(starts[0].x < starts[2].x && starts[1].x < starts[3].x)) {
    fail("Source fixed starts are not separated west/east as expected");
  }
  return starts;
}

function patchPlayers(mapInfo, starts) {
  const players = parseMapInfoPlayers(mapInfo);
  for (const player of players) {
    if (player.id >= 1 && player.id <= 4) {
      mapInfo.writeUInt32LE(1, player.controlOffset);
      mapInfo.writeUInt32LE(starts[player.id - 1].id, player.startPointOffset);
    } else if (player.id >= 5 && player.id <= 14) {
      mapInfo.writeUInt32LE(0, player.controlOffset);
      mapInfo.writeUInt32LE(0, player.startPointOffset);
    }
  }
  return mapInfo;
}

function setLocalizedLines(content, replacements) {
  const newline = content.includes("\r\n") ? "\r\n" : "\n";
  const lines = content.split(/\r?\n/);
  const pending = new Map(Object.entries(replacements));
  const updated = lines.map((line) => {
    const separator = line.indexOf("=");
    if (separator < 0) return line;
    const key = line.slice(0, separator).replace(/^\uFEFF/, "");
    if (!pending.has(key)) return line;
    const prefix = line.startsWith("\uFEFF") ? "\uFEFF" : "";
    const value = pending.get(key);
    pending.delete(key);
    return `${prefix}${key}=${value}`;
  });
  for (const [key, value] of pending) updated.push(`${key}=${value}`);
  return updated.join(newline);
}

function patchLocalization(archive) {
  const localized = {
    koKR: {
      "DocInfo/Name": MAP_NAME_KO,
      "DocInfo/DescShort": "사람과 Changeling이 참가하는 로컬 2대2 테스트",
      "DocInfo/DescLong": "P1 사람과 P2 Changeling이 서쪽 팀, P3/P4 Changeling이 동쪽 팀으로 대결하는 로컬 Pro Bot 테스트 맵입니다.",
      "Variant001/ModeName": "2 대 2",
      "Variant001/ModeDesc": "서쪽 P1/P2 대 동쪽 P3/P4 Pro Bot 테스트",
    },
    enUS: {
      "DocInfo/Name": MAP_NAME_EN,
      "DocInfo/DescShort": "Local human and Changeling 2v2 test",
      "DocInfo/DescLong": "P1 human and P2 Changeling play on the west team against P3/P4 Changeling on the east team.",
      "Variant001/ModeName": "2 vs 2",
      "Variant001/ModeDesc": "West P1/P2 versus east P3/P4 Pro Bot test",
    },
  };
  for (const [locale, replacements] of Object.entries(localized)) {
    const archiveName = `${locale}.SC2Data\\LocalizedData\\GameStrings.txt`;
    const content = archive.hasFile(archiveName)
      ? archive.readFileAsString(archiveName, "utf8")
      : "";
    archive.addString(archiveName, setLocalizedLines(content, replacements), { encoding: "utf8" });
  }
}

function patchMapScript(script) {
  const customBlock = /\/\/ SC2TEAM_CUSTOM_BEGIN[\s\S]*?\/\/ SC2TEAM_CUSTOM_END/;
  if (!customBlock.test(script)) fail("SC2TEAM custom block is missing");
  const support = `// SC2TEAM_CUSTOM_BEGIN
// Pro Bot v0.2_test: P1/P2 west team, P3/P4 east team.
trigger gt_sc2team_BridgePing;

bool sc2team_BridgePing_Func (bool testConds, bool runActions) {
    if (!runActions) {
        return true;
    }
    // Protocol bridge probe. A successful RequestMapCommand adds exactly 123
    // minerals to P1 so the local controller can verify trigger dispatch.
    PlayerModifyPropertyInt(1, c_playerPropMinerals, c_playerPropOperAdd, 123);
    return true;
}

void sc2team_InitializeProBot2v2 () {
    int firstPlayer;
    int secondPlayer;
    for (firstPlayer = 1; firstPlayer <= 4; firstPlayer += 1) {
        for (secondPlayer = 1; secondPlayer <= 4; secondPlayer += 1) {
            if (firstPlayer == secondPlayer) {
                continue;
            }
            if ((firstPlayer <= 2 && secondPlayer <= 2) ||
                (firstPlayer >= 3 && secondPlayer >= 3)) {
                libNtve_gf_SetAlliance(firstPlayer, secondPlayer, libNtve_ge_AllianceSetting_AllyWithSharedVision);
            }
            else {
                libNtve_gf_SetAlliance(firstPlayer, secondPlayer, libNtve_ge_AllianceSetting_Enemy);
            }
        }
    }
    VisRevealArea(1, RegionEntireMap(), 0.0, false);
    gt_sc2team_BridgePing = TriggerCreate("sc2team_BridgePing_Func");
}
// SC2TEAM_CUSTOM_END`;
  let updated = script.replace(customBlock, support);
  updated = updated.replace(/sc2team_Initialize7v7\(\);/, "sc2team_InitializeProBot2v2();");
  if (!updated.includes("sc2team_InitializeProBot2v2();")) fail("2v2 initialization call is missing");
  if (updated.includes("sc2team_Initialize7v7") || updated.includes("UnitSetPosition")) {
    fail("Obsolete team/start code remains in MapScript.galaxy");
  }
  return updated;
}

function verifyArchive(archive, starts) {
  const attributes = archive.readFileAsString("Attributes", "utf8");
  const script = archive.readFileAsString("MapScript.galaxy", "utf8");
  const players = parseMapInfoPlayers(archive.readFile("MapInfo"));
  const ko = archive.readFileAsString("koKR.SC2Data\\LocalizedData\\GameStrings.txt", "utf8");
  const active = players.filter((player) => player.control === 1).map((player) => player.id);
  if (active.join(",") !== "1,2,3,4") fail(`Expected P1-P4 open, found ${active.join(",")}`);
  for (let index = 0; index < 4; index += 1) {
    if (players.find((player) => player.id === index + 1)?.startPoint !== starts[index].id) {
      fail(`P${index + 1} fixed-start verification failed`);
    }
  }
  for (const expected of [
    '<CategoryId Value="6"/>', '<MaxTeamSize Value="2"/>',
    '<Slot Id="0"/><Value Id="21553"/>',
    '<Slot Id="1"/><Value Id="21553" Index="1"/>',
    '<Slot Id="2"/><Value Id="21554"/>',
    '<Slot Id="3"/><Value Id="21554" Index="1"/>',
  ]) {
    if (!attributes.includes(expected)) fail(`Lobby attribute missing: ${expected}`);
  }
  if (!script.includes("VisRevealArea(1, RegionEntireMap(), 0.0, false);")) fail("P1 full vision is missing");
  if (!script.includes('TriggerCreate("sc2team_BridgePing_Func")')) fail("Map-command bridge trigger is missing");
  if (!ko.includes(`DocInfo/Name=${MAP_NAME_KO}`)) fail("Korean map name is incorrect");
}

function formatStart(start) {
  return `(${start.x}, ${start.y}) id=${start.id}`;
}

function main() {
  const [sourceArg, outputArg] = process.argv.slice(2);
  if (!sourceArg || !outputArg) {
    console.error("Usage: node tools/build_pro_bot_2v2_map.cjs <fixed-teams.SC2Map> <output.SC2Map>");
    process.exit(2);
  }
  const source = path.resolve(sourceArg);
  const output = path.resolve(outputArg);
  if (!fs.existsSync(source)) fail(`Source map not found: ${source}`);
  if (source === output) fail("Source and output paths must be different");

  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "sc2-pro-bot-2v2-"));
  const staged = path.join(tempDir, "map.SC2Map");
  try {
    fs.copyFileSync(source, staged);
    const archive = Archive.open(staged);
    let starts;
    try {
      const mapInfo = archive.readFile("MapInfo");
      const players = parseMapInfoPlayers(mapInfo);
      const locations = readStartLocations(archive.readFileAsString("Objects", "utf8"));
      starts = selectTeamStarts(players, locations);
      archive.addBuffer("MapInfo", patchPlayers(mapInfo, starts));
      archive.addString("Attributes", TWO_V_TWO_ATTRIBUTES, { encoding: "utf8" });
      archive.addString("MapScript.galaxy", patchMapScript(archive.readFileAsString("MapScript.galaxy", "utf8")), { encoding: "utf8" });
      patchLocalization(archive);
      archive.compact();
      verifyArchive(archive, starts);
    } finally {
      archive.close();
    }
    fs.mkdirSync(path.dirname(output), { recursive: true });
    fs.copyFileSync(staged, output);
    console.log(`Built: ${output}`);
    console.log(`Map name: ${MAP_NAME_KO}`);
    console.log(`Team 1 west: P1 ${formatStart(starts[0])}; P2 ${formatStart(starts[1])}`);
    console.log(`Team 2 east: P3 ${formatStart(starts[2])}; P4 ${formatStart(starts[3])}`);
    console.log("P1 full-map vision: enabled");
  } finally {
    fs.rmSync(tempDir, { recursive: true, force: true });
  }
}

try {
  main();
} catch (error) {
  console.error(`ERROR: ${error.message}`);
  process.exitCode = 1;
}
