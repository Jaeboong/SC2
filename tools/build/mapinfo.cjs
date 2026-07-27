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
// 이 파서는 필드 순서를 고정 가정한다. 선택적 필드(예: 로드스크린 이미지
// 경로)가 있는 맵에서는 정렬이 어긋나 슬롯 수가 터무니없이 나온다 —
// Torches LE 실측: 오프셋 88 에서 u16 길이를 29505 로 읽는다. 그래서 아래
// 개연성 검사가 "지원하지 않는 레이아웃"의 실질적 판별기 역할을 한다.
function readMapInfoPlayers(buffer) {
  let offset = 0;
  const readU8 = () => buffer.readUInt8(offset++);
  const readU16 = () => {
    const value = buffer.readUInt16LE(offset);
    offset += 2;
    return value;
  };
  const readU32 = () => {
    const value = buffer.readUInt32LE(offset);
    offset += 4;
    return value;
  };
  const readCString = () => {
    const end = buffer.indexOf(0, offset);
    if (end < 0) fail(`Unterminated MapInfo string at offset ${offset}`);
    const value = buffer.subarray(offset, end).toString("utf8");
    offset = end + 1;
    return value;
  };
  const skip = (length) => {
    offset += length;
    if (offset > buffer.length) fail("MapInfo is truncated");
  };

  if (buffer.subarray(0, 4).toString("ascii") !== "IpaM") {
    fail("Unsupported MapInfo magic");
  }
  offset = 4;
  const version = readU32();
  if (version !== 0x27) fail(`Unsupported MapInfo version 0x${version.toString(16)}`);

  readU32(); readU32(); readU32(); readU32();
  let previewType = readU32();
  if (previewType === 2) readCString();
  previewType = readU32();
  if (previewType === 2) readCString();
  readCString(); readCString(); readU32(); readU32(); readCString(); readCString();
  for (let index = 0; index < 5; index += 1) readU32();
  const loadScreenType = readU32();
  if (loadScreenType === 2) readCString();
  skip(readU16());
  for (let index = 0; index < 8; index += 1) readU32();
  skip(8); skip(9); skip(4); skip(8);

  const playerCount = readU32();
  if (playerCount > MAX_PLAUSIBLE_MAPINFO_SLOTS) {
    fail(
      `Implausible MapInfo player count: ${playerCount} ` +
        "(지원하지 않는 MapInfo 레이아웃일 가능성이 높다)"
    );
  }
  const players = [];
  for (let index = 0; index < playerCount; index += 1) {
    const id = readU8();
    const controlOffset = offset;
    const control = readU32();
    readU32(); readCString(); readU32();
    const startPointOffset = offset;
    const startPoint = readU32();
    readU32(); readCString();
    players.push({ id, control, controlOffset, startPoint, startPointOffset });
  }
  return players;
}

// 빌드 경로용. 지금 빌더는 논리 P1~P14 + 중립/적대 두 슬롯을 전제하므로
// 슬롯 수가 15~16 이 아닌 맵은 여기서 막는다.
function parseMapInfoPlayers(buffer) {
  const players = readMapInfoPlayers(buffer);
  if (players.length < 15 || players.length > 16) {
    fail(`Unexpected MapInfo player count: ${players.length}`);
  }
  return players;
}

function validateConfig(config) {
  if (config.version !== 1 || !Array.isArray(config.slots) || config.slots.length !== 14) {
    fail("Expected a version 1 configuration with fourteen slots");
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
  for (let index = 0; index < 14; index += 1) {
    const slot = config.slots[index];
    if (slot.slot !== index + 1) fail("Slots must be ordered P1 through P14");
    if (!["empty", "human", "custom_ai"].includes(slot.controller)) {
      fail(`Unknown controller for P${slot.slot}: ${slot.controller}`);
    }
  }
  const configuredTeams = config.slots.map((slot) => slot.team);
  const teamMode = [...TEAM_LAYOUTS].find(([, layout]) =>
    layout.every((team, index) => configuredTeams[index] === team)
  )?.[0];
  if (teamMode === undefined) {
    fail("Team layout must match the fixed 2-team, 3-team, or 4-team preset");
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
  readMapInfoPlayers,
  parseMapInfoPlayers,
  validateConfig,
  patchPlayers,
};
