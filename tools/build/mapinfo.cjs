// MapInfo 바이너리 파싱과 플레이어 슬롯 패치, 그리고 런처 설정 검증.
//
// 논리 슬롯 P1-P14는 연속된 런타임 ID로 압축되고, 유일한 Participant는
// 엔진이 항상 런타임 P1로 승격한다(HANDOFF 불변식). 시작 지점은 원본 맵의
// 고정 배치를 그대로 재사용한다.

const { fail } = require("./util.cjs");
const {
  PROTOSS_FACTIONS,
} = require("./tables.cjs");

// Python launcher contract mirrored at the direct builder boundary. These
// layouts only change alliances; P1-P14 keep their existing fixed StartLocs.
const TEAM_LAYOUTS = new Map([
  [2, [1, 1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 2, 2, 2]],
  [3, [3, 3, 3, 1, 1, 1, 1, 3, 3, 3, 2, 2, 2, 3]],
  [4, [3, 3, 3, 1, 1, 1, 1, 4, 4, 4, 2, 2, 2, 4]],
]);

// SC2 의 플레이어 슬롯 상한(16)보다 넉넉히 잡은 개연성 한계. 이보다 크면
// 그런 맵이 있는 게 아니라 파싱이 어긋난 것이다.
const MAX_PLAUSIBLE_MAPINFO_SLOTS = 64;

// 원시 순차 파싱. 슬롯 수를 검증하지 않는다 — 임의 맵의 수용 인원을 재는
// map_capabilities.cjs 가 15~16 이 아닌 맵도 읽어야 하기 때문이다. 빌드
// 경로가 쓰는 15~16 검사는 parseMapInfoPlayers 가 계속 들고 있다.
//
// 이 파서는 필드 순서를 고정 가정한다. 로드스크린 경로는 loadScreenType 과
// 무관하게 항상 cstring으로 뒤따른다. 이를 타입 2일 때만 읽으면, 비어 있지
// 않은 경로를 가진 맵에서 이후 blob 길이와 플레이어 표의 정렬이 어긋난다.
function parseMapInfo(buffer) {
  let offset = 0;
  let readingPlayerTable = false;
  const truncated = () => {
    if (readingPlayerTable) {
      fail(
        "MapInfo 플레이어 표가 버퍼 끝에서 잘렸습니다 " +
          "(지원하지 않는 MapInfo 레이아웃일 가능성이 높다)"
      );
    }
    fail("MapInfo is truncated");
  };
  const ensureAvailable = (length) => {
    if (offset + length > buffer.length) truncated();
  };
  const readU8 = () => {
    ensureAvailable(1);
    return buffer.readUInt8(offset++);
  };
  const readU16 = () => {
    ensureAvailable(2);
    const value = buffer.readUInt16LE(offset);
    offset += 2;
    return value;
  };
  const readU32 = () => {
    ensureAvailable(4);
    const value = buffer.readUInt32LE(offset);
    offset += 4;
    return value;
  };
  const readCString = () => {
    ensureAvailable(1);
    const end = buffer.indexOf(0, offset);
    if (end < 0) {
      if (readingPlayerTable) truncated();
      fail(`Unterminated MapInfo string at offset ${offset}`);
    }
    const value = buffer.subarray(offset, end).toString("utf8");
    offset = end + 1;
    return value;
  };
  const skip = (length) => {
    offset += length;
    if (offset > buffer.length) truncated();
  };

  if (buffer.subarray(0, 4).toString("ascii") !== "IpaM") {
    fail("Unsupported MapInfo magic");
  }
  offset = 4;
  const version = readU32();
  if (version !== 0x27) fail(`Unsupported MapInfo version 0x${version.toString(16)}`);

  readU32(); readU32();
  const width = readU32();
  const height = readU32();
  let previewType = readU32();
  previewType = readU32();
  // previewType 값과 무관하게 뒤에는 문자열 두 개가 온다. 타입 2 조건은
  // 근거 없이 정렬을 깨므로 읽지 않는다.
  readCString(); readCString(); readU32(); readU32(); readCString(); readCString();
  // 플레이 영역(카메라 경계). 미니맵 이미지가 덮는 범위가 바로 이 사각형이다.
  const left = readU32();
  const bottom = readU32();
  const right = readU32();
  const top = readU32();
  readU32();
  const loadScreenType = readU32();
  readCString();
  skip(readU16());
  skip(60);

  const playerCount = readU32();
  if (playerCount > MAX_PLAUSIBLE_MAPINFO_SLOTS) {
    fail(
      `Implausible MapInfo player count: ${playerCount} ` +
        "(지원하지 않는 MapInfo 레이아웃일 가능성이 높다)"
    );
  }
  const players = [];
  readingPlayerTable = true;
  for (let index = 0; index < playerCount; index += 1) {
    const id = readU8();
    if (id > 15) {
      fail(
        `MapInfo 플레이어 id ${id} (표 ${index}번째)가 0..15 범위를 벗어났습니다 ` +
          "(지원하지 않는 MapInfo 레이아웃일 가능성이 높다)"
      );
    }
    if (index === 0 && id !== 0) {
      fail(
        `MapInfo 플레이어 표의 첫 id가 ${id}입니다 (0이어야 함; ` +
          "지원하지 않는 MapInfo 레이아웃일 가능성이 높다)"
      );
    }
    if (index > 0 && id <= players[index - 1].id) {
      fail(
        `MapInfo 플레이어 id가 엄격히 증가하지 않습니다: ${players[index - 1].id} 뒤에 ${id} ` +
          "(지원하지 않는 MapInfo 레이아웃일 가능성이 높다)"
      );
    }
    const controlOffset = offset;
    const control = readU32();
    readU32(); readCString(); readU32();
    const startPointOffset = offset;
    const startPoint = readU32();
    readU32(); readCString();
    players.push({ id, control, controlOffset, startPoint, startPointOffset });
  }
  if (players.length === 0) {
    fail(
      "MapInfo 플레이어 표가 비어 있습니다 (0으로 시작해 15로 끝나야 함; " +
        "지원하지 않는 MapInfo 레이아웃일 가능성이 높다)"
    );
  }
  if (players[players.length - 1].id !== 15) {
    fail(
      `MapInfo 플레이어 표의 마지막 id가 ${players[players.length - 1].id}입니다 ` +
        "(15여야 함; 지원하지 않는 MapInfo 레이아웃일 가능성이 높다)"
    );
  }
  return {
    geometry: { width, height, bounds: { left, bottom, right, top } },
    players,
  };
}

