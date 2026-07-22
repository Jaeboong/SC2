#!/usr/bin/env node

const fs = require("node:fs");
const path = require("node:path");
const { Archive } = require("@jamiephan/stormlib");

function fail(message) {
  console.error(`ERROR: ${message}`);
  process.exit(1);
}

const [sourceArg, outputArg, buildsArg] = process.argv.slice(2);
if (!sourceArg || !outputArg || !buildsArg) {
  fail("Usage: configure_team_map.cjs <source> <output> <13 comma-separated build IDs>");
}

const builds = buildsArg.split(",").map(Number);
if (builds.length !== 13 || builds.some((value) => !Number.isInteger(value))) {
  fail("Exactly thirteen integer build IDs are required for P2 through P14");
}

const source = path.resolve(sourceArg);
const output = path.resolve(outputArg);
fs.mkdirSync(path.dirname(output), { recursive: true });
fs.copyFileSync(source, output);

const archive = Archive.open(output);
try {
  let script = archive.readFileAsString("MapScript.galaxy", "utf8");
  const blockPattern = /(\/\/ SC2TEAM_GROUND_BUILD_CALLS_BEGIN)[\s\S]*?(\/\/ SC2TEAM_GROUND_BUILD_CALLS_END)/;
  if (!blockPattern.test(script)) {
    fail("The source map does not contain the ground-build configuration block");
  }
  const calls = builds
    .map((build, index) => `    sc2team_SetGroundBuild(${index + 2}, ${build});`)
    .join("\n");
  script = script.replace(blockPattern, `$1\n${calls}\n$2`);
  archive.addString("MapScript.galaxy", script, { encoding: "utf8" });
  archive.compact();
} finally {
  archive.close();
}

console.log(output);
