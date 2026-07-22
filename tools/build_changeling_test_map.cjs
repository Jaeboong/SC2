#!/usr/bin/env node

const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { Archive } = require("@jamiephan/stormlib");

const RESOURCE_AMOUNT = 50000;
const MAP_NAME_KO = "Torches LE Pro Bot_test";
const MAP_NAME_EN = "Torches LE Pro Bot_test";
const RESOURCE_REPLACEMENTS = new Map([
  ["MineralField", "RichMineralField"],
  ["MineralField750", "RichMineralField750"],
  ["VespeneGeyser", "RichVespeneGeyser"],
  ["ProtossVespeneGeyser", "RichVespeneGeyser"],
  ["SpacePlatformGeyser", "RichVespeneGeyser"],
]);
const RESOURCE_TYPES = new Set([
  "RichMineralField",
  "RichMineralField750",
  "PurifierRichMineralField",
  "RichVespeneGeyser",
]);

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

function makeResourcesRich(objects) {
  let updated = objects.replace(
    /(<ObjectUnit\b[^>]*\bUnitType=")([^"]+)(")/g,
    (whole, prefix, type, suffix) =>
      RESOURCE_REPLACEMENTS.has(type)
        ? `${prefix}${RESOURCE_REPLACEMENTS.get(type)}${suffix}`
        : whole
  );
  let count = 0;
  updated = updated.replace(/<ObjectUnit\b[^>]*>/g, (objectUnit) => {
    const type = /\bUnitType="([^"]+)"/.exec(objectUnit)?.[1];
    if (!RESOURCE_TYPES.has(type)) return objectUnit;
    count += 1;
    if (/\bResources="[^"]*"/.test(objectUnit)) {
      return objectUnit.replace(/\bResources="[^"]*"/, `Resources="${RESOURCE_AMOUNT}"`);
    }
    return objectUnit.replace(/(\/?)>$/, ` Resources="${RESOURCE_AMOUNT}"$1>`);
  });
  return { updated, count };
}

function workerSupplyOverride() {
  return `<?xml version="1.0" encoding="utf-8"?>
<Catalog>
    <CUnit id="Drone"><Food value="0"/></CUnit>
    <CUnit id="Probe"><Food value="0"/></CUnit>
    <CUnit id="SCV"><Food value="0"/></CUnit>
</Catalog>
`;
}

function patchMapScript(script) {
  if (script.includes("SC2TEAM_PRO_BOT_TEST_BEGIN")) {
    fail("The source map has already been patched");
  }
  const includeLine = 'include "TriggerLibs/NativeLib"';
  if (!script.includes(includeLine)) fail("NativeLib include is missing");
  const support = `

// SC2TEAM_PRO_BOT_TEST_BEGIN
void sc2team_InitializeProBotTest () {
    // Permanent full-map vision for the human P1 only.
    VisRevealArea(1, RegionEntireMap(), 0.0, false);
}
// SC2TEAM_PRO_BOT_TEST_END`;
  let updated = script.replace(includeLine, `${includeLine}${support}`);
  const optionsCall = /MeleeInitOptions\(\);/;
  if (!optionsCall.test(updated)) fail("MeleeInitOptions call is missing");
  updated = updated.replace(
    optionsCall,
    "MeleeInitOptions();\n    sc2team_InitializeProBotTest();"
  );
  return updated;
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
      "DocInfo/DescShort": "사람 대 Changeling 1대1 전체 시야 테스트",
      "DocInfo/DescLong": "Changeling 호환 1대1 지도입니다. 사람 P1에게만 전장 전체 시야가 제공됩니다.",
      "Variant001/ModeName": "1 대 1",
      "Variant001/ModeDesc": "사람과 Pro Bot이 대결하는 전체 시야 테스트용 섬멸전입니다.",
    },
    enUS: {
      "DocInfo/Name": MAP_NAME_EN,
      "DocInfo/DescShort": "Human vs Changeling full-vision test",
      "DocInfo/DescLong": "A Changeling-compatible 1v1 test map with permanent full-map vision for human player 1 only.",
      "Variant001/ModeName": "1 vs 1",
      "Variant001/ModeDesc": "A full-vision melee test match against a Pro Bot.",
    },
  };
  for (const [locale, replacements] of Object.entries(localized)) {
    const name = `${locale}.SC2Data\\LocalizedData\\GameStrings.txt`;
    const content = archive.hasFile(name)
      ? archive.readFileAsString(name, "utf8")
      : "";
    archive.addString(name, setLocalizedLines(content, replacements), {
      encoding: "utf8",
    });
  }
}

function verify(archive, resourceCount) {
  const objects = archive.readFileAsString("Objects", "utf8");
  const script = archive.readFileAsString("MapScript.galaxy", "utf8");
  const ko = archive.readFileAsString(
    "koKR.SC2Data\\LocalizedData\\GameStrings.txt",
    "utf8"
  );
  const startCount = (objects.match(/Type="StartLoc"/g) || []).length;
  const amountCount = (objects.match(/Resources="50000"/g) || []).length;
  if (startCount !== 2) fail(`Expected exactly two start locations, found ${startCount}`);
  if (amountCount !== resourceCount || resourceCount === 0) {
    fail(`Resource amount verification failed: ${amountCount}/${resourceCount}`);
  }
  if (!script.includes("VisRevealArea(1, RegionEntireMap(), 0.0, false);")) {
    fail("P1 permanent full-map vision is missing");
  }
  if (!ko.includes(`DocInfo/Name=${MAP_NAME_KO}`)) fail("Map name is incorrect");
}

function main() {
  const [sourceArg, outputArg] = process.argv.slice(2);
  if (!sourceArg || !outputArg) {
    console.error("Usage: node tools/build_changeling_test_map.cjs <source.SC2Map> <output.SC2Map>");
    process.exit(2);
  }
  const source = path.resolve(sourceArg);
  const output = path.resolve(outputArg);
  if (!fs.existsSync(source)) fail(`Source map not found: ${source}`);
  if (source === output) fail("Source and output must be different files");

  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "changeling-map-"));
  const staged = path.join(tempDir, "map.SC2Map");
  try {
    fs.copyFileSync(source, staged);
    const archive = Archive.open(staged);
    let resourceCount;
    try {
      const resources = makeResourcesRich(
        archive.readFileAsString("Objects", "utf8")
      );
      resourceCount = resources.count;
      archive.addString("Objects", resources.updated, { encoding: "utf8" });
      archive.addString(
        "Base.SC2Data\\GameData\\UnitData.xml",
        workerSupplyOverride(),
        { encoding: "utf8" }
      );
      archive.addString(
        "MapScript.galaxy",
        patchMapScript(archive.readFileAsString("MapScript.galaxy", "utf8")),
        { encoding: "utf8" }
      );
      archive.addString("Attributes", ONE_V_ONE_ATTRIBUTES, { encoding: "utf8" });
      patchLocalization(archive);
      archive.compact();
      verify(archive, resourceCount);
    } finally {
      archive.close();
    }

    fs.mkdirSync(path.dirname(output), { recursive: true });
    fs.copyFileSync(staged, output);
    console.log(`Built: ${output}`);
    console.log(`Map name: ${MAP_NAME_KO}`);
    console.log("Start locations: 2");
    console.log(`Rich resources: ${resourceCount} fields/geysers set to ${RESOURCE_AMOUNT}`);
    console.log("Worker supply: Drone=0, Probe=0, SCV=0");
    console.log("Human vision: entire map permanently revealed to P1 only");
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
