#!/usr/bin/env node

const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { Archive } = require("@jamiephan/stormlib");

const ATTRIBUTES = `<?xml version="1.0" encoding="utf-8"?>
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

function fail(message) {
  throw new Error(message);
}

function extractStartLocations(objectsXml) {
  const points = [];
  const pattern = /<ObjectPoint\b[^>]*\bType="StartLoc"[^>]*\/?\s*>/g;
  for (const match of objectsXml.matchAll(pattern)) {
    const position = /\bPosition="([^"]+)"/.exec(match[0]);
    if (!position) fail("StartLoc without a Position attribute");
    const [x, y] = position[1].split(",").map(Number);
    if (!Number.isFinite(x) || !Number.isFinite(y)) {
      fail(`Invalid StartLoc position: ${position[1]}`);
    }
    points.push({ x, y });
  }
  return points;
}

function chooseSideLocations(startLocations) {
  if (startLocations.length < 14) {
    fail(`At least 14 start locations are required; found ${startLocations.length}`);
  }
  const ordered = [...startLocations].sort((a, b) => a.x - b.x || a.y - b.y);
  return {
    west: ordered.slice(0, 7).sort((a, b) => a.y - b.y),
    east: ordered.slice(-7).sort((a, b) => a.y - b.y),
  };
}

function galaxyPoint(point) {
  return `Point(${point.x.toFixed(1)}, ${point.y.toFixed(1)})`;
}

function makeGalaxySupport(west, east) {
  const moves = [...west, ...east]
    .map(
      (point, index) =>
        `    sc2team_MovePlayerStart(${index + 1}, ${galaxyPoint(point)});`
    )
    .join("\n");

  return `// SC2TEAM_CUSTOM_BEGIN
// Player 1-7: west team. Player 8-14: east team.
void sc2team_MovePlayerStart (int player, point destination) {
    point source;
    unitgroup startUnits;
    int unitIndex;
    unit currentUnit;
    point currentPosition;

    source = PlayerStartLocation(player);
    startUnits = UnitGroup(null, player, RegionCircle(source, 15.0), UnitFilter(0, 0, 0, 0), 0);
    unitIndex = UnitGroupCount(startUnits, c_unitCountAll);

    for (;; unitIndex -= 1) {
        currentUnit = UnitGroupUnitFromEnd(startUnits, unitIndex);
        if (currentUnit == null) {
            break;
        }
        currentPosition = UnitGetPosition(currentUnit);
        UnitSetPosition(
            currentUnit,
            PointWithOffset(
                destination,
                PointGetX(currentPosition) - PointGetX(source),
                PointGetY(currentPosition) - PointGetY(source)
            ),
            false
        );
    }
    CameraPan(player, destination, 0.0, -1, 10.0, false);
}

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

${moves}
}
// SC2TEAM_CUSTOM_END`;
}

function patchMapScript(script, west, east) {
  const blockPattern = /\/\/ SC2TEAM_CUSTOM_BEGIN[\s\S]*?\/\/ SC2TEAM_CUSTOM_END/;
  if (!blockPattern.test(script)) {
    fail("The source map does not contain the SC2TEAM custom block");
  }
  let updated = script.replace(blockPattern, makeGalaxySupport(west, east));
  updated = updated.replace(
    /sc2team_Initialize4v4\s*\(\s*\)\s*;/g,
    "sc2team_Initialize7v7();"
  );
  if (!updated.includes("sc2team_Initialize7v7();")) {
    fail("Could not update the map initialization call to 7v7");
  }
  return updated;
}

function setLocalizedLines(content, replacements) {
  const newline = content.includes("\r\n") ? "\r\n" : "\n";
  const lines = content.split(/\r?\n/);
  const pending = new Map(Object.entries(replacements));
  const updated = lines.map((line) => {
    const separator = line.indexOf("=");
    if (separator < 0) return line;
    const key = line.slice(0, separator);
    if (!pending.has(key)) return line;
    const value = pending.get(key);
    pending.delete(key);
    return `${key}=${value}`;
  });
  for (const [key, value] of pending) updated.push(`${key}=${value}`);
  return updated.join(newline);
}

function patchLobby(archive) {
  archive.addString("Attributes", ATTRIBUTES, { encoding: "utf8" });
  const locales = {
    koKR: {
      "Variant001/ModeName": "7 대 7",
      "Variant001/ModeDesc": "두 팀이 각각 일곱 명으로 나뉘어 싸우는 섬멸전입니다.",
    },
    enUS: {
      "Variant001/ModeName": "7 vs 7",
      "Variant001/ModeDesc": "Two teams of seven players fight a melee match.",
    },
  };
  for (const [locale, replacements] of Object.entries(locales)) {
    const name = `${locale}.SC2Data\\LocalizedData\\GameStrings.txt`;
    const content = archive.hasFile(name)
      ? archive.readFileAsString(name, "utf8")
      : "";
    archive.addString(name, setLocalizedLines(content, replacements), {
      encoding: "utf8",
    });
  }
}

function formatPoint(point) {
  return `(${point.x.toFixed(1)}, ${point.y.toFixed(1)})`;
}

const [sourceArg, outputArg] = process.argv.slice(2);
if (!sourceArg || !outputArg) {
  console.error("Usage: node tools/expand_to_7v7.cjs <source.SC2Map> <output.SC2Map>");
  process.exit(2);
}

const source = path.resolve(sourceArg);
const output = path.resolve(outputArg);
if (!fs.existsSync(source)) fail(`Source map not found: ${source}`);
if (source === output) fail("Source and output paths must be different");

const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "sc2team-7v7-"));
const staged = path.join(tempDir, "map.SC2Map");
try {
  fs.copyFileSync(source, staged);
  const archive = Archive.open(staged);
  let west;
  let east;
  let startCount;
  try {
    const objects = archive.readFileAsString("Objects", "utf8");
    const starts = extractStartLocations(objects);
    startCount = starts.length;
    ({ west, east } = chooseSideLocations(starts));
    const script = archive.readFileAsString("MapScript.galaxy", "utf8");
    archive.addString("MapScript.galaxy", patchMapScript(script, west, east), {
      encoding: "utf8",
    });
    patchLobby(archive);
    archive.compact();
  } finally {
    archive.close();
  }

  fs.mkdirSync(path.dirname(output), { recursive: true });
  fs.copyFileSync(staged, output);
  console.log(`Expanded: ${output}`);
  console.log(`Start locations preserved: ${startCount}`);
  console.log(`West P1-P7: ${west.map(formatPoint).join(", ")}`);
  console.log(`East P8-P14: ${east.map(formatPoint).join(", ")}`);
  console.log("Lobby variant: melee 7 vs 7, max team size 7");
  console.log(
    "Next: run tools/fix_player_starts.cjs before playing or publishing this map"
  );
} finally {
  fs.rmSync(tempDir, { recursive: true, force: true });
}