function readMapInfoPlayers(buffer) {
  return parseMapInfo(buffer).players;
}

// 맵 전체 크기와 플레이 영역. 미니맵 프리뷰의 좌표 변환에 쓴다.
function readMapInfoGeometry(buffer) {
  return parseMapInfo(buffer).geometry;
}

// 빌드 경로용. id 0 및 15와 실제 플레이어가 최소 하나는 있어야 한다.
// 상한은 parseMapInfo()의 개연성 검사에서 이미 막는다.
function parseMapInfoPlayers(buffer) {
  const players = readMapInfoPlayers(buffer);
  if (players.length < 3) {
    fail(`Unexpected MapInfo player count: ${players.length}`);
  }
  return players;
}

function validateConfig(config) {
  if (config.version !== 1) fail("Expected a version 1 configuration");
  if (!Array.isArray(config.slots)) fail("Expected a slots array");
  if (config.slots.length < 2 || config.slots.length > 14) {
    fail("Expected between 2 and 14 slots");
  }
  const humans = config.slots.filter((slot) => slot.controller === "human");
  if (humans.length !== 1) fail("Exactly one human slot is required");
  if (config.campaign_units_probe_damage && !config.campaign_units_pilot) {
    fail("Torrasque damage probe requires the campaign-units pilot");
  }
  const protossFaction = config.protoss_faction ?? "Standard";
  if (!PROTOSS_FACTIONS.has(protossFaction)) {
    fail(`Unknown Protoss faction: ${protossFaction}`);
  }
  for (let index = 0; index < config.slots.length; index += 1) {
    const slot = config.slots[index];
    if (slot.slot !== index + 1) {
      fail("Slots must be ordered consecutively from P1");
    }
    if (!["empty", "human", "custom_ai"].includes(slot.controller)) {
      fail(`Unknown controller for P${slot.slot}: ${slot.controller}`);
    }
  }
  const configuredTeams = config.slots.map((slot) => slot.team);
  const teamNumbers = [...new Set(configuredTeams)].sort((left, right) => left - right);
  if (!teamNumbers.every((team, index) => Number.isInteger(team) && team === index + 1)) {
    fail("Team numbers must be consecutive from 1 without gaps");
  }
  const teamMode = teamNumbers.length;
  if (teamMode < 2 || teamMode > 4) {
    fail("Expected between 2 and 4 teams");
  }
  const activeTeams = new Set(
    config.slots.filter((slot) => slot.controller !== "empty").map((slot) => slot.team)
  );
  if (activeTeams.size === 0) {
    fail("At least one active player is required");
  }
  if (config.wild_zerg !== true && activeTeams.size < 2) {
    fail("At least two active teams are required when Wild Zerg is disabled");
  }
  return humans[0];
}

