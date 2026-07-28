// 임의의 .SC2Map 이 우리 계층을 얼마나 받아줄 수 있는지 읽기 전용으로 잰다.
//
// 여기서 나오는 값이 런처가 "이 맵으로 몇 명, 몇 팀, 야생 저그 가능?"을
// 판단하는 유일한 근거다. 맵을 고치지 않으며, 실패해도 예외를 던지지 않고
// 이유를 실어 돌려준다 — 런처가 목록의 나머지 맵을 계속 보여줘야 한다.
//
// 수용 인원의 상한은 맵이 정한다. MapInfo 의 슬롯 수에서 중립·적대 두
// 슬롯을 뺀 값이며, 전 맵에서 예외 없이 성립함을 확인했다(유럽 16->14,
// Flat128 6->4, Simple64 4->2). 슬롯을 새로 만드는 경로는 없다.

const { Archive } = require("@jamiephan/stormlib");

const { readMapInfoGeometry, readMapInfoPlayers } = require("./mapinfo.cjs");

// 맵 아카이브가 들고 있는 미니맵 텍스처. 에디터가 저장할 때 만든다.
const MINIMAP_FILE = "Minimap.tga";

// 논리 슬롯 P1~P14. P15 는 야생 저그, P16 은 중립이라 사람/커스텀 AI 가
// 앉을 수 없다.
const FIRST_PLAYER_SLOT = 1;
const LAST_PLAYER_SLOT = 14;

const WILD_ZERG_PLAYER = 15;
const ZERG_TOWN_HALLS = new Set(["Hatchery", "Lair", "Hive"]);

const CUSTOM_BLOCK_MARKER = "SC2TEAM_CUSTOM_BEGIN";
const NATIVE_LIB_INCLUDE = 'include "TriggerLibs/NativeLib"';
const STANDARD_MELEE_INIT =
  /MeleeInitResources\(\);\s*MeleeInitUnits\(\);\s*MeleeInitAI\(\);\s*MeleeInitOptions\(\);/;

function readStartLocations(objectsXml) {
  const points = [];
  for (const match of objectsXml.matchAll(
    /<ObjectPoint\b[^>]*\bType="StartLoc"[^>]*\/?\s*>/g
  )) {
    const position = /\bPosition="([^"]+)"/.exec(match[0]);
    const id = /\bId="(\d+)"/.exec(match[0]);
    if (!position || !id) continue;
    const [x, y] = position[1].split(",").map(Number);
    if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
    points.push({ id: Number(id[1]), x, y });
  }
  return points;
}

function countWildZergTownHalls(objectsXml) {
  let count = 0;
  for (const match of objectsXml.matchAll(/<ObjectUnit\b[^>]*\/?>/g)) {
    const player = /\bPlayer="(\d+)"/.exec(match[0]);
    const unitType = /\bUnitType="([^"]+)"/.exec(match[0]);
    if (!player || !unitType) continue;
    if (Number(player[1]) !== WILD_ZERG_PLAYER) continue;
    if (ZERG_TOWN_HALLS.has(unitType[1])) count += 1;
  }
  return count;
}

// 야생 저그는 두 가지를 동시에 요구한다. 선배치된 P15 저그 본진이 있어야
// 하고(없으면 중립 적대는 전투 유닛을 한 기도 못 만든다 — §90), 활성
// 플레이어가 쓰고 남은 StartLoc 이 하나 있어야 한다(P15 를 로비 Computer 로
// 승격시킬 때 그 자리를 준다).
function wildZergAvailability(capabilities, activePlayerCount) {
  if (!capabilities.readable) {
    return { available: false, reason: "MapInfo 를 읽을 수 없다" };
  }
  if (capabilities.wildZergTownHalls < 1) {
    return { available: false, reason: "맵에 P15 소유 저그 본진이 없다" };
  }
  if (capabilities.startLocations.length <= activePlayerCount) {
    return {
      available: false,
      reason: `여분 시작 지점이 없다 (시작 지점 ${capabilities.startLocations.length}, 활성 플레이어 ${activePlayerCount})`,
    };
  }
  return { available: true, reason: "" };
}

