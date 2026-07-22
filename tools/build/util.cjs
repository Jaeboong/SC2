// 빌더 공용 유틸. 다른 build/ 모듈이 모두 의존하므로 이 파일은 어떤
// build/ 모듈도 require 하지 않는다(순환 참조 방지).

const fs = require("node:fs");
const path = require("node:path");

// 이 모듈은 tools/build/에 있으므로 tools/는 한 단계, 프로젝트 루트는 두
// 단계 위다. 경로 상수를 여기서만 정의해 각 모듈이 __dirname을 재해석하지
// 않게 한다(파일을 옮길 때 조용히 깨지는 지점).
const TOOLS_DIR = path.join(__dirname, "..");
const PROJECT_ROOT = path.join(__dirname, "..", "..");
const GALAXY_DIR = path.join(TOOLS_DIR, "galaxy");
const CAMPAIGN_DATA_DIR = path.join(TOOLS_DIR, "campaign_data");

function fail(message) {
  throw new Error(message);
}

// 보간이 없는 큰 Galaxy 블록은 .galaxy 파일로 분리한다(문법 하이라이팅과
// 사람이 읽는 diff를 얻는다). JS 템플릿 리터럴은 ECMAScript 사양상 CRLF를
// LF로 정규화하므로, 파일에서 읽을 때도 같은 정규화를 해야 산출물이 바이트
// 단위로 동일하다 — 이 정규화를 빼면 CRLF 체크아웃에서 맵이 달라진다.
function readGalaxyTemplate(name) {
  return fs
    .readFileSync(path.join(GALAXY_DIR, `${name}.galaxy`), "utf8")
    .replace(/\r\n/g, "\n");
}

module.exports = {
  TOOLS_DIR,
  PROJECT_ROOT,
  GALAXY_DIR,
  CAMPAIGN_DATA_DIR,
  fail,
  readGalaxyTemplate,
};
