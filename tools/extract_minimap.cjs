#!/usr/bin/env node
// 맵 아카이브에서 Minimap.tga 를 그대로 꺼낸다.
//
//   node tools/extract_minimap.cjs <맵.SC2Map> <출력.tga>
//
// MPQ 접근은 node 쪽 stormlib 만 할 수 있고 이미지 합성은 Python 이 한다.
// 이 스크립트는 그 경계에서 바이트만 옮기는 역할이며, 변환·리사이즈를 하지
// 않는다 — TGA 헤더의 크기와 원점 플래그가 좌표 변환의 근거이기 때문이다.

const fs = require("node:fs");
const path = require("node:path");

const { Archive } = require("@jamiephan/stormlib");

const MINIMAP_FILE = "Minimap.tga";

const [mapPath, outputPath] = process.argv.slice(2);
if (!mapPath || !outputPath) {
  console.error("Usage: node tools/extract_minimap.cjs <map.SC2Map> <output.tga>");
  process.exit(2);
}

let archive;
try {
  archive = Archive.open(mapPath);
} catch (error) {
  console.error(`맵을 열 수 없다: ${error.message}`);
  process.exit(1);
}

try {
  if (!archive.hasFile(MINIMAP_FILE)) {
    console.error(`${path.basename(mapPath)} 에는 ${MINIMAP_FILE} 이 없다`);
    process.exit(3);
  }
  fs.mkdirSync(path.dirname(outputPath), { recursive: true });
  fs.writeFileSync(outputPath, archive.readFile(MINIMAP_FILE));
} finally {
  archive.close();
}

console.log(outputPath);
