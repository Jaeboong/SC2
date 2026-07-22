#!/usr/bin/env node

const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { Archive } = require("@jamiephan/stormlib");

const MAP_NAME_KO = "유럽 섬멸전 Pro Bot_test";
const MAP_NAME_EN = "Europe Melee Pro Bot_test";

const ONE_V_ONE_ATTRIBUTES = `<?xml version="1.0" encoding="utf-8"?>
<Attributes>
    <DefaultVariants Value="0"/>
    <Variant>
        <Id Value="1"/>
        <CategoryId Value="6"/>
        <ModeId Value="1"/>
        <ModeName Value="Variant001/ModeName"/>
        <ModeDesc Value="Variant001/ModeDesc"/>
        <MaxTeamSize Value="1"/>
        <AttributeHidden Namespace="999" Id="3006"/>
        <Attribute Namespace="999" Id="1001">
            <Default><Slot Id="Global"/><Value Id="28271"/></Default>
        </Attribute>
        <Attribute Namespace="999" Id="2000">
            <Default><Slot Id="Global"/><Value Id="29746"/></Default>
        </Attribute>
        <Attribute Namespace="999" Id="2011">
            <Default><Slot Id="0"/><Value Id="21553"/></Default>
            <Default><Slot Id="1"/><Value Id="21554"/></Default>
        </Attribute>
    </Variant>
</Attributes>
`;

function fail(message) {
  throw new Error(message);
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

  if (buffer.subarray(0, 4).toString("ascii") !== "IpaM") {
    fail("Unsupported MapInfo magic");
  }
  offset = 4;
  const version = readU32();
  if (version !== 0x27) {
    fail(`Unsupported MapInfo version 0x${version.toString(16)}`);
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
  const points = [];
  const pattern = /<ObjectPoint\b[^>]*\bType="StartLoc"[^>]*\/?\s*>/g;
  for (const match of objectsXml.matchAll(pattern)) {
    const idMatch = /\bId="(\d+)"/.exec(match[0]);
    const positionMatch = /\bPosition="([^"]+)"/.exec(match[0]);
    if (!idMatch || !positionMatch) fail("StartLoc is missing its id or position");
    const [x, y] = positionMatch[1].split(",").map(Number);
    points.push({ id: Number(idMatch[1]), x, y });
  }
  if (points.length < 14) fail(`Expected at least 14 StartLoc objects, found ${points.length}`);
  return points;
}

function chooseOneVsOneStarts(points) {
  const ordered = [...points].sort((a, b) => a.x - b.x || a.y - b.y);
  const west = ordered.slice(0, 7).sort((a, b) => a.y - b.y);
  const east = ordered.slice(-7).sort((a, b) => a.y - b.y);
  // Use the middle base on each side. This keeps both players far apart while
  // avoiding the extreme corner bases of the original 14-player layout.
  return { player1: west[3], player2: east[3] };
}

function patchPlayers(mapInfo, player1Start, player2Start) {
  const players = parseMapInfoPlayers(mapInfo);
  for (const player of players) {
    if (player.id === 1 || player.id === 2) {
      mapInfo.writeUInt32LE(1, player.controlOffset); // User/open lobby slot.
      mapInfo.writeUInt32LE(
        player.id === 1 ? player1Start.id : player2Start.id,
        player.startPointOffset
      );
    } else if (player.id >= 3 && player.id <= 14) {
      mapInfo.writeUInt32LE(0, player.controlOffset); // None/closed slot.
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
    const value = pending.get(key);
    pending.delete(key);
    const prefix = line.startsWith("\uFEFF") ? "\uFEFF" : "";
    return `${prefix}${key}=${value}`;
  });
  for (const [key, value] of pending) updated.push(`${key}=${value}`);
  return updated.join(newline);
}

