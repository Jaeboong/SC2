#!/usr/bin/env node

const path = require("node:path");
const { Archive } = require("@jamiephan/stormlib");

const [mapArg, ...entries] = process.argv.slice(2);
if (!mapArg || entries.length === 0) {
  console.error("Usage: node tools/inspect_map_entries.cjs <map.SC2Map> <entry> [...]");
  process.exit(2);
}

const archive = Archive.open(path.resolve(mapArg));
try {
  for (const entry of entries) {
    console.log(`===== ${entry} =====`);
    if (!archive.hasFile(entry)) {
      console.log("<missing>");
      continue;
    }
    console.log(archive.readFileAsString(entry, "utf8"));
  }
} finally {
  archive.close();
}
