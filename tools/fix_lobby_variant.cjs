#!/usr/bin/env node

const fs = require("node:fs");
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
        <MaxTeamSize Value="4"/>
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
            <Default><Slot Id="4"/><Value Id="21554"/></Default>
            <Default><Slot Id="5"/><Value Id="21554" Index="1"/></Default>
            <Default><Slot Id="6"/><Value Id="21554" Index="2"/></Default>
            <Default><Slot Id="7"/><Value Id="21554" Index="3"/></Default>
        </Attribute>
    </Variant>
</Attributes>
`;

function fail(message) {
  console.error(`ERROR: ${message}`);
  process.exit(1);
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
  for (const [key, value] of pending) {
    updated.push(`${key}=${value}`);
  }
  return updated.join(newline);
}

const [sourceArg, outputArg] = process.argv.slice(2);
if (!sourceArg || !outputArg) {
  fail("Usage: node tools/fix_lobby_variant.cjs <source.SC2Map> <output.SC2Map>");
}

const source = path.resolve(sourceArg);
const output = path.resolve(outputArg);
if (!fs.existsSync(source)) fail(`Source map not found: ${source}`);
if (source === output) fail("Source and output paths must be different");

fs.mkdirSync(path.dirname(output), { recursive: true });
fs.copyFileSync(source, output);

const archive = Archive.open(output);
try {
  archive.addString("Attributes", ATTRIBUTES, { encoding: "utf8" });

  const localized = {
    koKR: {
      "Variant001/ModeName": "4 대 4",
      "Variant001/ModeDesc": "두 팀이 각각 네 명으로 나뉘어 싸우는 섬멸전입니다.",
    },
    enUS: {
      "Variant001/ModeName": "4 vs 4",
      "Variant001/ModeDesc": "Two teams of four players fight a melee match.",
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
  archive.compact();
} finally {
  archive.close();
}

console.log(`Fixed lobby variant: ${output}`);
console.log("Category: melee, mode: 4 vs 4, max team size: 4");