function patchLocalization(archive) {
  const localized = {
    koKR: {
      "DocInfo/Name": MAP_NAME_KO,
      "DocInfo/DescShort": "사람 대 Pro Bot 1대1 관전 테스트",
      "DocInfo/DescLong": "사람(P1)이 전장 전체를 보면서 Pro Bot(P2)의 동작을 확인하는 1대1 테스트 맵입니다.",
      "Variant001/ModeName": "1 대 1",
      "Variant001/ModeDesc": "사람과 Pro Bot이 대결하는 전체 시야 테스트용 섬멸전입니다.",
    },
    enUS: {
      "DocInfo/Name": MAP_NAME_EN,
      "DocInfo/DescShort": "Human vs Pro Bot 1v1 vision test",
      "DocInfo/DescLong": "A 1v1 test map where human player 1 can observe the entire battlefield while playing against Pro Bot player 2.",
      "Variant001/ModeName": "1 vs 1",
      "Variant001/ModeDesc": "A melee test match with full-map vision for the human player.",
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

function patchMapScript(script) {
  const customBlock = /\/\/ SC2TEAM_CUSTOM_BEGIN[\s\S]*?\/\/ SC2TEAM_CUSTOM_END/;
  if (!customBlock.test(script)) fail("SC2TEAM custom block is missing");

  const support = `// SC2TEAM_CUSTOM_BEGIN
// Pro Bot test: P1 human in the west, P2 bot in the east.
void sc2team_InitializeProBotTest () {
    libNtve_gf_SetAlliance(1, 2, libNtve_ge_AllianceSetting_Enemy);
    libNtve_gf_SetAlliance(2, 1, libNtve_ge_AllianceSetting_Enemy);
    // A duration of 0 permanently reveals the complete map to the human only.
    VisRevealArea(1, RegionEntireMap(), 0.0, false);
}
// SC2TEAM_CUSTOM_END`;

  let updated = script.replace(customBlock, support);
  updated = updated.replace(/\s*sc2team_Initialize7v7\(\);/, "\n    sc2team_InitializeProBotTest();");
  if (!updated.includes("sc2team_InitializeProBotTest();")) {
    fail("Could not replace the 7v7 initialization call");
  }
  if (updated.includes("sc2team_Initialize7v7") || updated.includes("UnitSetPosition")) {
    fail("Obsolete team/start code remains in MapScript.galaxy");
  }
  return updated;
}

function verifyArchive(archive, player1Start, player2Start) {
  const attributes = archive.readFileAsString("Attributes", "utf8");
  const script = archive.readFileAsString("MapScript.galaxy", "utf8");
  const ko = archive.readFileAsString(
    "koKR.SC2Data\\LocalizedData\\GameStrings.txt",
    "utf8"
  );
  const players = parseMapInfoPlayers(archive.readFile("MapInfo"));

  if (!attributes.includes('<CategoryId Value="6"/>') ||
      !attributes.includes('<MaxTeamSize Value="1"/>')) {
    fail("The 1v1 melee lobby variant was not written correctly");
  }
  if (!script.includes("VisRevealArea(1, RegionEntireMap(), 0.0, false);")) {
    fail("Permanent full-map vision for player 1 is missing");
  }
  if (!ko.includes(`DocInfo/Name=${MAP_NAME_KO}`)) fail("Korean map name is incorrect");

  const active = players.filter((player) => player.control === 1).map((player) => player.id);
  if (active.length !== 2 || active[0] !== 1 || active[1] !== 2) {
    fail(`Expected only P1 and P2 to be open, found: ${active.join(", ")}`);
  }
  if (players.find((player) => player.id === 1)?.startPoint !== player1Start.id ||
      players.find((player) => player.id === 2)?.startPoint !== player2Start.id) {
    fail("P1/P2 fixed start-point verification failed");
  }
}

function main() {
  const [sourceArg, outputArg] = process.argv.slice(2);
  if (!sourceArg || !outputArg) {
    console.error("Usage: node tools/build_pro_bot_test_map.cjs <source.SC2Map> <output.SC2Map>");
    process.exit(2);
  }

  const source = path.resolve(sourceArg);
  const output = path.resolve(outputArg);
  if (!fs.existsSync(source)) fail(`Source map not found: ${source}`);
  if (source === output) fail("Source and output paths must be different");

  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "sc2-pro-bot-test-"));
  const staged = path.join(tempDir, "map.SC2Map");
  try {
    fs.copyFileSync(source, staged);
    const archive = Archive.open(staged);
    let player1Start;
    let player2Start;
    try {
      const points = readStartLocations(archive.readFileAsString("Objects", "utf8"));
      ({ player1: player1Start, player2: player2Start } = chooseOneVsOneStarts(points));

      archive.addBuffer(
        "MapInfo",
        patchPlayers(archive.readFile("MapInfo"), player1Start, player2Start)
      );
      archive.addString("Attributes", ONE_V_ONE_ATTRIBUTES, { encoding: "utf8" });
      archive.addString(
        "MapScript.galaxy",
        patchMapScript(archive.readFileAsString("MapScript.galaxy", "utf8")),
        { encoding: "utf8" }
      );
      patchLocalization(archive);
      archive.compact();
      verifyArchive(archive, player1Start, player2Start);
    } finally {
      archive.close();
    }

    fs.mkdirSync(path.dirname(output), { recursive: true });
    fs.copyFileSync(staged, output);
    console.log(`Built: ${output}`);
    console.log(`Map name: ${MAP_NAME_KO}`);
    console.log(`P1 human start: (${player1Start.x}, ${player1Start.y}) id=${player1Start.id}`);
    console.log(`P2 Pro Bot start: (${player2Start.x}, ${player2Start.y}) id=${player2Start.id}`);
    console.log("Lobby: melee 1 vs 1; only P1 and P2 are open");
    console.log("Human vision: entire map permanently revealed to P1");
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