// 플레이어 수에 따른 팀 수 상한. 2명은 2팀, 3명은 3팀, 4명부터 4팀이다.
// 팀이 플레이어보다 많으면 빈 팀이 생겨 승리 판정이 이상해진다.
function maxTeamsFor(playerCount) {
  if (playerCount < 2) return 0;
  return Math.min(4, playerCount);
}

function readMapCapabilities(mapPath) {
  const capabilities = {
    path: mapPath,
    readable: false,
    reason: "",
    mapInfoSlots: 0,
    maxPlayers: 0,
    geometry: null,
    startLocations: [],
    playerStarts: [],
    wildZergTownHalls: 0,
    hasMinimap: false,
    prepared: false,
    preparable: false,
  };

  let archive;
  try {
    archive = Archive.open(mapPath);
  } catch (error) {
    capabilities.reason = `맵을 열 수 없다: ${error.message}`;
    return capabilities;
  }

  let playerSlots = [];
  try {
    try {
      const mapInfo = archive.readFile("MapInfo");
      const players = readMapInfoPlayers(mapInfo);
      capabilities.geometry = readMapInfoGeometry(mapInfo);
      capabilities.mapInfoSlots = players.length;
      playerSlots = players.filter(
        (player) => player.id >= FIRST_PLAYER_SLOT && player.id <= LAST_PLAYER_SLOT
      );
      capabilities.maxPlayers = playerSlots.length;
    } catch (error) {
      capabilities.reason = `MapInfo 를 읽을 수 없다: ${error.message}`;
      return capabilities;
    }

    try {
      const objects = archive.readFileAsString("Objects", "utf8");
      capabilities.startLocations = readStartLocations(objects);
      capabilities.wildZergTownHalls = countWildZergTownHalls(objects);
    } catch (error) {
      capabilities.reason = `Objects 를 읽을 수 없다: ${error.message}`;
      return capabilities;
    }

    // 프리뷰를 만들 수 있는지만 본다. 미니맵이 없어도 맵은 정상 동작하므로
    // readable 을 깎지 않는다.
    capabilities.hasMinimap = archive.hasFile(MINIMAP_FILE);

    try {
      const script = archive.readFileAsString("MapScript.galaxy", "utf8");
      capabilities.prepared = script.includes(CUSTOM_BLOCK_MARKER);
      capabilities.preparable =
        !capabilities.prepared &&
        script.includes(NATIVE_LIB_INCLUDE) &&
        STANDARD_MELEE_INIT.test(script);
    } catch (error) {
      capabilities.reason = `MapScript.galaxy 를 읽을 수 없다: ${error.message}`;
      return capabilities;
    }
  } finally {
    archive.close();
  }

  // 슬롯이 실제로 어느 좌표에 앉는지 잇는다. 방위 분할은 슬롯 번호 순서가
  // 아니라 이 좌표에서 유도해야 한다 — 순서 가정은 맵마다 달라 깨진다.
  const startById = new Map(
    capabilities.startLocations.map((point) => [point.id, point])
  );
  capabilities.playerStarts = playerSlots
    .map((player) => {
      const point = startById.get(player.startPoint);
      if (!point) return null;
      return { slot: player.id, startPoint: player.startPoint, x: point.x, y: point.y };
    })
    .filter(Boolean);

  // 실제로 앉힐 수 있는 인원은 MapInfo 슬롯과 시작 지점 중 작은 쪽이다.
  // 시작 지점이 없는 슬롯은 patchPlayers 가 거부한다.
  capabilities.maxPlayers = Math.min(
    capabilities.maxPlayers,
    capabilities.startLocations.length
  );
  if (capabilities.maxPlayers < 2) {
    capabilities.reason = `플레이어를 2명 이상 앉힐 수 없다 (수용 ${capabilities.maxPlayers})`;
    return capabilities;
  }

  capabilities.readable = true;
  return capabilities;
}

module.exports = {
  LAST_PLAYER_SLOT,
  maxTeamsFor,
  readMapCapabilities,
  wildZergAvailability,
};
