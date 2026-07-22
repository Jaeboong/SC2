// 빌드 산출물 자가 검증. 여기서 실패하면 맵 파일이 생성되지 않는다.
//
// 이 파일의 단언들은 대부분 실제로 게임에서 깨진 것을 다시 못 깨지게
// 막는 것이다(HANDOFF의 불변식과 1:1로 대응). 단언을 완화하기 전에
// 반드시 해당 §절의 실측 기록을 확인할 것.

const fs = require("node:fs");
const path = require("node:path");

const { fail, PROJECT_ROOT } = require("./util.cjs");
const { parseMapInfoPlayers } = require("./mapinfo.cjs");
const {
  ROSTER_HOTKEYS,
  researchLadderForSlot,
  CAMPAIGN_ASSET_DEPENDENCIES,
  PROTOSS_FACTION_SENTINEL_MODEL,
  COMBAT_AIR_BY_RACE,
  SUPPORT_AIR_BY_RACE,
  supportAirCap,
  PREFERRED_STOCK_BY_BUILD,
  STOCK_SQUEEZE_MULTIPLIER,
  PREFERRED_UPGRADES_BY_BUILD,
  RESEARCH_INFRA_BY_RACE,
  CAMPAIGN_PURCHASE_BY_UNIT,
  PREFERRED_INFRA_BY_BUILD,
  RANDOM_INFRA_BY_RACE,
  RANDOM_TRAIN_BY_RACE,
  FORCED_INFRASTRUCTURE_BY_BUILD,
  SCALING_PRODUCTION_BY_BUILD,
  RANDOM_SCALING_PRODUCTION_BY_RACE,
  FIXED_STRUCTURE_CAPS_BY_BUILD,
  EXPANSION_TOWN_HALL_BY_RACE,
  DIRECT_TRAIN_BY_UNIT,
} = require("./tables.cjs");
const {
  WILD_ZERG_FOREIGN_UNITS,
  WILD_START_ON_HALL_RADIUS,
} = require("./archive.cjs");

// §93: 야생 저그 비활성 모드가 실제로 "채취만" 하는지 확인하는 마커.
// 있어야 하는 것은 10초 틱과 DroneHarvest 뿐이다.
const HOSTILE_WILD_IDLE_MARKERS = [
  "sc2team_HostileWildIdle_Func",
  "sc2team_HostileWildIdleHarvest",
  "sc2team_HostileWildIdleMineralByIndex",
  "AbilityCommand(\"DroneHarvest\", 0)",
  "sc2team_InitializeHostileWildIdle();",
  "TriggerAddEventTimePeriodic(gt_sc2team_HostileWildIdle, 10.0, c_timeGame)",
];

// 반대로 비활성 모드에 **남아 있으면 안 되는** 것들. 채취 컨트롤러가 활성
// 컨트롤러의 일부만 잘라낸 형태가 되면 "생산도 안하게" 라는 요구가 조용히
// 깨지므로, 생산·건설·확장·습격·은행 보충의 대표 심볼을 전부 금지한다.
const HOSTILE_WILD_IDLE_BANNED = [
  "sc2team_HostileWildTrainLarva",
  "sc2team_HostileWildBuildEconomy",
  "sc2team_HostileWildBuildSpineCrawler",
  "sc2team_HostileWildBuildAlphaTech",
  "sc2team_HostileWildTryExpand",
  "sc2team_HostileWildTryMacroHatchery",
  "sc2team_HostileWildTryRaid",
  "sc2team_HostileWildTryRebuildNest",
  "TechTreeUnitAllow(15,",
  "TechTreeAbilityAllow(15,",
  "PlayerModifyPropertyInt(15,",
];

// SC2 resolves a unit actor's voice by actor id: actor "Predator" finds CSound
// "Predator_What" with no XML. Our actors are named SC2TeamPredator, so that
// auto-link finds nothing and every roster unit is mute until its SoundArray
// names Blizzard's CSound explicitly. A wrong id is silent rather than fatal --
// the roster shipped "UltraliskReady" for a sound really called
// "Ultralisk_Ready" and nothing complained -- so every id is checked against the
// catalogs actually extracted under vendor/.
//
// Only sounds from the base game and the Liberty campaign may be named. The
// matching Aberration_* voice set exists solely in Swarm Story, and that
// dependency redefines FactoryTrain Train20 and breaks Goliath production.
const SOUND_SOURCE_GLOBS = [
  "vendor/sc2gamedata-source/mods/liberty.sc2mod/base.sc2data/GameData/SoundData.xml",
  "vendor/sc2gamedata-source/campaigns/liberty.sc2campaign/base.sc2data/GameData/SoundData.xml",
];

function knownSoundIds() {
  const ids = new Set();
  for (const relative of SOUND_SOURCE_GLOBS) {
    // This builder lives in tools/, so the project root is its parent.
    const file = path.join(PROJECT_ROOT, relative);
    if (!fs.existsSync(file)) return null;
    const content = fs.readFileSync(file, "utf8");
    for (const match of content.matchAll(/<CSound\s+id="([^"]+)"/g)) ids.add(match[1]);
  }
  return ids;
}

// Two purchases sharing a cooldown slot still build, still pass every catalog
// and production probe, and simply throttle each other on the structures they
// share. Nothing at runtime reports it, so assert it here.
function verifyPurchaseCooldownSlots() {
  const owner = new Map();
  for (const [unitType, purchase] of Object.entries(CAMPAIGN_PURCHASE_BY_UNIT)) {
    const previous = owner.get(purchase.customValue);
    if (previous !== undefined) {
      fail(
        `Campaign purchases ${previous} and ${unitType} share customValue ` +
        `${purchase.customValue}; they would contend for one cooldown slot on ` +
        "every producer they have in common",
      );
    }
    if (purchase.customValue >= 26) {
      fail(
        `Campaign purchase ${unitType} uses customValue ${purchase.customValue}; ` +
        "slot 26 is the Torrasque probe marker and 31 is the script-control timer",
      );
    }
    owner.set(purchase.customValue, unitType);
  }
}

function verifyRosterSounds(actorBlock) {
  const ids = knownSoundIds();
  if (ids === null) {
    // The extracted Blizzard catalogs are a developer convenience, not a build
    // input. Skip loudly rather than pretend the sounds were checked.
    console.warn("WARN: vendor sound catalogs are absent; roster sound ids unchecked");
    return;
  }
  let checked = 0;
  for (const match of actorBlock.matchAll(
    /<(?:Group)?SoundArray\s+index="([^"]+)"\s+value="([^"]*)"\s*\/>/g,
  )) {
    const [, index, value] = match;
    if (value === "") continue;
    checked += 1;
    if (!ids.has(value)) {
      fail(
        `Roster sound "${value}" (index ${index}) is not a CSound in the base game ` +
        "or the Liberty campaign; the unit would be silent",
      );
    }
  }
  if (checked === 0) fail("Roster actors declare no sounds; every roster unit would be mute");
}

// A CButton is an icon and nothing else: Blizzard's Marine button carries no
// hotkey and no tooltip either. Both come from string keys, so a roster button
// with no string renders as an icon with no letter and no description.
function verifyRosterHotkeysAndTooltips(archive) {
  for (const locale of ["koKR", "enUS"]) {
    const hotkeyFile = `${locale}.SC2Data\\LocalizedData\\GameHotkeys.txt`;
    if (!archive.hasFile(hotkeyFile)) fail(`Map has no ${hotkeyFile}`);
    const hotkeys = archive.readFileAsString(hotkeyFile, "utf8");
    const strings = archive.readFileAsString(
      `${locale}.SC2Data\\LocalizedData\\GameStrings.txt`,
      "utf8",
    );
    for (const [button, key] of Object.entries(ROSTER_HOTKEYS)) {
      if (!hotkeys.includes(`Button/Hotkey/${button}=${key}`)) {
        fail(`${locale}: roster button ${button} has no hotkey`);
      }
      if (!strings.includes(`Button/Tooltip/${button}=`)) {
        fail(`${locale}: roster button ${button} has no tooltip`);
      }
    }
  }
}

// §95: 생산 스케줄러와 집계 캐시 검증.
//
// 종전에는 sc2team_ProductionSteering_Func 하나가 커스텀 AI 전원의 경제·생산
// 로직을 15초마다 한꺼번에 돌렸다. 릴리스 설정(12명) 기준 한 발화에 무조건
// 전체 맵 스캔 365회(조건부까지 상한 1,121회)라, SC2 시뮬레이션 스레드가 그
// 시간 동안 통째로 멈춘다 — 사용자가 관측한 주기적 화면 정지다. 이제 발화당
// 플레이어 하나만 처리하고, 그 플레이어의 유닛은 한 번만 훑는다.
//
// 여기서 막아야 하는 퇴행은 두 가지다.
// (1) 스케줄러가 사라지고 다시 전원 일괄 처리로 돌아가는 것.
// (2) 집계 표에 없는 타입을 질의해 **조용히 0**을 받는 것. 그건 §83(빌드
//     관리자 영구 정지)·§91.10(보급 게이트 영구 폐쇄)과 같은 무증상 전면
//     고장이며, 이 프로젝트에서 가장 비싼 실패 유형이다.
function verifyProductionScheduler(script, activeSlots) {
  const steerPlayers = [];
  for (let index = 0; index < activeSlots.length; index += 1) {
    if (activeSlots[index].controller !== "custom_ai") continue;
    steerPlayers.push(index + 1);
  }
  if (steerPlayers.length === 0) return;

  // (1) 전원 일괄 처리로의 퇴행 금지.
  if (script.includes("TriggerAddEventTimePeriodic(gt_sc2team_ProductionSteering, 15.0, c_timeGame)")) {
    fail("Production steering must not return to a single 15s all-players tick");
  }
  for (const marker of [
    "int gv_sc2team_SteerCursor;",
    "gv_sc2team_SteerCursor += 1;",
    "void sc2team_RefreshCounts (int player) {",
    "int sc2team_CountIndex (string unitType) {",
    "gv_sc2team_CountReady[player] = true;",
  ]) {
    if (!script.includes(marker)) fail(`Missing production scheduler marker: ${marker}`);
  }
  const cursorReset = new RegExp(
    `if \\(gv_sc2team_SteerCursor > ${steerPlayers.length}\\) \\{`
  );
  if (!cursorReset.test(script)) {
    fail(`Round-robin cursor must wrap at ${steerPlayers.length} (one entry per active custom AI)`);
  }
  // 한 바퀴가 12게임초여야 한다. 주기 × 인원 = 12.
  const periodMatch = /TriggerAddEventTimePeriodic\(gt_sc2team_ProductionSteering, ([\d.]+), c_timeGame\)/
    .exec(script);
  if (!periodMatch) fail("Missing production steering periodic event");
  const cycle = parseFloat(periodMatch[1]) * steerPlayers.length;
  if (Math.abs(cycle - 12.0) > 0.05) {
    fail(
      `Production steering cycle must stay 12 game seconds per player ` +
      `(period ${periodMatch[1]} x ${steerPlayers.length} = ${cycle.toFixed(2)})`
    );
  }
  // (2) 플레이어별 함수·디스패치·초기 1회·집계 갱신이 전부 있어야 한다.
  for (let i = 0; i < steerPlayers.length; i += 1) {
    const player = steerPlayers[i];
    const fn = `sc2team_SteerP${player}`;
    if (!script.includes(`void ${fn} () {`)) {
      fail(`Missing per-player production function for runtime P${player}`);
    }
    if (!script.includes(`gv_sc2team_SteerCursor == ${i + 1}) { ${fn}(); }`)) {
      fail(`Runtime P${player} is never reached by the round-robin dispatcher`);
    }
    const bodyStart = script.indexOf(`void ${fn} () {`);
    const bodyEnd = script.indexOf("\n}", bodyStart);
    const body = script.slice(bodyStart, bodyEnd);
    // 집계 갱신이 그 플레이어의 첫 동작이어야 한다. 빠지면 직전 플레이어의
    // 수치를 읽는다(캐시는 플레이어별이지만 준비 플래그가 계속 참이므로
    // 조용히 낡은 값을 반환한다).
    if (!body.includes(`sc2team_RefreshCounts(${player});`)) {
      fail(`Runtime P${player} production turn does not refresh its unit tally`);
    }
    for (const other of steerPlayers) {
      if (other === player) continue;
      if (body.includes(`sc2team_RefreshCounts(${other});`)) {
        fail(`Runtime P${player} production turn refreshes the tally of P${other}`);
      }
    }
  }

  // (3) 집계 표 커버리지. 질의되는 타입이 표에 없으면 accessor가 *Live 전체
  // 스캔으로 떨어지므로 결과는 정확하다 — 그래서 이건 성능 회귀 경보다.
  // 반대로 폴백 자체가 사라지면 조용한 0이 되므로 폴백 존재는 필수 검사다.
  // 인덱스가 있는 accessor는 폴백이 **두 곳**이다: 캐시 미준비와 표에 없는
  // 타입. 한쪽만 남기면 나머지 경우가 조용히 0이 되므로 개수까지 센다.
  for (const accessor of [
    { fn: "sc2team_CountAllProduction", live: "sc2team_CountAllProductionLive", paths: 2 },
    { fn: "sc2team_CountCompletedProduction", live: "sc2team_CountCompletedProductionLive", paths: 2 },
    { fn: "sc2team_CountUnits", live: "sc2team_CountUnitsLive", paths: 2 },
    { fn: "sc2team_CountCompletedTownHalls", live: "sc2team_CountCompletedTownHallsLive", paths: 1 },
    { fn: "sc2team_CountAllTownHalls", live: "sc2team_CountAllTownHallsLive", paths: 1 },
    { fn: "sc2team_EconomyWorkerTarget", live: "sc2team_EconomyWorkerTargetLive", paths: 1 },
  ]) {
    const start = script.indexOf(`int ${accessor.fn} (int player`);
    if (start < 0) fail(`Missing count cache accessor: ${accessor.fn}`);
    const body = script.slice(start, script.indexOf("\n}", start));
    const found = body.split(`${accessor.live}(player`).length - 1;
    if (found < accessor.paths) {
      fail(
        `${accessor.fn} must keep ${accessor.paths} exact-count fallback path(s) ` +
        `to ${accessor.live}, found ${found} — a missing fallback returns a silent 0`
      );
    }
  }
  const indexStart = script.indexOf("int sc2team_CountIndex (string unitType) {");
  const indexBody = script.slice(indexStart, script.indexOf("\n}", indexStart));
  const tableTypes = new Set(
    [...indexBody.matchAll(/unitType == "([^"]+)"/g)].map((match) => match[1])
  );
  // 타운홀 합산은 표를 직접 인덱싱하므로 하나라도 빠지면 조용히 과소 집계된다.
  for (const townHall of [
    "CommandCenter", "OrbitalCommand", "PlanetaryFortress",
    "Nexus", "Hatchery", "Lair", "Hive",
  ]) {
    if (!tableTypes.has(townHall)) {
      fail(`Count table must contain every town hall type; missing ${townHall}`);
    }
  }
  // 별칭은 반드시 짝으로 있어야 합산이 맞는다.
  if (tableTypes.has("Gateway") !== tableTypes.has("WarpGate")) {
    fail("Count table must hold Gateway and WarpGate together");
  }
  if (tableTypes.has("SupplyDepot") !== tableTypes.has("SupplyDepotLowered")) {
    fail("Count table must hold SupplyDepot and SupplyDepotLowered together");
  }
  const queried = new Set();
  for (const pattern of [
    /sc2team_CountCompletedProduction\(\d+, "([^"]+)"\)/g,
    /sc2team_CountAllProduction\(\d+, "([^"]+)"\)/g,
    /sc2team_CountUnits\(\d+, "([^"]+)"\)/g,
    /sc2team_TrySupplyStructure\(\d+, "([^"]+)"\)/g,
  ]) {
    for (const match of script.matchAll(pattern)) queried.add(match[1]);
  }
  for (const match of script.matchAll(/sc2team_TryBuildTerranAddon\(\d+, "([^"]+)", "([^"]+)"/g)) {
    queried.add(match[2]);
  }
  for (const match of script.matchAll(
    /sc2team_TryPurchaseCampaignUnit\(\d+, "[^"]*", "([^"]+)", "([^"]+)"/g
  )) {
    queried.add(match[1]);
    queried.add(match[2]);
  }
  const uncovered = [...queried].filter((unitType) => !tableTypes.has(unitType));
  if (uncovered.length > 0) {
    fail(
      `Count table misses queried types (they would fall back to a full scan every turn): ` +
      uncovered.join(", ")
    );
  }
}

