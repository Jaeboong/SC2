#!/usr/bin/env node
// 맵 능력 판정 CLI. 런처가 목록을 만들 때 쓴다.
//
//   node tools/map_capabilities.cjs <맵 또는 디렉터리> [...]
//
// 표준출력에 JSON 배열 하나를 낸다. 읽을 수 없는 맵도 배열에 남고
// readable:false 와 reason 을 실어 보낸다 — 런처가 왜 못 쓰는지 보여줘야
// 하기 때문에 조용히 빠뜨리지 않는다.

const fs = require("node:fs");
const path = require("node:path");

const {
  maxTeamsFor,
  readMapCapabilities,
} = require("./build/map_capabilities.cjs");

function usage() {
  console.error("Usage: node tools/map_capabilities.cjs <map.SC2Map|directory> [...]");
}

function expand(target) {
  let stat;
  try {
    stat = fs.statSync(target);
  } catch (error) {
    return [];
  }
  if (stat.isDirectory()) {
    return fs
      .readdirSync(target)
      .filter((name) => name.endsWith(".SC2Map"))
      .sort()
      .map((name) => path.join(target, name));
  }
  return [target];
}

const targets = process.argv.slice(2);
if (targets.length === 0) {
  usage();
  process.exit(2);
}

const report = [];
for (const target of targets.flatMap(expand)) {
  const capabilities = readMapCapabilities(target);
  report.push({
    name: path.basename(target, ".SC2Map"),
    path: capabilities.path,
    readable: capabilities.readable,
    reason: capabilities.reason,
    mapInfoSlots: capabilities.mapInfoSlots,
    maxPlayers: capabilities.maxPlayers,
    maxTeams: maxTeamsFor(capabilities.maxPlayers),
    startLocations: capabilities.startLocations,
    playerStarts: capabilities.playerStarts,
    wildZergTownHalls: capabilities.wildZergTownHalls,
    prepared: capabilities.prepared,
    preparable: capabilities.preparable,
  });
}
process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