// §90: 야생 저그(맵 플레이어 15)를 실제 로비 컴퓨터 슬롯으로 승격시킨다.
//
// 중립 적대(control 4)로는 전투 유닛을 **어떤 경로로도** 생산할 수 없다 —
// 프로브 12판으로 확정했다(§90 기록). 같은 라바에서 드론·대군주는 유효 59,
// 저글링·바퀴·히드라·베인링·뮤탈은 물론 마린(테란)·질럿(프로토스)·캠페인
// 유닛까지 전부 유효 0이었고, 요구조건 속성을 지운 항목도, 해처리 직접 훈련
// 능력도 똑같이 0이었다. 드론과 대군주는 저그가 건물 없이 시작할 때 만들 수
// 있는 정확히 그 두 유닛이다 — 엔진이 P15 를 영구히 "무건물"로 취급한다.
//
// control 을 1로 올리고 시작 지점을 주면 풀린다(실측: 6게임분에 바퀴 +28,
// 히드라 +11, 저글링 +7, 산란못 2 -> 11, 알이 내내 5~11개). 승격 전 같은
// 구성에서는 6분 내내 병력이 1기도 늘지 않았다.
const WILD_ZERG_PLAYER = 15;

function patchPlayers(mapInfo, activeSlots, wildStartPoint = null) {
  const players = parseMapInfoPlayers(mapInfo);
  const fixedStarts = new Map(
    players
      .filter((player) => player.id >= 1 && player.id <= 14)
      .map((player) => [player.id, player.startPoint])
  );
  const assignments = [];
  for (const player of players) {
    if (player.id >= 1 && player.id <= 14) {
      const logicalSlot = activeSlots[player.id - 1];
      mapInfo.writeUInt32LE(logicalSlot ? 1 : 0, player.controlOffset);
      if (logicalSlot) {
        const startPoint = fixedStarts.get(logicalSlot.slot);
        if (!startPoint) fail(`P${logicalSlot.slot} has no fixed start point`);
        mapInfo.writeUInt32LE(startPoint, player.startPointOffset);
        assignments.push({
          runtimeId: player.id,
          logicalSlot: logicalSlot.slot,
          team: logicalSlot.team,
          startPoint,
        });
      }
    }
    else if (player.id === WILD_ZERG_PLAYER && wildStartPoint !== null) {
      mapInfo.writeUInt32LE(1, player.controlOffset);
      mapInfo.writeUInt32LE(wildStartPoint, player.startPointOffset);
    }
  }
  return { mapInfo, assignments };
}

// §63: 한 플레이어의 연구 사다리를 "틱당 최대 1건" try 체인으로 펼친다.
// §69: prereqStructure(요구 구조물 게이트)를 함수에 넘긴다. 없으면 빈 문자열.

module.exports = {
  readMapInfoGeometry,
  readMapInfoPlayers,
  parseMapInfoPlayers,
  validateConfig,
  patchPlayers,
};