function verify(archive, config, humanRuntimeId, assignments, activeSlots) {
  // 슬롯 14 유령 유닛 방지: 선배치 유닛이 플레이어 14 소유로 남아 있으면 실패.
  const objects = archive.readFileAsString("Objects", "utf8");
  if (/<ObjectUnit\b[^>]*\bPlayer="14"/.test(objects)) {
    fail("Objects still contains player-14 preplaced units");
  }
  if (/<ObjectUnit\b(?=[^>]*\bUnitType="Overlord")[^>]*\bPlayer="7"/.test(objects)) {
    fail("Objects still contains player-7 Overlord decoration");
  }
  const players = parseMapInfoPlayers(archive.readFile("MapInfo"));
  const expected = Array.from({ length: assignments.length }, (_, index) => index + 1);
  const actual = players
    .filter((player) => player.id >= 1 && player.id <= 14 && player.control === 1)
    .map((player) => player.id);
  if (JSON.stringify(actual) !== JSON.stringify(expected)) {
    fail(`Active slot verification failed: expected ${expected}, got ${actual}`);
  }
  // §90.9: 야생 저그는 저그다. 프로토스 선배치 유닛이 남아 있으면 빌드 실패
  // (사용자 지시로 제거했다 — 원본 맵 장식에 질럿·추적자·불멸자·파수기·
  // 사도 잔상이 섞여 있었다).
  for (const unitType of WILD_ZERG_FOREIGN_UNITS) {
    const stray = new RegExp(
      `<ObjectUnit\\b[^>]*\\bUnitType="${unitType}"[^>]*\\bPlayer="15"|` +
      `<ObjectUnit\\b[^>]*\\bPlayer="15"[^>]*\\bUnitType="${unitType}"`
    );
    if (stray.test(objects)) {
      fail(`Wild Zerg still owns a Protoss unit: ${unitType}`);
    }
  }
  // §90: 야생 저그는 중립 적대가 아니라 실제 로비 컴퓨터 슬롯이어야 한다.
  // 중립 적대(control 4)로는 전투 유닛을 어떤 경로로도 훈련할 수 없다 —
  // 프로브 12판으로 확정했다(드론·대군주만 유효, 요구조건을 지운 항목도,
  // 해처리 직접 훈련도 전부 거부). 승격과 시작 지점 둘 다 있어야 병력이
  // 나온다: 시작 지점이 없으면 밀레 AI가 산란못을 끝내 짓지 않는다.
  //
  // §93: 런처에서 야생 저그를 끄면 그 승격을 하지 "않는" 것이 곧 생산 금지의
  // 구현이므로, 같은 검사를 반대 방향으로 건다.
  const wildZergActive = config.wild_zerg !== false;
  const wildZerg = players.find((player) => player.id === 15);
  if (!wildZerg) fail("Wild Zerg map player 15 is missing from MapInfo");
  if (wildZergActive) {
    if (wildZerg.control !== 1) {
      fail(
        "Wild Zerg must be a real lobby computer slot " +
        `(MapInfo control ${wildZerg.control}, expected 1)`
      );
    }
    if (!wildZerg.startPoint) {
      fail("Wild Zerg has no start point; the melee AI never builds tech without one");
    }
    // §90.12: 시작 지점은 P15 타운홀 "위"에 있어야 한다. 밀레 AI 는 시작 위치에서
    // 가장 가까운 타운홀을 본진으로 삼으므로, 빈 땅에 있으면 엉뚱한 기지를 본진으로
    // 잡고 그쪽으로만 오버로드와 드론을 보낸다(사용자 실관측). 어느 타운홀인지는
    // 사용자가 에디터에서 정하므로 좌표를 고정하지 않고 "타운홀 위"만 강제한다.
    const wildStartTag = new RegExp(
      `<ObjectPoint\\b[^>]*\\bId="${wildZerg.startPoint}"[^>]*\\/>`
    ).exec(objects);
    if (!wildStartTag) {
      fail(`Wild Zerg start point ${wildZerg.startPoint} is not an Objects point`);
    }
    const [startX, startY] = /\bPosition="([^"]+)"/
      .exec(wildStartTag[0])[1].split(",").map(Number);
    let nearestHall = Infinity;
    for (const match of objects.matchAll(/<ObjectUnit\b[^>]*\/>/g)) {
      const tag = match[0];
      if (!/\bPlayer="15"/.test(tag)) continue;
      if (!/\bUnitType="(?:Hatchery|Lair|Hive)"/.test(tag)) continue;
      const [x, y] = /\bPosition="([^"]+)"/.exec(tag)[1].split(",").map(Number);
      nearestHall = Math.min(nearestHall, Math.hypot(startX - x, startY - y));
    }
    // 임계값은 archive.cjs 와 같은 상수를 쓴다. 숫자를 양쪽에 따로 두면
    // 조용히 어긋나고, 어긋나면 빌더가 사용자 배치를 버리는데도 검사는 통과한다
    // (2026-07-22 에 실제로 그렇게 3시 Lair 로 끌려갔다).
    if (!(nearestHall <= WILD_START_ON_HALL_RADIUS)) {
      fail(
        `Wild Zerg start point is ${nearestHall.toFixed(1)} from the nearest P15 ` +
        "town hall; it must sit on one or the melee AI adopts the wrong main base"
      );
    }
  }
  else if (wildZerg.control === 1) {
    // 승격이 남아 있으면 맵 트리거를 아무리 비워도 블리자드 멜레 AI 가 P15 를
    // 대신 굴려 계속 생산한다 — 비활성 모드의 유일한 실패 양상이 이것이다.
    fail(
      "Wild Zerg is disabled but map player 15 is still a lobby computer; " +
      "the melee AI would keep producing for it"
    );
  }
  if (config.campaign_units_pilot) {
    const documentInfo = archive.readFileAsString("DocumentInfo", "utf8");
    const voidIndex = documentInfo.indexOf("file:Mods/Void.SC2Mod");
    for (const dependency of CAMPAIGN_ASSET_DEPENDENCIES) {
      const filePart = dependency.slice(dependency.indexOf("file:"));
      const dependencyIndex = documentInfo.indexOf(filePart);
      if (dependencyIndex < 0 || (voidIndex >= 0 && dependencyIndex > voidIndex)) {
        fail(`Campaign asset dependency is missing or ordered after Void: ${filePart}`);
      }
    }
  }
  const script = archive.readFileAsString("MapScript.galaxy", "utf8");
  // P15 is a neutral-hostile map owner rather than a lobby slot.  The wildlife
  // controller must therefore stay map-side and keep its own anchors, slow
  // reinforcement, local defense, patrol, and limited raid behavior.
  // §93: 비활성 모드에서는 이 목록 전체가 채취 전용 마커로 교체된다.
  const hostileWildActiveMarkers = [
    "sc2team_HostileWildAI_Func",
    "sc2team_HostileWildManageNest",
    "sc2team_HostileWildHarvest",
    "sc2team_HostileWildTrainLarva",
    "sc2team_HostileWildBuildEconomy",
    "sc2team_HostileWildIsEconomyNest",
    "sc2team_HostileWildTryRaid",
    "sc2team_HostileWildRecallRaiders",
    "sc2team_HostileWildBuildSpineCrawler",
    "sc2team_HostileWildTryExpand",
    // §89: 로컬 매크로 해처리가 전 경제 둥지로 확대(알파 5개).
    "sc2team_HostileWildTryMacroHatchery",
    // §89.4: 매크로 해처리는 밀착 반경(14) 카운트를 쓴다 — 반경 30 카운트는
    // 이웃 선배치 둥지까지 세어 전 둥지에서 발동 불가였다(실측 신규 1개).
    "sc2team_HostileWildTightNestCount",
    // §89: 병종 순환 선택(구성비 상한 없는 혼합).
    "gv_sc2team_HostileWildTickCounter",
    // §89.4: 일꾼 보충 틱당 2기 제한 — cv28 위에서 무제한 보충은 라바 전체를
    // 드론으로 소진해 병력이 굶는다(실측: 드론 162 vs 병력 23).
    "workerWant",
    // §89.4: 복구 동시 2건 + 후보 중복 제외.
    "sc2team_HostileWildRebuildPending",
    // §89.6: 채굴 재발주 금지(명령 있는 드론은 건드리지 않음) + 광물 덩어리
    // 분산 배정. 종전에는 "가장 가까운 덩어리 1개"에 근처 드론 전원을 매 틱
    // c_orderQueueReplace로 몰아넣어, 사용자 실관측대로 채굴하던 드론이 한
    // 곳에 뭉치고 건설하러 가던 드론은 도중에 취소됐다.
    "sc2team_HostileWildMineralByIndex",
    // §89.6: 건설 임무 도장(cv29) — 걸어가는 동안 구조물이 아직 없으므로
    // 다음 틱에 새 지점으로 재발주돼 드론이 영원히 방황하던 문제.
    "sc2team_HostileWildBuilderBusy",
    "sc2team_HostileWildTakeBuilder",
    "sc2team_HostileWildMarkBuilder",
    // §89.8: 은행 자동 보충. P15는 수입이 사실상 없어(추출장 0) 초기 일괄
    // 지급이 마르면 드론(50)만 통과하고 병력·건물 하한은 전부 막힌다 —
    // "드론은 늘고 병력은 일절 안 나온다"의 실측된 원인.
    "PlayerGetPropertyInt(15, c_playerPropVespene) < 20000",
    // §89.9: 7분 휴전 중 이탈 유닛 회수 — 방어 응전이 정찰 일꾼을 쫓아
    // 상대 본진까지 원정 가던 문제(귀환 도장 + 미귀가 유닛 강제 소환).
    "sc2team_HostileWildLeashStrays",
    "UnitSetCustomValue(currentUnit, 27, now + returnAfter)",
    "sc2team_HostileWildFindInitialLair",
    "sc2team_HostileWildAlphaNextRaid = 420.0",
    "sc2team_HostileWildUpdateExpansionState",
    "sc2team_HostileWildThreatPoint",
    "sc2team_InitializeHostileWildAI();",
    "TriggerAddEventTimePeriodic(gt_sc2team_HostileWildAI, 10.0, c_timeGame)",
    // §103: 원거리 이동이 필요한 두 건설 경로(확장·둥지 재건)는 발주 전에
    // 드론이 실제로 갈 수 있는지 확인한다. 배치 유효성만으로는 절벽 위처럼
    // 도달 불가한 자리에도 명령이 나가고, 그 드론은 임무 도장이 만료될 때까지
    // 채취도 건설도 하지 않는다.
    "sc2team_HostileWildCanReach",
    // §85: 대군주 확보는 훈련 else-if 체인 "밖"에서 독립적으로 돌아야 한다.
    // 체인 안에 있던 동안에는 위협 분기가 먼저 잡아 20게임분 내내 도달조차
    // 하지 못했고(대군주 신규 생산 0), 보급이 P15 병력 상한을 눌렀다.
    // 이 두 마커가 사라지면 그 회귀가 되돌아온 것이다.
    // §86에서 병력 상한이 폐지되며 수요가 늘어 문턱 16→24, 상한 2→6.
    // §89: 해처리 증설로 문턱 24→32, 상한 6→8.
    // §90.13: 문턱 32→48, 상한 8→12. 인구가 병목이면 둥지 순서가 곧 생산
    // 배분이 되어 라운드로빈만으로는 뒤 순번이 계속 굶는다.
    "gv_sc2team_HostileWildOverlordsThisTick < 12",
    "gv_sc2team_HostileWildOverlordsThisTick +=",
    // §89.14: 병력은 라바 훈련 명령으로만 나온다. §89.12의 UnitCreate 즉시
    // 생성(`ForceSpawn`)은 되돌렸다 — 생산이 아니라 치환이었고, 그 근거였던
    // "P15는 Requirements 유닛을 100% 거부한다"는 진단도 틀렸다(§87.6/§87.7/
    // §88.6 20분 계측 3회가 이 경로로 저글링 30/61/60기를 신규 생산했고, P15는
    // `HaveHatchery` 요구조건이 붙은 산란못을 11~12개 지었다). 이 마커가
    // 사라지면 그 오진으로 되돌아간 것이다.
    // §89.14/§89.16: 병력은 라바 훈련 명령으로만 나온다(§89.12의 UnitCreate
    // 즉시 생성은 사용자 지시로 되돌렸다 — 치환은 생산이 아니다). 인덱스는
    // §85.6 엔진 검증값: 저글링 1, 히드라 3, 바퀴 9, 울트라 6.
    // §90.7: 랠리는 둥지별로 지역화한다. 밀레 AI 가 모든 부화장 랠리를 한
    // 지점으로 몰면 외곽 둥지에서 나온 병력이 전부 그리로 행군해 둥지가 빈다.
    "AbilityCommand(\"RallyHatchery\", 0)",
    "AbilityCommand(\"RallyHatchery\", 1)",
    // §90.6: 광물 없는 둥지는 드론을 상비하지 않는다(멍하니 서 있기만 한다).
    // 건설이 필요할 때만 한 기 뽑고, 저그 드론은 건물이 되며 소모된다.
    "if (economyNest && workerCount < 2 &&",
    "sc2team_HostileWildTrainLarva(anchor, 1, forceCount)",
    "sc2team_HostileWildTrainLarva(anchor, 3, forceCount)",
    "sc2team_HostileWildTrainLarva(anchor, 9, forceCount)",
    "AbilityCommand(\"DroneHarvest\", 0)",
    "AbilityCommand(\"LarvaTrain\", commandIndex)",
    "AbilityCommand(\"ZergBuild\", 3)",
    "AbilityCommand(\"ZergBuild\", 13)",
    "AbilityCommand(\"ZergBuild\", 5)",
    "AbilityCommand(\"UpgradeToLair\", 0)",
    "AbilityCommand(\"ZergBuild\", 14)",
    "AbilityCommand(\"ZergBuild\", 0)",
    "PlayerModifyPropertyInt(15, c_playerPropMinerals, c_playerPropOperAdd, 50000)",
    "PlayerModifyPropertyInt(15, c_playerPropVespene, c_playerPropOperAdd, 50000)",
    "TimerGetElapsed(gv_sc2team_HostileWildTimer) >= 420.0",
    "unitType != \"Zergling\" && unitType != \"Baneling\"",
    "UnitSetCustomValue(currentUnit, 27, now + 60.0)",
    "gv_sc2team_HostileWildNextRaid = 420.0",
    // §88: 확장 상한 3 → 6 (성장 여지 확대, 사용자 지시).
    "gv_sc2team_HostileWildCompletedExpansions >= 6",
    // §88: 같은 틱 라바 발주 보호. 대군주/드론/병력 블록이 한 틱에 같은
    // 라바를 c_orderQueueReplace로 덮어쓰던 것이 "신규 대군주 0"의 원인 —
    // custom value 28 타임스탬프가 사라지면 그 회귀다.
    "UnitGetCustomValue(currentLarva, 28) == now",
    "UnitSetCustomValue(currentLarva, 28, now)",
    // §88: 둥지 복구(알파 최우선) + 알파 테크 진화 체인.
    "sc2team_HostileWildRememberNests",
    "sc2team_HostileWildTryRebuildNest",
    "sc2team_HostileWildBuildAlphaTech",
    "AbilityCommand(\"ZergBuild\", 7)",
    "AbilityCommand(\"ZergBuild\", 8)",
    "AbilityCommand(\"UpgradeToHive\", 0)",
    "AbilityCommand(\"LarvaTrain\", 6), true",
    // §90.13: 알파 = P15 시작 위치(사용자가 에디터에서 고른 핵심 본진).
    // 예전의 "맵에 유일한 Lair" 정의는 사용자가 시작 위치를 1시로 옮긴 뒤로
    // 3시를 가리켰고, 밀레 AI 의 본진(시작 위치)과 Galaxy 의 알파 특혜가
    // 갈라졌다. 이 마커가 사라지면 그 분열이 되돌아온 것이다.
    "gv_sc2team_HostileWildAlphaPoint = sc2team_HostileWildFindAlphaPoint();",
    "startPoint = PlayerStartLocation(15);",
    // §90.13: 생산 순서 — 알파 최우선 + 나머지 라운드로빈. 이게 없으면 둥지
    // 순회가 유닛 생성 순서를 그대로 따라, 선배치 부화장의 에디터 배치 순서가
    // 영구 우선순위가 된다(사용자 실관측: 목록 선두 두 곳만 병력을 뽑았다).
    "sc2team_HostileWildManageNest(gv_sc2team_HostileWildAlphaPoint, active);",
    "gv_sc2team_HostileWildNestCursor += 1;",
    // §90.13: 회전은 좌표 배열 위에서 한다. 유닛 그룹을 두 번 훑는 구현은
    // 연산 한도를 넘겨 100초 만에 생산이 죽었다(병력 6분간 104→120, 알 0~2,
    // 루프 밖 알파만 생존). 이 마커가 사라지면 그 회귀다.
    "gv_sc2team_HostileWildNestList[gv_sc2team_HostileWildNestListCount] =",
    "anchorPoint = gv_sc2team_HostileWildNestList[unitIndex];",
    // §90.13: 알파가 부화장에서 시작하므로 레어 변태 단계가 필요하다. 없으면
    // 감염 구덩이 분기의 Lair/Hive 조건에 걸려 알파 테크가 통째로 멈춘다.
    "lairOrder = Order(AbilityCommand(\"UpgradeToLair\", 0));",
    // §92: 인구 400 병력 천장(사용자 지시 "병력 상한을 둔다. 인구 400을 상한으로
    // 두겠다"). SuppliesUsed 기준이어야 한다 — §91.11 참조.
    "PlayerGetPropertyInt(15, c_playerPropSuppliesUsed) < 400",
  ];
  if (!config.melee_only) {
    for (const marker of wildZergActive ? hostileWildActiveMarkers : HOSTILE_WILD_IDLE_MARKERS) {
      if (!script.includes(marker)) fail(`P15 hostile wildlife marker is missing: ${marker}`);
    }
  }
  if (!wildZergActive && !config.melee_only) {
    for (const banned of HOSTILE_WILD_IDLE_BANNED) {
      if (script.includes(banned)) {
        fail(`Wild Zerg is disabled but the map script still contains: ${banned}`);
      }
    }
  }
  // §86: P15 **둥지별** 병력 목표(armyTarget)가 되살아나면 빌드 실패 — 멜리
  // 슬롯의 §68 saveForExpansion 금지와 같은 원칙이다("상한선 두지마", 사용자
  // 지시). 이 상한 때문에 선배치 병력만으로 목표를 채운 둥지가 초반 내내 드론만
  // 뽑았다. §92 의 인구 400 천장은 이것과 다르다: 플레이어 전역 한 곳에서만
  // 재고 둥지별 생산 배분을 왜곡하지 않으며, 일꾼·대군주·건설은 막지 않는다.
  if (script.includes("armyTarget")) {
    fail("P15 armyTarget production cap must stay removed");
  }
  // §89: 구성비 상한(desiredRoaches/desiredHydras)도 같은 원칙으로 폐지됐다
  // (사용자 지시 "병력 상한이고 나발이고 다 제거"). 되살아나면 빌드 실패.
  for (const identifier of ["desiredRoaches", "desiredHydras"]) {
    if (script.includes(identifier)) {
      fail(`P15 composition cap must stay removed: ${identifier}`);
    }
  }
  // §89.14: P15 병력을 UnitCreate 즉시 생성으로 만드는 경로는 금지다(사용자
  // 지시 "직접 생산도 아니고 — 롤백해라"). 알도 부화 시간도 없이 라바를 유닛으로
  // 치환하는 것은 생산이 아니다. 병력은 라바 훈련 명령으로만 나와야 한다.
  if (script.includes("sc2team_HostileWildForceSpawn")) {
    fail("P15 army must be trained from Larvae, not spawned by UnitCreate");
  }
  if (!/<ObjectUnit\b[^>]*\bUnitType="(?:Hatchery|Lair|Hive)"[^>]*\bPlayer="15"/.test(objects)) {
    fail("P15 hostile wildlife has no Zerg nest anchors");
  }
  const raceData = archive.readFileAsString(
    "Base.SC2Data\\GameData\\UnitData.xml",
    "utf8"
  );
  if (config.campaign_units_pilot) {
    for (const name of [
      "AbilData.xml", "UpgradeData.xml", "ButtonData.xml",
      "UnitData.xml", "EffectData.xml", "WeaponData.xml", "ActorData.xml", "ModelData.xml",
    ]) {
      const catalog = archive.readFileAsString(
        `Base.SC2Data\\GameData\\${name}`,
        "utf8",
      );
      if (!catalog.includes(`SC2TEAM_CAMPAIGN_ROSTER_${path.basename(name, ".xml")}_BEGIN`)) {
        fail(`Missing campaign roster catalog: ${name}`);
      }
    }
    for (const name of [
      "AbilData.xml", "ActorData.xml", "BehaviorData.xml", "ButtonData.xml",
      "EffectData.xml", "ModelData.xml", "RequirementData.xml",
      "RequirementNodeData.xml", "UnitData.xml", "UpgradeData.xml", "ValidatorData.xml",
    ]) {
      const catalog = archive.readFileAsString(
        `Base.SC2Data\\GameData\\${name}`,
        "utf8",
      );
      if (!catalog.includes(`SC2TEAM_NATIVE_TORRASQUE_${path.basename(name, ".xml")}_BEGIN`)) {
        fail(`Missing native Torrasque catalog: ${name}`);
      }
    }
    for (const name of ["ActorData.xml", "ModelData.xml"]) {
      const catalog = archive.readFileAsString(
        `Base.SC2Data\\GameData\\${name}`,
        "utf8",
      );
      if (!catalog.includes(`SC2TEAM_NATIVE_CAMPAIGN_ROSTER_${path.basename(name, ".xml")}_BEGIN`)) {
        fail(`Missing native campaign roster parents: ${name}`);
      }
    }
    const nativeSwarmModels = archive.readFileAsString(
      "Base.SC2Data\\GameData\\ModelData.xml",
      "utf8",
    );
    if (!nativeSwarmModels.includes("SC2TEAM_NATIVE_SWARM_ROSTER_ModelData_BEGIN")) {
      fail("Missing native Swarm roster models");
    }
    // A CModel parent does not inherit the Model asset path. A roster CModel
    // without its own <Model> renders as the gray placeholder sphere even
    // though catalog, create, and combat checks all pass.
    const rosterModelBlock = nativeSwarmModels.match(
      /SC2TEAM_CAMPAIGN_ROSTER_ModelData_BEGIN -->([\s\S]*?)<!-- SC2TEAM_CAMPAIGN_ROSTER_ModelData_END/,
    );
    if (!rosterModelBlock) fail("Missing campaign roster ModelData block");
    for (const entry of rosterModelBlock[1].matchAll(
      /<CModel\s+id="([^"]+)"[\s\S]*?(?:\/>|<\/CModel>)/g,
    )) {
      if (!/<Model\s+value="[^"]+\.m3"/.test(entry[0])) {
        fail(`Roster model has no explicit Model asset path: ${entry[1]}`);
      }
    }

    // A CActorUnit creates itself on "UnitBirth.##unitName##" and that token is
    // resolved where it is declared. Parenting from a concrete unit actor bakes in
    // the parent's unit name, so the actor never spawns for our unit and the unit
    // renders as a gray placeholder sphere while every catalog/create/combat probe
    // still passes. Only generic base actors leave the token unresolved.
    const rosterActors = archive.readFileAsString(
      "Base.SC2Data\\GameData\\ActorData.xml",
      "utf8",
    );
    const rosterActorBlock = rosterActors.match(
      /SC2TEAM_CAMPAIGN_ROSTER_ActorData_BEGIN -->([\s\S]*?)<!-- SC2TEAM_CAMPAIGN_ROSTER_ActorData_END/,
    );
    if (!rosterActorBlock) fail("Missing campaign roster ActorData block");
    for (const entry of rosterActorBlock[1].matchAll(
      /<CActorUnit\s+id="(SC2Team[^"]+)"([^>]*)>/g,
    )) {
      const parent = entry[2].match(/parent="([^"]+)"/);
      if (!parent) fail(`Roster actor has no parent: ${entry[1]}`);
      if (!parent[1].startsWith("Generic")) {
        fail(
          `Roster actor ${entry[1]} parents from concrete actor "${parent[1]}"; ` +
          "use a Generic* base actor or it never binds to the unit",
        );
      }
      if (!entry[2].includes(`unitName="${entry[1]}"`)) {
        fail(`Roster actor ${entry[1]} must set unitName="${entry[1]}"`);
      }
    }
    verifyRosterSounds(rosterActorBlock[1]);
    verifyRosterHotkeysAndTooltips(archive);
    verifyPurchaseCooldownSlots();
    // 변종은 울트라리스크에서 갈라진 전용 공격 효과를 쓰므로, 저그 근접 공격
    // 업그레이드가 자동으로 이어지지 않는다. 각 단계가 기본 피해 +2와 정보
    // 패널의 무기 레벨·아이콘을 모두 갱신하는지 별도로 고정한다.
    const rosterUpgradeData = archive.readFileAsString(
      "Base.SC2Data\\GameData\\UpgradeData.xml", "utf8",
    );
    for (const level of [1, 2, 3]) {
      const start = rosterUpgradeData.lastIndexOf(
        `<CUpgrade id="ZergMeleeWeaponsLevel${level}">`,
      );
      if (start < 0) fail(`Aberration melee upgrade override missing: level ${level}`);
      const record = rosterUpgradeData.slice(
        start, rosterUpgradeData.indexOf("</CUpgrade>", start),
      );
      for (const marker of [
        '<EffectArray Reference="Effect,SC2TeamAberrationDamage,Amount" Value="2"/>',
        '<EffectArray Reference="Weapon,SC2TeamAberrationWeapon,Level" Value="1"/>',
        `btn-upgrade-zerg-meleeattacks-level${level}.dds`,
      ]) {
        if (!record.includes(marker)) {
          fail(`Aberration melee upgrade reference missing (level ${level}): ${marker}`);
        }
      }
    }
    if (config.strategy_bridge && !config.bridge_probe) {
      for (let index = 0; index < activeSlots.length; index += 1) {
        const slot = activeSlots[index];
        if (slot.controller !== "custom_ai") continue;
        const player = index + 1;
        const preferred = PREFERRED_STOCK_BY_BUILD[slot.build] ?? {};
        for (const unitType of Object.keys(preferred)) {
          const purchase = CAMPAIGN_PURCHASE_BY_UNIT[unitType];
          if (purchase === undefined) continue;
          const call = `sc2team_TryPurchaseCampaignUnit(${player}, "${purchase.producer}", "${purchase.prerequisite}", "${unitType}"`;
          if (!script.includes(call)) {
            fail(`Missing campaign purchase for runtime P${player}: ${unitType}`);
          }
        }
        // §87: 직접 훈련 디스패처 — 멜레 병종(비구매) 전 항목에 대해 정확한
        // 생산자/능력/커맨드 인덱스의 훈련 호출이 있어야 한다. 인덱스가 틀리면
        // 엉뚱한 유닛이 나오거나 조용한 무동작이 되므로 표와 호출을 강결합한다.
        // random_ground(종족 고정)는 코드젠과 같은 종족별 기본 세트를 요구한다.
        const trainSource = slot.build === "random_ground" && slot.race !== "Random"
          ? (RANDOM_TRAIN_BY_RACE[slot.race] ?? {})
          : preferred;
        for (const unitType of Object.keys(trainSource)) {
          // 캠페인 유닛은 구매 경로(pilot on) 또는 부재(pilot off) — 디스패처 밖.
          if (CAMPAIGN_PURCHASE_BY_UNIT[unitType] !== undefined) continue;
          const train = DIRECT_TRAIN_BY_UNIT[unitType];
          if (train === undefined) {
            fail(`Missing direct-train table entry for ${unitType}`);
          }
          const call = train.morphFrom
            ? `sc2team_TryMorphMeleeUnit(${player}, "${train.morphFrom}", "${train.abil}", ${train.index},`
            : `sc2team_TryTrainMeleeUnit(${player}, "${train.producer}", "${train.abil}", ${train.index},`;
          if (!script.includes(call)) {
            fail(`Missing direct-train call for runtime P${player}: ${unitType}`);
          }
          if (train.warpAbil &&
              !script.includes(`sc2team_TryWarpTrain(${player}, "${train.warpAbil}", ${train.warpIndex},`)) {
            fail(`Missing warp-train call for runtime P${player}: ${unitType}`);
          }
        }
        // §69: 랩터 진화 구매는 ling/ultra 빌드 + random_ground 저그 슬롯(둘 다
        // campaign pilot일 때만 생성)이 대상이므로 verify도 같은 조건을 쓴다.
        const wantsRaptor = config.campaign_units_pilot &&
          ((PREFERRED_UPGRADES_BY_BUILD[slot.build] ?? []).includes("SC2TeamRaptorEvolution") ||
           (slot.build === "random_ground" && slot.race === "Zerg"));
        if (wantsRaptor &&
            !script.includes(`sc2team_TryPurchaseRaptorEvolution(${player});`)) {
          fail(`Missing Raptor purchase for runtime P${player}`);
        }
        // §88: 보급 선제 확보 — 테란은 보급고 AIBuild + 궤도 SupplyDrop,
        // 프로토스는 파일런 AIBuild. 빠지면 §87 디스패처가 인구에 막힌다.
        if (slot.race === "Terran") {
          for (const call of [
            `sc2team_TrySupplyStructure(${player}, "SupplyDepot");`,
            `sc2team_TryCalldownSupplies(${player});`,
          ]) {
            if (!script.includes(call)) {
              fail(`Missing supply support for runtime P${player}: ${call}`);
            }
          }
        }
        // §91.10: 보급 막힘 판정은 SuppliesMade(현재 공급량) 기준이어야 한다.
        // SuppliesLimit 은 맵 천장(800)이라 그것으로 여유를 재면 게이트가 영구히
        // 닫힌다 — §88 보급 지원 전체가 그 상태로 출시돼 있었다. 되돌아오면 실패.
        if (!script.includes("made - used < 32")) {
          fail("Supply-blocked check must measure headroom against SuppliesMade");
        }
        if (script.includes("limit - used <")) {
          fail("Supply-blocked check must not measure headroom against SuppliesLimit");
        }
        // §91.11: 같은 혼동이 캠페인 구매와 P15 대군주에도 있었다. SuppliesLimit
        // 을 읽어도 되는 곳은 "천장에 도달했는가" 비교(made < ceiling) 하나뿐이다.
        // 남은 사용처를 세어 새 오용이 끼어들면 빌드를 실패시킨다.
        // 주석 줄은 세지 않는다(설명에 상수 이름이 나오는 것은 정상이다).
        const limitReads = script
          .split("\n")
          .filter((line) => !line.trim().startsWith("//"))
          .join("\n")
          .match(/c_playerPropSuppliesLimit/g)?.length ?? 0;
        if (limitReads !== 1) {
          fail(
            `c_playerPropSuppliesLimit must be read exactly once (the made<ceiling guard); found ${limitReads}. ` +
            "Supply headroom and affordability must use c_playerPropSuppliesMade."
          );
        }
        // §91.9: 파일런은 AIBuild "부탁"만으로는 정지한다(계측: 6슬롯 중 3개가
        // 14/7/6분간 증가 0). 탐사정 직접 발주가 보장 경로이므로 둘 다 요구한다.
        if (slot.race === "Protoss") {
          for (const call of [
            `sc2team_TrySupplyStructure(${player}, "Pylon");`,
            `sc2team_TryBuildPylonDirect(${player});`,
          ]) {
            if (!script.includes(call)) {
              fail(`Missing supply support for runtime P${player}: ${call}`);
            }
          }
        }
      }
      // §63: 구매 틱 라인은 구매 유닛을 목표 재고에 둔 슬롯이 있을 때만
      // 생성되므로, 그 경우에만 비율 선택·교차 게이트 마커를 요구한다.
      const hasPurchaseSlots = activeSlots.some(
        (slot) => slot.controller === "custom_ai" &&
          Object.keys(PREFERRED_STOCK_BY_BUILD[slot.build] ?? {}).some(
            (unitType) => CAMPAIGN_PURCHASE_BY_UNIT[unitType] !== undefined,
          ),
      );
      for (const marker of [
        "PlayerGetPropertyInt(player, c_playerPropSuppliesUsed)",
        "PlayerModifyPropertyInt(player, c_playerPropMinerals",
        "UnitSetCustomValue(currentUnit, customValueIndex, now + cooldown)",
        // §61 구매 잔고 하한선과 비율 기반 우선순위가 빠지면 빌드 실패.
        // §87: 하한 검사는 다중 구매 루프 "안"에 있어야 한다(매 구매 후 재검사).
        "PlayerGetPropertyInt(player, c_playerPropMinerals) < mineralCost + 500",
        "PlayerGetPropertyInt(player, c_playerPropVespene) < gasCost + 400",
        // §87: 라바 구매 상한(라바는 구매가 소모하므로 무상한이면 라바 풀 전멸).
        "if (maxCount > 0 && bought >= maxCount)",
        ...(hasPurchaseSlots ? ["purchaseBestRatio"] : []),
      ]) {
        if (!script.includes(marker)) fail(`Missing campaign purchase guard: ${marker}`);
      }
      // §87: 틱당 1기 상한과 §62 교차 게이트는 폐지됐다(사용자 지시 — "돈 많고
      // 팩토리 많으면 뭐해"). 게이트가 되살아나면 빌드 실패.
      if (script.includes("meleeWorstRatio")) {
        fail("Campaign purchase cross-pool gate must stay removed");
      }
      // §87: 직접 훈련 디스패처 전역 마커. 멜레 AI의 AISetStock 단독 의존은
      // §62/§71/§82에서 세 번 기각됐다 — 훈련도 직접 명령이 유일한 보장 경로다.
      for (const marker of [
        "sc2team_TryTrainMeleeUnit",
        "sc2team_TryWarpTrain",
        "sc2team_TryMorphMeleeUnit",
        // 멜레 AI 대기열을 교체하지 않는다(추가만).
        "UnitIssueOrder(currentUnit, trainOrder, c_orderQueueAddToEnd)",
        "UnitIssueOrder(currentUnit, morphOrder, c_orderQueueAddToEnd)",
        "UnitIssueOrder(currentUnit, warpOrder, c_orderQueueAddToEnd)",
        // §82 애드온 굶김 방지: 애드온 가능 건물 1개를 유휴로 남기는 예약 로직.
        "addonReserved = true;",
        // 라바 보존(멜레 저그의 드론·대군주 생산 보호).
        "if (remaining <= leaveIdle)",
      ]) {
        if (!script.includes(marker)) fail(`Missing direct-train marker: ${marker}`);
      }
      // 사람 슬롯에는 어떤 훈련 명령도 나가면 안 된다(§63 연구와 같은 원칙).
      // (옵저버 모드는 사람 슬롯이 AI로 변환되므로 훈련 명령이 실리는 게 정상.)
      if (!config.observer_mode) {
        for (const helper of [
          "sc2team_TryTrainMeleeUnit",
          "sc2team_TryWarpTrain",
          "sc2team_TryMorphMeleeUnit",
        ]) {
          if (script.includes(`${helper}(${humanRuntimeId},`)) {
            fail(`Direct-train order targets the human slot: ${helper}`);
          }
        }
        // §88: 보급 지원도 사람 슬롯에는 나가면 안 된다(같은 원칙).
        if (script.includes(`sc2team_TrySupplyStructure(${humanRuntimeId},`) ||
            script.includes(`sc2team_TryCalldownSupplies(${humanRuntimeId})`)) {
          fail("Supply-support order targets the human slot");
        }
      }
    }
  }
  const protossFaction = config.protoss_faction ?? "Standard";
  if (protossFaction !== "Standard") {
    const actorData = archive.readFileAsString(
      "Base.SC2Data\\GameData\\ActorData.xml",
      "utf8",
    );
    const modelData = archive.readFileAsString(
      "Base.SC2Data\\GameData\\ModelData.xml",
      "utf8",
    );
    if (!actorData.includes("SC2TEAM_PROTOSS_FACTION_ActorData_BEGIN") ||
        !modelData.includes("SC2TEAM_PROTOSS_FACTION_ModelData_BEGIN")) {
      fail(`Missing Protoss faction catalogs for ${protossFaction}`);
    }
    const sentinelModel = PROTOSS_FACTION_SENTINEL_MODEL[protossFaction];
    if (!actorData.includes(`Model value="${sentinelModel}"`) ||
        !modelData.includes(`id="${sentinelModel}"`)) {
      fail(`Wrong Protoss faction model wiring for ${protossFaction}`);
    }
    if (protossFaction === "Aiur") {
      const abilData = archive.readFileAsString(
        "Base.SC2Data\\GameData\\AbilData.xml",
        "utf8",
      );
      const effectData = archive.readFileAsString(
        "Base.SC2Data\\GameData\\EffectData.xml",
        "utf8",
      );
      const weaponData = archive.readFileAsString(
        "Base.SC2Data\\GameData\\WeaponData.xml",
        "utf8",
      );
      const moverData = archive.readFileAsString(
        "Base.SC2Data\\GameData\\MoverData.xml",
        "utf8",
      );
      const turretData = archive.readFileAsString(
        "Base.SC2Data\\GameData\\TurretData.xml",
        "utf8",
      );
      const factionUnitData = archive.readFileAsString(
        "Base.SC2Data\\GameData\\UnitData.xml",
        "utf8",
      );
      for (const marker of [
        '<CAbilEffectInstant id="VoidZealotWhirlwind">',
        '<Flags index="AutoCast" value="1"/>',
        '<Flags index="AutoCastOn" value="1"/>',
        '<AutoCastValidatorArray value="VoidZealotWhirlwindCheck"/>',
      ]) {
        if (!abilData.includes(marker)) fail(`Aiur Whirlwind wiring missing: ${marker}`);
      }
      for (const marker of [
        '<CEffectDamage id="VoidZealotWhirlwindDamage"',
        '<CEffectDamage id="DragoonDamage"',
        '<AttributeBonus index="Armored" value="8"/>',
      ]) {
        if (!effectData.includes(marker)) fail(`Aiur combat effect missing: ${marker}`);
      }
      for (const marker of [
        '<CWeaponLegacy id="SolariteReaper">',
        '<CWeaponLegacy id="Dragoon">',
        '<Range value="7"/>',
      ]) {
        if (!weaponData.includes(marker)) fail(`Aiur weapon missing: ${marker}`);
      }
      for (const marker of [
        '<CUnit id="Zealot">',
        '<AbilArray Link="VoidZealotWhirlwind"/>',
        '<CUnit id="Stalker">',
        '<AbilArray index="5" removed="1"/>',
        '<Mover value="Dragoon"/>',
        '<WeaponArray index="0" Link="Dragoon" Turret="Dragoon"/>',
        '<LifeMax value="120"/>',
      ]) {
        if (!factionUnitData.includes(marker)) fail(`Aiur unit replacement missing: ${marker}`);
      }
      for (const marker of [
        '<CMoverMissile id="DragoonWeapon">',
        '<CMoverAvoid id="Dragoon" parent="Ground">',
      ]) {
        if (!moverData.includes(marker)) fail(`Aiur Dragoon mover missing: ${marker}`);
      }
      if (!turretData.includes('<CTurret id="Dragoon">')) {
        fail("Aiur Dragoon turret catalog missing");
      }
      for (const marker of [
        '<CActorUnit id="Stalker" parent="GenericUnitBase" unitName="Stalker">',
        '<Model value="Dragoon"/>',
        '<WalkAnimMoveSpeed value="1.25"/>',
        '<CActorTurret id="DragoonTurret">',
        '<CActorMissile id="DragoonAttackMissile"',
      ]) {
        if (!actorData.includes(marker)) fail(`Aiur Dragoon actor missing: ${marker}`);
      }
      const koStrings = archive.readFileAsString(
        "koKR.SC2Data\\LocalizedData\\GameStrings.txt", "utf8",
      );
      const enStrings = archive.readFileAsString(
        "enUS.SC2Data\\LocalizedData\\GameStrings.txt", "utf8",
      );
      if (!koStrings.includes("Unit/Name/Stalker=용기병") ||
          !enStrings.includes("Unit/Name/Stalker=Dragoon")) {
        fail("Aiur Dragoon localized Stalker replacement name missing");
      }
      // §67: 멜레 공업은 효과 id 참조라 교체 무기에는 저절로 적용되지 않는다.
      // 지상 공업 1~3레벨 전부에 아이어 참조가 덧붙었는지 확인한다.
      const upgradeData = archive.readFileAsString(
        "Base.SC2Data\\GameData\\UpgradeData.xml", "utf8",
      );
      for (const level of [1, 2, 3]) {
        const start = upgradeData.lastIndexOf(
          `<CUpgrade id="ProtossGroundWeaponsLevel${level}">`,
        );
        if (start < 0) fail(`Aiur weapon upgrade override missing: level ${level}`);
        const record = upgradeData.slice(
          start, upgradeData.indexOf("</CUpgrade>", start),
        );
        for (const marker of [
          '<EffectArray Reference="Effect,ZealotAiurWeapon,Amount" Value="2"/>',
          '<EffectArray Reference="Effect,VoidZealotWhirlwindDamage,Amount" Value="1"/>',
          '<EffectArray Reference="Effect,DragoonDamage,Amount" Value="1"/>',
          '<EffectArray Reference="Effect,DragoonDamage,AttributeBonus[Armored]" Value="1"/>',
          '<EffectArray Reference="Weapon,SolariteReaper,Level" Value="1"/>',
          '<EffectArray Reference="Weapon,Dragoon,Level" Value="1"/>',
          `btn-upgrade-protoss-groundweaponslevel${level}.dds`,
        ]) {
          if (!record.includes(marker)) {
            fail(`Aiur weapon upgrade reference missing (level ${level}): ${marker}`);
          }
        }
      }
    } else if (protossFaction === "Nerazim") {
      const abilData = archive.readFileAsString(
        "Base.SC2Data\\GameData\\AbilData.xml", "utf8",
      );
      const effectData = archive.readFileAsString(
        "Base.SC2Data\\GameData\\EffectData.xml", "utf8",
      );
      const factionUnitData = archive.readFileAsString(
        "Base.SC2Data\\GameData\\UnitData.xml", "utf8",
      );
      for (const marker of [
        '<CAbilAugment id="ShadowCharge">',
        '<CAbilAugment id="ShadowChargeStun">',
        '<CAbilEffectTarget id="ImmortalShakurasShadowCannon">',
        '<CAbilEffectTarget id="DarkArchonMindControl">',
        '<CAbilEffectTarget id="DarkArchonConfusion">',
        '<CAbilEffectTarget id="BlinkShieldRestore">',
      ]) {
        if (!abilData.includes(marker)) fail(`Nerazim ability wiring missing: ${marker}`);
      }
      const shadowCannonRecord = abilData.slice(
        abilData.indexOf('<CAbilEffectTarget id="ImmortalShakurasShadowCannon">'),
        abilData.indexOf('</CAbilEffectTarget>', abilData.indexOf('<CAbilEffectTarget id="ImmortalShakurasShadowCannon">')),
      );
      if (shadowCannonRecord.includes('AutoCast')) {
        fail("Nerazim Shadow Cannon must retain its original manual-cast flags");
      }
      for (const marker of [
        '<CEffectTeleport id="VoidStalkerBlinkShieldRestore"',
        '<TeleportEffect value="VoidStalkerBlinkApplyRestore"',
        '<CEffectDamage id="ImmortalShakurasShadowCannonDamage">',
      ]) {
        if (!effectData.includes(marker)) fail(`Nerazim combat effect missing: ${marker}`);
      }
      for (const marker of [
        '<AbilArray index="5" Link="ShadowCharge"',
        '<AbilArray index="5" Link="ImmortalShakurasShadowCannon"',
        '<AbilArray Link="DarkArchonMindControl"',
        '<AbilArray Link="DarkArchonConfusion"',
        '<AbilArray index="5" Link="BlinkShieldRestore"',
      ]) {
        if (!factionUnitData.includes(marker)) fail(`Nerazim unit wiring missing: ${marker}`);
      }
    } else if (protossFaction === "Purifier") {
      const abilData = archive.readFileAsString(
        "Base.SC2Data\\GameData\\AbilData.xml", "utf8",
      );
      const behaviorData = archive.readFileAsString(
        "Base.SC2Data\\GameData\\BehaviorData.xml", "utf8",
      );
      const factionUnitData = archive.readFileAsString(
        "Base.SC2Data\\GameData\\UnitData.xml", "utf8",
      );
      for (const marker of [
        '<CAbilEffectTarget id="BlinkMultiple">',
        '<CountMax value="3"',
        '<CountStart value="3"',
        '<TimeUse value="4"',
        '<CAbilEffectTarget id="VoidSentryChronoBeam">',
        '<CAbilMorph id="VoidSentryPhasingMode">',
        '<CAbilMorph id="ZealotPurifierReviveDeath">',
      ]) {
        if (!abilData.includes(marker)) fail(`Purifier multi-Blink missing: ${marker}`);
      }
      if (!factionUnitData.includes('<AbilArray index="5" Link="BlinkMultiple"')) {
        fail("Purifier Stalker is not wired to three-charge Blink");
      }
      for (const marker of [
        '<CBehaviorBuff id="ZealotPurifierRevive">',
        '<Handled value="ZealotPurifierReviveDeadIssueOrder"',
        '<CBehaviorBuff id="ZealotPurifierReviveSupressed">',
        '<Duration value="120"',
        '<CBehaviorBuff id="VoidSentryChronoBeam">',
      ]) {
        if (!behaviorData.includes(marker)) fail(`Purifier Reconstruction missing: ${marker}`);
      }
      for (const marker of [
        '<BehaviorArray Link="ZealotPurifierRevive"',
        '<Attributes index="Mechanical" value="1"',
        '<AbilArray Link="VoidSentryChronoBeam"',
        '<AbilArray Link="VoidSentryPhasingMode"',
        '<CUnit id="ZealotPurifierReviveCorpse" parent="Zealot">',
      ]) {
        if (!factionUnitData.includes(marker)) fail(`Purifier Sentinel wiring missing: ${marker}`);
      }
    } else if (protossFaction === "Taldarim") {
      const abilData = archive.readFileAsString(
        "Base.SC2Data\\GameData\\AbilData.xml", "utf8",
      );
      const effectData = archive.readFileAsString(
        "Base.SC2Data\\GameData\\EffectData.xml", "utf8",
      );
      const behaviorData = archive.readFileAsString(
        "Base.SC2Data\\GameData\\BehaviorData.xml", "utf8",
      );
      const factionUnitData = archive.readFileAsString(
        "Base.SC2Data\\GameData\\UnitData.xml", "utf8",
      );
      for (const marker of [
        '<CAbilEffectTarget id="BlinkSlayer"',
        '<CAbilEffectInstant id="AlarakZealotFrenziedOverload">',
        '<Flags index="AutoCastOn" value="1"',
        '<CAbilEffectTarget id="ObserverTargetLock">',
        '<CAbilEffectTarget id="ForceFieldMonitor">',
        '<CAbilEffectTarget id="VoidHighTemplarMindBlast">',
        '<CAbilEffectTarget id="VoidHighTemplarPsiOrb">',
        '<CAbilEffectTarget id="AscendantSacrifice">',
      ]) {
        if (!abilData.includes(marker)) fail(`Taldarim ability wiring missing: ${marker}`);
      }
      for (const marker of [
        '<CEffectSet id="PhaseBlinkSet"',
        '<EffectArray value="PhaseBlinkDamageAB"',
      ]) {
        if (!effectData.includes(marker)) fail(`Taldarim Blink effect missing: ${marker}`);
      }
      for (const marker of [
        '<CBehaviorBuff id="PhaseBlinkDamage">',
        '<Duration value="8"',
        '<DamageDealtFraction index="Ranged" value="1"',
      ]) {
        if (!behaviorData.includes(marker)) fail(`Taldarim damage buff missing: ${marker}`);
      }
      for (const marker of [
        '<AbilArray Link="ObserverTargetLock"',
        '<AbilArray Link="ForceFieldMonitor"',
        '<AbilArray index="2" Link="VoidHighTemplarMindBlast"',
        '<AbilArray index="6" Link="VoidHighTemplarPsiOrb"',
        '<AbilArray index="7" Link="AscendantSacrifice"',
      ]) {
        if (!factionUnitData.includes(marker)) fail(`Taldarim caster wiring missing: ${marker}`);
      }
    }
  }
  if (config.campaign_units_probe_damage &&
      !script.includes("sc2team_InitializeTorrasqueProbeDamage();")) {
    fail("Torrasque damage probe trigger is missing");
  }
  if (config.campaign_units_pilot) {
    for (let index = 0; index < activeSlots.length; index += 1) {
      if (activeSlots[index].race !== "Zerg") continue;
      const player = index + 1;
      if (!script.includes(`TechTreeUpgradeAddLevel(${player}, "HotSTorrasque", 1);`)) {
        fail(`Native Torrasque upgrade is missing for runtime P${player}`);
      }
    }
  }
  if (archive.hasFile("Base.SC2Data\\GameData\\RaceData.xml")) {
    fail("RaceData.xml would shadow standard starting-unit records");
  }
  for (const raceId of ["Terr", "Prot", "Zerg"]) {
    const raceRecord = new RegExp(
      `<CRace\\b[^>]*\\bid=["']${raceId}["'][^>]*>[\\s\\S]*?` +
      `<FoodCeiling\\b[^>]*\\bvalue=["']800["']`,
      "i"
    );
    if (!raceRecord.test(raceData)) fail(`Missing 800 food ceiling for ${raceId}`);
  }
  if (!script.includes("sc2team_InitializeRuntime();")) {
    fail("Runtime script verification failed");
  }
  if (((config.strategy_bridge && !config.bridge_probe) || config.melee_only) &&
      !script.includes("MeleeInitAI();")) {
    fail("This runtime requires Blizzard melee AI");
  }
  if (config.strategy_bridge && !config.bridge_probe && !config.melee_only &&
      !script.includes("sc2team_InitializeProductionRules();")) {
    fail("Strategy bridge production rules are missing");
  }
  const productionInitCount = (
    script.match(/sc2team_InitializeProductionRules\(\);/g) || []
  ).length;
  if (config.strategy_bridge && !config.bridge_probe && !config.melee_only && productionInitCount !== 1) {
    fail(`Expected one production-rule initialization, got ${productionInitCount}`);
  }
  if (((!config.strategy_bridge || config.bridge_probe) || config.melee_only) && productionInitCount !== 0) {
    fail("Isolated bridge unexpectedly initializes production rules");
  }
  if (config.strategy_bridge && !config.bridge_probe && !config.melee_only) {
    for (let index = 0; index < activeSlots.length; index += 1) {
      const slot = activeSlots[index];
      if (slot.controller !== "custom_ai") continue;
      const player = index + 1;
      const races = slot.race === "Random" ? ["Terran", "Protoss", "Zerg"] : [slot.race];
      for (const race of races) {
        for (const unitType of COMBAT_AIR_BY_RACE[race]) {
          const cap = `TechTreeSetProduceCap(${player}, "${unitType}", c_techCatUnit, 0);`;
          if (!script.includes(cap)) fail(`Missing combat-air cap for runtime P${player}: ${unitType}`);
        }
        for (const unitType of SUPPORT_AIR_BY_RACE[race]) {
          const expectedCap = supportAirCap(
            slot.build,
            unitType,
            config.allow_support_air !== false,
          );
          const cap = `TechTreeSetProduceCap(${player}, "${unitType}", c_techCatUnit, ${expectedCap});`;
          if (!script.includes(cap)) fail(`Missing support-air cap for runtime P${player}: ${unitType}`);
        }
      }
      // §71: random_ground(종족 고정)는 종족별 인프라 표를 쓴다.
      const infraPlan = slot.build === "random_ground" && slot.race !== "Random"
        ? (RANDOM_INFRA_BY_RACE[slot.race] ?? {})
        : PREFERRED_INFRA_BY_BUILD[slot.build];
      for (const [unitType, count] of Object.entries(infraPlan)) {
        const stock = `AISetStock(${player}, ${count}, "${unitType}");`;
        if (!script.includes(stock)) fail(`Missing infrastructure stock for runtime P${player}: ${unitType}`);
      }
      // §71: 인프라(연구 보강 포함) 전 항목에 재건 AIBuild 발주가 있어야 한다.
      if (slot.race !== "Random") {
        const mergedInfra = { ...infraPlan };
        for (const [unitType, count] of Object.entries(RESEARCH_INFRA_BY_RACE[slot.race] ?? {})) {
          if (!(unitType in mergedInfra)) mergedInfra[unitType] = count;
        }
        const forcedTypes = new Set(
          (FORCED_INFRASTRUCTURE_BY_BUILD[slot.build] ?? []).map((request) => request.unitType)
        );
        for (const unitType of Object.keys(mergedInfra)) {
          if (forcedTypes.has(unitType)) continue;
          const rebuild = `AIBuild(${player}, c_makePriorityTown, AIGetMainTown(${player}), "${unitType}", 1, c_nearChokePoint);`;
          if (!script.includes(rebuild)) {
            fail(`Missing infrastructure rebuild order for runtime P${player}: ${unitType}`);
          }
        }
      }
      for (const request of FORCED_INFRASTRUCTURE_BY_BUILD[slot.build] ?? []) {
        const build = `AIBuild(${player}, c_makePriorityTown, AIGetMainTown(${player}), "${request.unitType}", 1, c_nearChokePoint);`;
        const prerequisite = `sc2team_CountCompletedProduction(${player}, "${request.prerequisite}") >= 1`;
        if (!script.includes(build) || !script.includes(prerequisite)) {
          fail(`Missing forced infrastructure request for runtime P${player}: ${request.unitType}`);
        }
      }
      for (const [unitType, count] of Object.entries(FIXED_STRUCTURE_CAPS_BY_BUILD[slot.build])) {
        const cap = `TechTreeSetProduceCap(${player}, "${unitType}", c_techCatUnit, ${count});`;
        if (!script.includes(cap)) fail(`Missing fixed production cap for runtime P${player}: ${unitType}`);
      }
      if (slot.race !== "Random") {
        const scalingPlan = slot.build === "random_ground"
          ? RANDOM_SCALING_PRODUCTION_BY_RACE[slot.race]
          : SCALING_PRODUCTION_BY_BUILD[slot.build];
        for (const [unitType, scale] of Object.entries(scalingPlan)) {
          // §68: 부유 보너스(richBonus)가 스케일 목표에 붙는다.
          const desired = `desired = ${scale.base} + ((bases - 1) * ${scale.perExpansion}) + richBonus;`;
          // §62: 팩토리는 상한 없음, 나머지는 목표 수가 상한.
          const cap = unitType === "Factory"
            ? `TechTreeSetProduceCap(${player}, "${unitType}", c_techCatUnit, -1);`
            : `TechTreeSetProduceCap(${player}, "${unitType}", c_techCatUnit, desired);`;
          const stock = `AISetStock(${player}, desired + 1, "${unitType}");`;
          if (!script.includes(desired) || !script.includes(cap) || !script.includes(stock)) {
            fail(`Missing scaling production target for runtime P${player}: ${unitType}`);
          }
          if (unitType === "Factory" &&
              !script.includes(`AISetStock(${player}, desired, "FactoryTechLab");`)) {
            fail(`Missing FactoryTechLab stock request for runtime P${player}`);
          }
        }
        // §97: AIExpand도 전달 좌표와 다른 안전지대에 본진 건물을 놓을 수
        // 있으므로 금지한다. 검증 좌표에 종족별 일꾼 건설 명령을 직접 내린다.
        const townHall = EXPANSION_TOWN_HALL_BY_RACE[slot.race];
        if (script.includes(`AISetStockExpand(${player},`)) {
          fail(`Runtime P${player} must not use AISetStockExpand placement`);
        }
        for (const required of [
          `sc2team_NextExpansionPointP${player}(${player})`,
          `sc2team_TryBuildExpansionAt(${player}, "${slot.race}", expansionTarget)`,
          `sc2team_ExpansionCandidateOwnedByPlayer(gv_sc2team_ExpansionRequestedCandidate[${player}], ${player})`,
          `TechTreeUnitAllow(${player}, "${townHall}", canExpand)`,
          `TechTreeSetProduceCap(${player}, "${townHall}", c_techCatUnit, townHallCap)`,
        ]) {
          if (!script.includes(required)) {
            fail(`Missing validated expansion controller for runtime P${player}: ${required}`);
          }
        }
        // 허가(TechTreeUnitAllow/SetProduceCap)는 직접 건설 발주보다 반드시 앞에
        // 있어야 한다. sc2team_TryBuildExpansionAt는 UnitOrderIsValid로 그 자리에서
        // 판정하므로, 허가가 뒤에 있으면 직전 틱의 "본진 금지" 상태를 보고 매번
        // 실패하면서 townHallCap +1만 열어 밀리 AI가 본진 앞에 타운홀을 쌓는다.
        // 옛 AIExpand는 비동기 요청이라 이 순서가 무해했기 때문에 마커 존재
        // 검사만으로는 이 회귀를 잡지 못한다.
        const steerStart = script.indexOf(`void sc2team_SteerP${player} ()`);
        if (steerStart < 0) {
          fail(`Missing steering function for runtime P${player}`);
        }
        const nextSteer = script.indexOf("\nvoid sc2team_SteerP", steerStart + 1);
        const steerBody = script.slice(
          steerStart,
          nextSteer > 0 ? nextSteer : undefined,
        );
        const allowAt = steerBody.indexOf(
          `TechTreeUnitAllow(${player}, "${townHall}", canExpand)`,
        );
        const buildAt = steerBody.indexOf(`sc2team_TryBuildExpansionAt(${player},`);
        if (allowAt < 0 || buildAt < 0 || allowAt > buildAt) {
          fail(
            `Runtime P${player}: expansion allowance must be applied before the direct build order`,
          );
        }
        // §105.8(감사 B1): 타운홀 전멸 비상구. §96에 있던 이 줄은 문서에만
        // 있고 마커가 없어서 §97/§98 재작성 때 기록 없이 사라졌다 — 같은
        // 실수를 막기 위해 슬롯별 필수 마커로 강제하고, 허가 줄보다 앞에
        // 있어야 한다(§98 순서 불변식의 일부).
        const wipeoutAt = steerBody.indexOf(
          "if (totalBases == 0) { canExpand = true; townHallCap = townHallTypeCount + 1; }",
        );
        if (wipeoutAt < 0 || wipeoutAt > allowAt) {
          fail(
            `Runtime P${player}: town-hall wipeout recovery line must precede the expansion allowance (§96/§105.8)`,
          );
        }
      }
      // §82: Terran addons must use real producer commands, not an ignored
      // stock request or AIBuild (addons attach to the producer itself).
      if (slot.race === "Terran") {
        if (!script.includes("sc2team_TryBuildTerranAddon") ||
            !script.includes("UnitOrderIsValid") ||
            !script.includes("OrderTargetingPoint")) {
          fail("Missing Terran addon command helper");
        }
        const bioBuild = slot.build === "bio" || slot.build === "bio_tank";
        const factoryBuild = ["bio_tank", "hellion_tank", "thor_tank", "mech_macro"].includes(slot.build);
        const expectAddonOrder = (producer, addon, ability, commandIndex) => {
          const call = `sc2team_TryBuildTerranAddon(${player}, "${producer}", "${addon}", "${ability}", ${commandIndex}, addonTarget);`;
          if (!script.includes(call)) {
            fail(`Missing Terran addon order for runtime P${player}: ${addon}`);
          }
        };
        if (bioBuild) {
          expectAddonOrder("Barracks", "BarracksTechLab", "BarracksAddOns", 0);
          expectAddonOrder("Barracks", "BarracksReactor", "BarracksAddOns", 1);
        }
        if (factoryBuild) {
          expectAddonOrder("Factory", "FactoryTechLab", "FactoryAddOns", 0);
        }
        if (config.allow_support_air !== false) {
          expectAddonOrder("Starport", "StarportTechLab", "StarportAddOns", 0);
        }
      }
      for (const [unitType, count] of Object.entries(PREFERRED_STOCK_BY_BUILD[slot.build])) {
        // §68: 병력 재고는 종족 불문 도달 불가능한 고정 배수 목표.
        const stock = `AISetStock(${player}, ${count * STOCK_SQUEEZE_MULTIPLIER}, "${unitType}");`;
        if (!script.includes(stock)) fail(`Missing preferred stock for runtime P${player}: ${unitType}`);
      }
      for (const upgradeType of PREFERRED_UPGRADES_BY_BUILD[slot.build]) {
        const stock = `AISetStock(${player}, 1, "${upgradeType}");`;
        if (!script.includes(stock)) fail(`Missing preferred upgrade for runtime P${player}: ${upgradeType}`);
      }
      // §63: 연구 인프라 보강과 연구 명령 체인이 슬롯마다 실제로 생성됐는지.
      for (const [unitType, count] of Object.entries(RESEARCH_INFRA_BY_RACE[slot.race] ?? {})) {
        const expected = PREFERRED_INFRA_BY_BUILD[slot.build][unitType] ?? count;
        const stock = `AISetStock(${player}, ${expected}, "${unitType}");`;
        if (!script.includes(stock)) fail(`Missing research infrastructure stock for runtime P${player}: ${unitType}`);
      }
      const researchLadder = researchLadderForSlot(slot, config.protoss_faction ?? "Standard");
      if (researchLadder) {
        for (const entry of researchLadder) {
          const call = `sc2team_TryResearchUpgrade(${player}, "${entry.structure}", "${entry.abil}", ${entry.index}, "${entry.upgrade}",`;
          if (!script.includes(call)) fail(`Missing research order for runtime P${player}: ${entry.upgrade}`);
        }
      }
    }
    for (const marker of [
      "sc2team_CountCompletedProduction",
      "sc2team_CountCompletedTownHalls",
      "sc2team_CountAllProduction",
      "sc2team_CountAllTownHalls",
      "PlayerGetPropertyInt",
      "productionReady",
      "AIBuild",
      // §94: 멜레 AI의 가스/일꾼 판단 누락을 직접 보완한다. 풍부한 가스
      // 건설, 기지별 일꾼 목표, 가스 3기·광물 2기 배정이 모두 있어야 한다.
      "sc2team_RunEconomyGuard",
      "sc2team_EconomyWorkerTarget",
      "sc2team_TryBuildEconomyGas",
      "sc2team_TryTrainEconomyWorkers",
      "AbilityCommand(\"TerranBuild\", 7)",
      "AbilityCommand(\"ProtossBuild\", 2)",
      "AbilityCommand(\"ZergBuild\", 2)",
      // §102: 가스 건설의 값싼 사전 게이트. 종전에는 45초 이후 매 턴 무조건
      // 전체 스캔을 완주했다(지을 것이 없어도).
      "sc2team_CountGasStructures",
      "gv_sc2team_NextGasAttempt",
      "gv_sc2team_GasScanBases",
      // §63: 연구 함수와 중복 방지·잔고 하한 마커.
      "sc2team_TryResearchUpgrade",
      "c_techCountQueuedOrBetter",
      "c_techCountCompleteOnly",
      "richBonus",
      "sc2team_TryBuildTerranAddon",
      "UnitOrderIsValid",
      "OrderTargetingPoint",
      // §97: 맵 전체 자원을 런타임에 반복 스캔하지 않고, 오프라인
      // 배치 표와 후보 주변 15 중복 검사만 사용한다.
      "sc2team_ExpansionCandidateOpen",
      "sc2team_ExpansionCandidateOwnedByPlayer",
      "sc2team_TryBuildExpansionAt",
      // §102: 후보 개폐는 후보마다 반경 스캔을 새로 만들지 않고, 탐색 한 번에
      // 타운홀을 한 번만 훑어 전부 미리 계산한다. nearestDistance <= 45.0이
      // 종전 RegionCircle(target, 45.0)과 동치인 항이다.
      "sc2team_RefreshExpansionClosed",
      "gv_sc2team_ExpansionClosed[nearestIndex] = true;",
      "nearestDistance <= 45.0",
      "RegionCircle(target, 8.0)",
      "UnitGetCustomValue(currentWorker, 22)",
      "sc2team_ReleaseEconomyHarvestWorkers(player, now)",
      "AbilityCommand(\"TerranBuild\", 0)",
      "AbilityCommand(\"ProtossBuild\", 0)",
      "AbilityCommand(\"ZergBuild\", 0)",
      // 후보 귀속(Voronoi)을 먼저 보고, 어디에도 귀속되지 않은 채 밀착한
      // 타운홀만 10.0으로 막는다. 14.0은 후보 34(시작 타운홀에서 13.15)를
      // 영구히 닫아 P12가 원거리 확장을 한 번도 못 하게 만들었다.
      "< 10.0",
      // §102: 스크립트가 제어한 경제 일꾼은 명단으로 추적한다. 종전에는
      // 해제 대상 몇 기를 찾으려고 매 턴 그 플레이어의 유닛 전부를 훑었다.
      "unitgroup[16] gv_sc2team_EconomyControlled;",
      "sc2team_TrackEconomyWorker",
      // §102: 생산자·구조물 그룹 캐시. 슬롯이 여러 개여야 한다 — 관문/차원관문
      // 교대와 연구 사다리(엔지니어링 베이/무기고/기술실)가 번갈아 요청한다.
      "sc2team_ProducerGroup",
      "unitgroup[4] gv_sc2team_ProducerCache;",
      // §103: 직접 건설 명령은 배치 유효성(UnitOrderIsValid)만으로 부족하다.
      // 그건 경로를 보지 않아서 절벽 위처럼 갈 수 없는 자리에도 명령이 나간다.
      "sc2team_BuilderCanReach",
      "AIPathingCostUnit(builder, target, true) >= 0",
      // §104: 궤도 사령부 에너지는 100 이상일 때만 쓴다(사용자 지시). 예비선이
      // 없으면 50이 모이는 즉시 우리가 가져가 밀레 AI가 스캐너 탐색·지게로봇을
      // 영영 쓰지 못한다. 우리 코드는 보조이지 주가 아니다.
      "c_unitPropEnergy, c_unitPropCurrent) >= 100.0",
      // 착공 전 확장 허가 창구를 짧게 끊고, 발주한 일꾼이 살아 있는 동안으로
      // 한정한다. 이게 없으면 밀리 AI가 그 허가로 본진 앞에 타운홀을 쌓는다.
      "gv_sc2team_ExpansionStartDeadline",
      "sc2team_ExpansionBuilderActive",
      // 확장 1단계(이동)와 2단계(도착 후 건설) 분리. 이동에는 테크트리 허가가
      // 필요 없으므로 걷는 동안 townHallCap을 닫아 두는 것이 핵심이다. 이게
      // 없으면 먼 확장일수록 허가 창구가 길어져 밀리 AI가 자기 기지 옆에
      // 먼저 타운홀을 지어 버린다.
      "sc2team_TryStageExpansionWorker",
      "sc2team_ExpansionBuilderAtTarget",
      "gv_sc2team_ExpansionStaging",
      'AbilityCommand("move", 0), target)',
      "DistanceBetweenPoints(",
      "gv_sc2team_ExpansionCursor",
      "gv_sc2team_ExpansionDeadline",
      "gv_sc2team_NextExpansionAttempt",
    ]) {
      if (!script.includes(marker)) fail(`Missing adaptive economy marker: ${marker}`);
    }
    // §102: 죽은 채로 남아 있던 재배정 경로를 아예 정의째 금지한다. 호출부는
    // 원래 0개였지만, 되살아나면 §89.6의 일꾼 뭉침·건설 취소가 재발하고
    // "자원 하나마다 일꾼 전체 스캔"이라는 2차식 순회가 매 턴 돌아온다.
    for (const deadHarvestPath of [
      "sc2team_EnforceEconomyHarvest",
      "sc2team_TryAssignEconomyWorker",
      "sc2team_CountWorkersOnResource",
    ]) {
      if (script.includes(deadHarvestPath)) {
        fail(`Economy guard must not reassign existing harvest workers: ${deadHarvestPath}`);
      }
    }
    // §102: 후보 개폐 판정은 배열 읽기여야 한다. 종전처럼 후보마다 UnitGroup을
    // 새로 만들면 확장 탐색 한 번에 44개가 한 프레임에 몰린다(§102 감사에서
    // 그 턴 총 92개 중 45개). 확장 쿨다운 45~120초 × 12슬롯이면 4~10초에 한 번
    // 터지므로, 사용자가 보고한 주기적 정지의 주기와 일치한다.
    const candidateOpenStart = script.indexOf("bool sc2team_ExpansionCandidateOpen");
    if (candidateOpenStart < 0) fail("Expansion candidate gate is missing");
    const candidateOpenBody = script.slice(
      candidateOpenStart,
      script.indexOf("\n}", candidateOpenStart)
    );
    if (candidateOpenBody.includes("UnitGroup(")) {
      fail(
        "sc2team_ExpansionCandidateOpen must read the precomputed closure array; " +
        "a per-candidate UnitGroup puts up to 44 scans in one frame"
      );
    }
    // §103: 좌표로 직접 건설/파견하는 모든 경로는 도달 가능성을 확인해야 한다.
    // 사용자 실관측: 파일런이 언덕 위에 발주돼 탐사정이 영영 가지 못했다.
    // UnitOrderIsValid는 "놓을 수 있는가"만 보고 "갈 수 있는가"는 보지 않는다.
    for (const reachGated of [
      "void sc2team_TryBuildPylonDirect",
      "bool sc2team_TryBuildExpansionAt",
      "bool sc2team_TryStageExpansionWorker",
    ]) {
      const fnStart = script.indexOf(reachGated);
      if (fnStart < 0) fail(`Direct build path is missing: ${reachGated}`);
      const fnBody = script.slice(fnStart, script.indexOf("\n}", fnStart));
      if (!fnBody.includes("sc2team_BuilderCanReach")) {
        fail(
          `${reachGated} must gate on sc2team_BuilderCanReach; placement validity ` +
          "alone lets a worker be ordered onto unreachable high ground"
        );
      }
    }
    // §105.8(감사 C2): 파일런 일꾼 피커는 자매 함수들과 같은 cv18/20/22 3종을
    // 모두 검사해야 한다. cv18만 보면 같은 틱에 확장 이동(cv20/22)이나 간헐천
    // 건설(cv20) 명령을 받은 탐사정을 덮어써 확장이 최대 195초 정지한다.
    {
      const pylonStart = script.indexOf("void sc2team_TryBuildPylonDirect");
      const pylonBody = script.slice(pylonStart, script.indexOf("\n}", pylonStart));
      for (const cvCheck of [
        "UnitGetCustomValue(builder, 18) > now",
        "UnitGetCustomValue(builder, 20) > now",
        "UnitGetCustomValue(builder, 22) > now",
      ]) {
        if (!pylonBody.includes(cvCheck)) {
          fail(`Pylon worker picker must skip claimed workers: missing ${cvCheck}`);
        }
      }
    }
    // §105.8(감사 C3): 가스 일꾼 피커의 fallback은 "채취 중"만 허용한다 —
    // 멜레 AI가 건설 보낸/짓고 있는 일꾼을 고르면 c_orderQueueReplace가
    // 진행 중 건설을 취소시켜 미완성 건물이 남는다. cv22도 함께 검사(확장
    // 스테이징 일꾼 보호).
    {
      const pickerStart = script.indexOf("unit sc2team_EconomyWorkerAt");
      if (pickerStart < 0) fail("Economy worker picker is missing");
      const pickerBody = script.slice(pickerStart, script.indexOf("\n}", pickerStart));
      for (const marker of [
        "UnitGetCustomValue(currentUnit, 22) > now",
        'UnitOrderHasAbil(currentUnit, "TerranBuild")',
        'UnitOrderHasAbil(currentUnit, "ProtossBuild")',
        'UnitOrderHasAbil(currentUnit, "ZergBuild")',
      ]) {
        if (!pickerBody.includes(marker)) {
          fail(`Gas worker picker must not steal building workers: missing ${marker}`);
        }
      }
    }
    // §102: 경제 일꾼 해제도 §97의 제어 해제와 같은 이유로 전수 조사를 금지한다.
    const economyReleaseStart = script.indexOf("void sc2team_ReleaseEconomyHarvestWorkers");
    if (economyReleaseStart < 0) fail("Economy harvest release is missing");
    const economyReleaseBody = script.slice(
      economyReleaseStart,
      script.indexOf("\n}", economyReleaseStart)
    );
    if (economyReleaseBody.includes("RegionEntireMap()")) {
      fail(
        "sc2team_ReleaseEconomyHarvestWorkers must walk gv_sc2team_EconomyControlled, " +
        "not every unit the player owns"
      );
    }
    for (const forbiddenNativePlacement of ["AISetStockExpand(", "AIExpand("]) {
      if (script.includes(forbiddenNativePlacement)) {
        fail(`Expansion must not delegate validated placement to melee AI: ${forbiddenNativePlacement}`);
      }
    }
    if (!script.includes("AISetUnitScriptControlled(builder, true)")) {
      fail("Validated expansion builder must remain script-controlled until its order ends");
    }
    const expansionOpenStart = script.indexOf("bool sc2team_ExpansionCandidateOpen");
    const expansionOpenBody = script.slice(
      expansionOpenStart,
      script.indexOf("\n}", expansionOpenStart),
    );
    if (expansionOpenStart < 0 || expansionOpenBody.includes("RegionEntireMap()")) {
      fail("Expansion duplicate check must remain local, not scan every player across the full map");
    }
    // §68: 병력 생산 동결(saveForExpansion)이 되살아나면 빌드 실패 —
    // "어떤 상황에서도 병력에 상한을 두지 않는다"(사용자 지시).
    if (script.includes("saveForExpansion")) {
      fail("saveForExpansion production freeze must stay removed");
    }
    // §63: 연구 프로브 플래그 없이 사람 슬롯에 연구 명령이 실리면 안 된다.
    // (옵저버 모드는 사람 슬롯이 AI이므로 연구 명령이 실리는 게 정상이다.)
    if (!config.research_probe && !config.observer_mode &&
        script.includes(`sc2team_TryResearchUpgrade(${humanRuntimeId},`)) {
      fail("Human research lines must not ship without research_probe");
    }
    verifyProductionScheduler(script, activeSlots);
  }
  if ((!config.strategy_bridge || config.bridge_probe) && !config.melee_only && script.includes("MeleeInitAI();")) {
    fail("Isolated controller map unexpectedly enables melee AI");
  }
  for (const assignment of assignments) {
    const player = players.find((item) => item.id === assignment.runtimeId);
    if (!player || player.startPoint !== assignment.startPoint) {
      fail(`Start mapping failed for runtime P${assignment.runtimeId}`);
    }
  }
  if (/PlayerModifyProperty(?:Int|Fixed)\([^\n]*c_playerPropSuppliesLimit/.test(script)) {
    fail("Supply ceiling must come from race data, not a runtime property mutation");
  }
  if (config.full_vision && !script.includes(`VisRevealArea(${humanRuntimeId},`)) {
    fail("Human full-vision setup is missing");
  }
  // §105: 유닛 제어 모듈은 opt-in(기본 off). 브리지 프로브 맵은 항상 포함.
  const unitControlActive =
    (config.bridge_probe || (config.strategy_bridge && config.unit_control === true)) &&
    !config.melee_only;
  if (unitControlActive && !script.includes("sc2team_InitializeCommandBridge();")) {
    fail("Command bridge is missing");
  }
  if (!unitControlActive) {
    // §105 역방향 가드: off 맵에 브리지 심볼이 하나라도 남으면 실패.
    // 주의: `AISetUnitScriptControlled(currentUnit, false)`는 확장·파일런
    // 빌더 해제(production.cjs)에도 있는 문자열이라 여기 못 쓴다 — 브리지
    // 전용 식별자만 나열한다(§93 wild_zerg off 가드와 같은 원리).
    for (const forbidden of [
      "sc2team_InitializeCommandBridge",
      "gv_sc2team_CommandBeacon",
      "sc2team_IssueSupport",
      "sc2team_ControlForSeconds",
      "sc2team_ControlRelease_Func",
      "sc2team_DefendHome",
      "sc2team_HoldMission",
      "sc2team_Maintenance_Func",
      "gv_sc2team_ControlledUnits",
    ]) {
      if (script.includes(forbidden)) {
        fail(`Unit-control symbol must not ship with unit_control off: ${forbidden}`);
      }
    }
  }
  if (unitControlActive) {
    for (const marker of [
      "sc2team_IssueSupport",
      "sc2team_ControlRelease_Func",
      "supportPlayer = FixedToInt",
      "AISetUnitScriptControlled(currentUnit, false)",
      // §70: 임무 보류(수비·지원 보호)와 자체 수비 마커.
      "sc2team_HoldMission",
      "sc2team_MissionHeld",
      "sc2team_PlayerTeam",
      "sc2team_DefendHome",
      "sc2team_HomeDefense_Func",
    ]) {
      if (!script.includes(marker)) fail(`Ally-support bridge marker is missing: ${marker}`);
    }
    // §70: 사람 슬롯 병력은 수비 트리거가 절대 지휘하지 않는다.
    if (script.includes(`sc2team_DefendHome(${humanRuntimeId});`)) {
      fail("Home defense must not command the human slot");
    }
    // §99: 제어 해제와 본진 방어는 플레이어 라운드로빈이며, 하나의 4단계
    // 스케줄러에서 서로 다른 프레임에 실행한다.
    for (const marker of [
      "unitgroup[16] gv_sc2team_ControlledUnits;",
      "int gv_sc2team_ControlReleaseCursor;",
      "int gv_sc2team_HomeDefenseCursor;",
      "int gv_sc2team_MaintenancePhase;",
      "gv_sc2team_ControlledUnits[controlledPlayer]",
      "gv_sc2team_ControlledUnits[player]",
      "sc2team_MaintenancePlayer",
      "sc2team_Maintenance_Func",
      "gv_sc2team_MaintenancePhase == 1 || gv_sc2team_MaintenancePhase == 3",
      "gv_sc2team_MaintenancePhase == 2",
    ]) {
      if (!script.includes(marker)) fail(`Script-control roster marker is missing: ${marker}`);
    }
    if (script.includes('TriggerCreate("sc2team_ControlRelease_Func")') ||
        script.includes('TriggerCreate("sc2team_HomeDefense_Func")')) {
      fail("Release and home-defense jobs must not use independent periodic triggers");
    }
    const maintenancePeriod = /TriggerAddEventTimePeriodic\(gt_sc2team_Maintenance, ([\d.]+), c_timeGame\)/
      .exec(script);
    if (!maintenancePeriod) fail("Missing interleaved maintenance scheduler");
    const maintenancePlayers = activeSlots.filter((_, index) => index + 1 !== humanRuntimeId).length;
    const expectedMaintenancePeriod = 10.0 / (Math.max(1, maintenancePlayers) * 4.0);
    if (Math.abs(parseFloat(maintenancePeriod[1]) - expectedMaintenancePeriod) > 0.001) {
      fail(
        `Maintenance period must preserve 5s release / 10s defense cycles ` +
        `(got ${maintenancePeriod[1]}, expected ${expectedMaintenancePeriod.toFixed(3)})`
      );
    }
    // §105.5(A1): opcode 10/11의 통제 시간은 파이썬 재출격 주기보다 엄격히
    // 작아야 한다. 종전 버그는 코드가 틀린 게 아니라 독립인 두 상수(45/45)가
    // 조용히 같아진 것이었다 — 그 불변식을 기계로 고정한다. 통제 시간이
    // 주기 이상이면 만료 전에 다음 출격이 통제를 갱신해 병력이 밀레 AI에게
    // 영원히 돌아가지 않는다(§70.1 실측).
    const bridgeFuncStart = script.indexOf("bool sc2team_CommandBridge_Func");
    const bridgeFuncBody = script.slice(
      bridgeFuncStart,
      script.indexOf("\n}", bridgeFuncStart)
    );
    const attackControlDurations = [
      ...bridgeFuncBody.matchAll(/sc2team_ControlForSeconds\(currentUnit, ([\d.]+)\)/g),
    ].map((match) => parseFloat(match[1]));
    if (attackControlDurations.length !== 2) {
      fail(
        `Expected exactly two attack-broadcast control stamps (opcode 10/11), found ${attackControlDurations.length}`
      );
    }
    const pythonController = fs.readFileSync(
      path.join(PROJECT_ROOT, "sc2team", "strategy_controller.py"),
      "utf8"
    );
    const cooldownMatch = /attack_cooldown_seconds:\s*float\s*=\s*([\d.]+)/.exec(pythonController);
    if (!cooldownMatch) fail("Cannot find attack_cooldown_seconds in strategy_controller.py");
    const pythonAttackCooldown = parseFloat(cooldownMatch[1]);
    for (const duration of attackControlDurations) {
      if (!(duration < pythonAttackCooldown)) {
        fail(
          `Attack-broadcast control time (${duration}s) must be strictly less than the ` +
          `Python attack cooldown (${pythonAttackCooldown}s), or units never return to the melee AI`
        );
      }
    }
    // §105.5(A2): 라바는 병력 판정에서 제외 — 세 채널 전부가 라바에 통제
    // 도장을 찍고 homeCount를 부풀리는 것을 막는다.
    const groundArmyStart = script.indexOf("bool sc2team_IsGroundArmyUnit");
    const groundArmyBody = script.slice(
      groundArmyStart,
      script.indexOf("\n}", groundArmyStart)
    );
    if (!groundArmyBody.includes('UnitGetType(candidate) == "Larva"')) {
      fail("sc2team_IsGroundArmyUnit must exclude Larva (a production resource, not army)");
    }
    // §105.5(A3): 전군 회군은 타운홀 피해 게이트 + 이미 통제 중 + 임무 없음
    // 조건을 모두 갖춰야 한다(homeCount == 0 무조건 참 문제의 봉인).
    const defendStart = script.indexOf("void sc2team_DefendHome");
    const defendBody = script.slice(defendStart, script.indexOf("\n}", defendStart));
    if (!/devastating = threatCount >= \(homeCount \* 2\) &&\s*\n\s*UnitGetPropertyFixed\(hallUnit, c_unitPropLife, c_unitPropCurrent\) </.test(defendBody)) {
      fail("Devastating retreat must require actual town-hall damage");
    }
    if (!defendBody.includes("devastating && AIIsScriptControlled(currentUnit)")) {
      fail("Devastating retreat must only recall units already under script control");
    }
    // §105.5(A4): 지원 파견은 본진 방어 중(cv30) 병력을 차출하지 않는다 —
    // 카운트와 발주 두 루프 모두.
    const supportStart = script.indexOf("void sc2team_IssueSupport");
    const supportBody = script.slice(supportStart, script.indexOf("\n}", supportStart));
    const supportHeldGuards = supportBody.split("!sc2team_MissionHeld(currentUnit)").length - 1;
    if (supportHeldGuards !== 2) {
      fail(
        `sc2team_IssueSupport must skip mission-held units in both loops (found ${supportHeldGuards}/2 guards)`
      );
    }
    // 가드는 이 함수 본문에만 건다. P15 야생 저그 컨트롤러에도 광역 질의가
    // 두 곳 있지만("맵에서 가장 가까운 빈 광물/적 타운홀 찾기") 그건 광역
    // 탐색이 본질이고 쿨다운으로 제한된다. 5초마다 무조건 도는 것은 여기뿐이다.
    const releaseStart = script.indexOf("bool sc2team_ControlRelease_Func");
    const releaseBody = script.slice(
      releaseStart,
      script.indexOf("\n}", releaseStart)
    );
    if (releaseBody.includes("RegionEntireMap()")) {
      fail(
        "sc2team_ControlRelease_Func must not scan the map; it fires every 5 game " +
        "seconds and a full c_playerAny sweep walks thousands of units late game"
      );
    }
  }
  // §70: 수비 트리거는 실게임 브리지에서만 등록된다(프로브 계측 오염 방지).
  // §105: 유닛 제어 off 맵에는 브리지 자체가 없으므로 수비도 없어야 한다.
  const defenseInitMarker = "gv_sc2team_MaintenancePhase == 2 && true";
  if (config.strategy_bridge && config.unit_control === true && !config.bridge_probe && !config.melee_only) {
    if (!script.includes(defenseInitMarker)) fail("Home defense trigger is missing");
  } else if (script.includes(defenseInitMarker)) {
    fail("Home defense must not run in probe or bridgeless maps");
  }
  if (config.melee_only) {
    for (const forbidden of [
      "sc2team_InitializeCommandBridge();",
      "sc2team_InitializeProductionRules();",
      "sc2team_InitializeHostileWildAI();",
    ]) {
      if (script.includes(forbidden)) {
        fail(`melee_only map contains custom runtime work: ${forbidden}`);
      }
    }
    if (wildZergActive) {
      for (const marker of [
        "sc2team_InitializeV3WildDelay();",
        "AISetUserInt(15, 145, 0);",
        "AISetUserInt(15, 145, 1);",
        "AISetUserInt(15, 142, 301);",
        "AISetSpecificState(15, 1, 1);",
        "AISetSpecificState(15, 2, 1);",
        "AISetSpecificState(15, 3, 1);",
        "AIGetTime() < 420.0",
        "AISetUnitScriptControlled(currentUnit, true);",
        "AISetUnitScriptControlled(currentUnit, false);",
        "TriggerAddEventTimePeriodic(gt_sc2team_V3WildRelease, 2.0, c_timeGame);",
        "TriggerEnable(gt_sc2team_V3WildRelease, false);",
      ]) {
        if (!script.includes(marker)) fail(`V3 P15 delayed-AI marker is missing: ${marker}`);
      }
      for (const forbidden of [
        "sc2team_InitializeHostileWildIdle();",
        "sc2team_InitializeV3WildTruce();",
      ]) {
        if (script.includes(forbidden)) {
          fail(`V3 P15 delayed AI changes player relations or runs the old controller: ${forbidden}`);
        }
      }
      if (script.includes("AISetSpecificState(15, 1, -1)")) {
        fail("V3 P15 delayed AI must not use the invalid Disabled main state");
      }
      const delayFunction = /void sc2team_InitializeV3WildDelay \(\) \{([^}]*)\}/s.exec(script);
      const releaseFunction = /bool sc2team_V3WildRelease_Func \([^)]*\) \{([\s\S]*?)\n\}/.exec(script);
      const controlFunction = /void sc2team_V3SetWildCombatControl \([^)]*\) \{([\s\S]*?)\n\}/.exec(script);
      for (const [name, body] of [
        ["initialize", delayFunction && delayFunction[1]],
        ["release", releaseFunction && releaseFunction[1]],
        ["combat-control", controlFunction && controlFunction[1]],
      ]) {
        if (!body) fail(`V3 P15 delayed-AI ${name} function is missing`);
        if (/SetAlliance|PlayerSetController|UnitSetOwner/.test(body)) {
          fail(`V3 P15 delayed-AI ${name} function changes players, alliances, or ownership`);
        }
      }
      const withoutAllowedWildTimers = script
        .replace(
          "TriggerAddEventTimePeriodic(gt_sc2team_V3WildRelease, 2.0, c_timeGame);",
          ""
        );
      if (withoutAllowedWildTimers.includes("TriggerAddEventTimePeriodic(gt_sc2team_")) {
        fail("melee_only map contains an unexpected custom periodic trigger");
      }
    }
    else {
      for (const forbidden of [
        "sc2team_InitializeHostileWildIdle();",
        "sc2team_InitializeV3WildTruce();",
        "sc2team_InitializeV3WildDelay();",
        "TriggerAddEventTimePeriodic(gt_sc2team_",
      ]) {
        if (script.includes(forbidden)) {
          fail(`melee_only map with Wild Zerg disabled contains: ${forbidden}`);
        }
      }
    }
  }
}

// 파이썬 전략 제어기의 출격 문턱(목표재고 달성률)이 쓰는 사이드카 내용을 만든다.
// perExpansion은 경제 규칙과 같은 공식(max(1, ceil(count*0.6)))을 미리 계산해 싣고,
// Random 종족은 Galaxy가 재고를 확장 비례 없이 걸므로 0으로 미러한다.

module.exports = {
  verify,
};
