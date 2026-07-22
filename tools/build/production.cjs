// 생산 규칙 Galaxy 생성: 슬롯별 목표 재고(AISetStock), 유닛 생산 상한,
// 캠페인 유닛 구매, 업그레이드 연구 사다리, 테란 애드온 발주.
//
// 불변식 요약(자세한 근거는 HANDOFF):
// - 병력 재고 목표는 절대 상한을 두지 않는다(비율표 x STOCK_SQUEEZE_MULTIPLIER).
// - 캠페인 구매는 은행 하한선(광물 +500 / 가스 +400)과 틱당 1기를 지킨다.
// - 요구조건 미충족 AIBuild는 무동작이 아니라 빌드 관리자를 영구 정지시킨다(§83).

const { fail } = require("./util.cjs");
const EXPANSION_LAYOUT = require("./expansion-layout.json");
const {
  researchLadderForSlot,
  COMBAT_AIR_BY_RACE,
  SUPPORT_AIR_BY_RACE,
  supportAirCap,
  GROUND_COMBAT_BY_RACE,
  PREFERRED_STOCK_BY_BUILD,
  STOCK_SQUEEZE_MULTIPLIER,
  PREFERRED_UPGRADES_BY_BUILD,
  RESEARCH_INFRA_BY_RACE,
  CAMPAIGN_PURCHASE_BY_UNIT,
  PREFERRED_INFRA_BY_BUILD,
  RANDOM_INFRA_BY_RACE,
  RANDOM_TRAIN_BY_RACE,
  REBUILD_PREREQUISITE,
  SAFE_OPENING_AIBUILD,
  FORCED_INFRASTRUCTURE_BY_BUILD,
  SCALING_PRODUCTION_BY_BUILD,
  SCALING_PRODUCTION_PREREQUISITE,
  RANDOM_SCALING_PRODUCTION_BY_RACE,
  FIXED_STRUCTURE_CAPS_BY_BUILD,
  EXPANSION_GATE_INFRA_BY_BUILD,
  EXPANSION_TOWN_HALL_BY_RACE,
  ALLOWED_GROUND_BY_BUILD,
  DIRECT_TRAIN_BY_UNIT,
} = require("./tables.cjs");

function makeResearchLines(player, ladder, indent) {
  const lines = [`${indent}researched = false;`];
  for (const entry of ladder) {
    const prereq = entry.prereqUpgrade ? `"${entry.prereqUpgrade}"` : '""';
    const prereqStruct = entry.prereqStructure ? `"${entry.prereqStructure}"` : '""';
    lines.push(
      `${indent}if (!researched) { researched = sc2team_TryResearchUpgrade(${player}, "${entry.structure}", "${entry.abil}", ${entry.index}, "${entry.upgrade}", ${prereq}, ${prereqStruct}, ${entry.minerals}, ${entry.gas}); }`,
    );
  }
  return lines;
}

// §82: Terran addons are attached structures, so AIBuild cannot create them
// and AISetStock may be ignored forever.  Ask an idle, placement-valid producer
// to attach the addon with its real ability.  One order per player/tick keeps
// the normal melee economy and build queue in charge.
function makeTerranAddonLines(player, build, allowSupportAir) {
  const lines = ["    addonOrdered = false;"];
  const request = (producer, addon, ability, commandIndex, targetLines) => {
    lines.push(
      "    if (!addonOrdered) {",
      ...targetLines.map((line) => `        ${line}`),
      `        addonOrdered = sc2team_TryBuildTerranAddon(${player}, "${producer}", "${addon}", "${ability}", ${commandIndex}, addonTarget);`,
      "    }",
    );
  };
  // §87: random_ground 테란도 포함 — 기본 훈련 세트(불곰/탱크/토르)가 기술실
  // 없이는 전부 조용한 무동작이 된다(§82 애드온 직접 발주가 유일 경로).
  const bioBuild = build === "bio" || build === "bio_tank" || build === "random_ground";
  const factoryBuild = ["bio_tank", "hellion_tank", "thor_tank", "mech_macro", "random_ground"].includes(build);

  // Bio needs at least one Tech Lab for Marauders/Medics and uses its remaining
  // Barracks slots for reactors.  The target is derived from real completed
  // buildings, so later normal-melee Barracks additions receive addons too.
  if (bioBuild) {
    request("Barracks", "BarracksTechLab", "BarracksAddOns", 0, [
      `addonTarget = sc2team_CountCompletedProduction(${player}, "Barracks");`,
      "if (addonTarget > 1) { addonTarget = 1; }",
    ]);
    request("Barracks", "BarracksReactor", "BarracksAddOns", 1, [
      `addonTarget = sc2team_CountCompletedProduction(${player}, "Barracks") - sc2team_CountAllProduction(${player}, "BarracksTechLab");`,
      "if (addonTarget < 0) { addonTarget = 0; }",
    ]);
  }
  // Every Factory in the tank/mech plans is eligible for a Tech Lab.  This
  // removes the known empty-Factory bottleneck without touching a busy queue.
  if (factoryBuild) {
    request("Factory", "FactoryTechLab", "FactoryAddOns", 0, [
      `addonTarget = sc2team_CountCompletedProduction(${player}, "Factory");`,
    ]);
  }
  // Ravens require a Starport Tech Lab.  Only request one when support air is
  // enabled; transport/detection remains otherwise governed by the normal AI.
  if (allowSupportAir) {
    request("Starport", "StarportTechLab", "StarportAddOns", 0, [
      `addonTarget = sc2team_CountCompletedProduction(${player}, "Starport");`,
      "if (addonTarget > 1) { addonTarget = 1; }",
    ]);
  }
  return lines;
}

// §87: 직접 훈련 디스패처 코드젠. 생산자 클래스(그룹)별로 보유/목표 비율이
// 가장 낮은 병종이 먼저 은행을 쓰고(1패스), 나머지 병종이 남은 생산 능력을
// 채운다(2패스 — 대기열·잔고·유효성 검사에 걸리면 자연히 무동작). 1패스가
// 이미 발주한 병종은 2패스에서 대기열 상한(maxQueue)에 걸려 이중 발주가 없다.
function makeTrainDispatchLines(player, build, meleeEntries) {
  const lines = [];
  const groups = new Map();
  for (const entry of meleeEntries) {
    // campaign_units_pilot=false면 캠페인 유닛이 구매 대신 여기로 흘러온다.
    // 그때 맵에는 그 유닛 자체가 없으므로 디스패처가 다룰 수 없다 — 건너뛴다.
    if (CAMPAIGN_PURCHASE_BY_UNIT[entry.unitType] !== undefined) continue;
    const train = DIRECT_TRAIN_BY_UNIT[entry.unitType];
    // 표 밖의 멜레 병종은 조용한 구멍이 된다(그 병종만 디스패처 없이 남음).
    if (train === undefined) fail(`Missing direct-train entry for ${entry.unitType}`);
    if (!groups.has(train.group)) groups.set(train.group, []);
    groups.get(train.group).push({ ...entry, train });
  }
  // §87: random_ground 테란도 포함 — 기본 훈련 세트(불곰/탱크/토르)가 기술실
  // 없이는 전부 조용한 무동작이 된다(§82 애드온 직접 발주가 유일 경로).
  const bioBuild = build === "bio" || build === "bio_tank" || build === "random_ground";
  const factoryBuild = ["bio_tank", "hellion_tank", "thor_tank", "mech_macro", "random_ground"].includes(build);
  const callFor = (candidate, indent) => {
    const t = candidate.train;
    const emitted = [];
    if (t.morphFrom) {
      emitted.push(
        `${indent}sc2team_TryMorphMeleeUnit(${player}, "${t.morphFrom}", "${t.abil}", ${t.index}, ${t.minerals}, ${t.gas}, 4);`
      );
      return emitted;
    }
    // §82 애드온 발주는 유휴 생산 건물이 필요하다. 훈련이 모든 건물을 점유하면
    // 애드온이 영구히 굶으므로, 애드온을 달 수 있는 건물 1개를 틱마다 남긴다.
    let reserveAbil = "";
    if (t.producer === "Barracks" && bioBuild) reserveAbil = "BarracksAddOns";
    if (t.producer === "Factory" && factoryBuild) reserveAbil = "FactoryAddOns";
    const leaveIdle = t.producer === "Larva" ? 3 : 0;
    const maxQueue = t.producer === "Larva" ? 1 : 2;
    emitted.push(
      `${indent}sc2team_TryTrainMeleeUnit(${player}, "${t.producer}", "${t.abil}", ${t.index}, ${t.minerals}, ${t.gas}, "${reserveAbil}", ${leaveIdle}, ${maxQueue});`
    );
    if (t.warpAbil) {
      emitted.push(
        `${indent}sc2team_TryWarpTrain(${player}, "${t.warpAbil}", ${t.warpIndex}, ${t.minerals}, ${t.gas});`
      );
    }
    return emitted;
  };
  const countExpr = (candidate) => {
    const types = [candidate.unitType, ...(candidate.train.aliases ?? [])];
    return types
      .map((unitType) => `sc2team_CountUnits(${player}, "${unitType}")`)
      .join(" + ");
  };
  for (const candidates of groups.values()) {
    lines.push("    trainBestRatio = 2.0;", "    trainPick = 0;");
    candidates.forEach((candidate, i) => {
      lines.push(
        `    desired = ${candidate.count * STOCK_SQUEEZE_MULTIPLIER};`,
        `    trainCurrent = ${countExpr(candidate)};`,
        "    if (IntToFixed(trainCurrent) / IntToFixed(desired) < trainBestRatio) {",
        "        trainBestRatio = IntToFixed(trainCurrent) / IntToFixed(desired);",
        `        trainPick = ${i + 1};`,
        "    }",
      );
    });
    candidates.forEach((candidate, i) => {
      lines.push(
        `    ${i === 0 ? "if" : "else if"} (trainPick == ${i + 1}) {`,
        ...callFor(candidate, "        "),
        "    }",
      );
    });
    // 2패스: 1패스가 고르지 않은 병종으로 남은 생산 능력을 채운다(예: 기술실
    // 공장은 탱크, 무부속 공장은 화염차).
    //
    // §102: 종전에는 1패스가 이미 처리한 병종까지 무조건 한 번 더 불렀다.
    // 그 두 번째 호출은 모든 생산 건물이 이미 대기열 상한이거나 은행이 이미
    // 하한이라 항상 무동작인데, 생산 건물 전체 스캔만 한 번 더 만들었다.
    // 구매 쪽이 쓰는 purchasePick 가드와 같은 형태로 건너뛴다.
    candidates.forEach((candidate, i) => {
      lines.push(
        `    if (trainPick != ${i + 1}) {`,
        ...callFor(candidate, "        "),
        "    }",
      );
    });
  }
  return lines;
}

function makeProductionRules(activeSlots, allowSupportAir, campaignUnitsPilot, researchProbe, protossFaction = "Standard") {
  const capLines = [];
  // §95: 플레이어별로 코드를 분리해 담는다. 종전에는 하나의 평평한 배열이라
  // 12명 전원의 경제·생산 로직이 한 트리거 호출에 전부 들어갔다(라운드로빈
  // 스케줄러와 집계 캐시가 이 분리를 전제로 한다).
  const playerBlocks = [];
  // AIBuild is only safe here as a *rebuild* order.  When issued before the
  // normal melee plan has made a structure once, an unmet prerequisite can
  // stall that player's build manager permanently.  Keep a per-player latch
  // for every managed infrastructure type; the normal AI/AISetStock owns the
  // opening, and this controller owns only recovery after it has succeeded.
  const rebuildInfraTypes = new Map();
  for (const slot of activeSlots) {
    if (!slot || slot.controller !== "custom_ai" || slot.race === "Random") continue;
    const baseInfrastructure = slot.build === "random_ground"
      ? (RANDOM_INFRA_BY_RACE[slot.race] ?? {})
      : PREFERRED_INFRA_BY_BUILD[slot.build];
    for (const unitType of Object.keys(baseInfrastructure ?? {})) {
      if (!rebuildInfraTypes.has(unitType)) rebuildInfraTypes.set(unitType, rebuildInfraTypes.size);
    }
    for (const unitType of Object.keys(RESEARCH_INFRA_BY_RACE[slot.race] ?? {})) {
      if (!rebuildInfraTypes.has(unitType)) rebuildInfraTypes.set(unitType, rebuildInfraTypes.size);
    }
  }
  const completedAny = (player, types) => {
    const alternatives = Array.isArray(types) ? types : [types];
    return `(${alternatives.map(
      (unitType) => `sc2team_CountCompletedProduction(${player}, "${unitType}") >= 1`
    ).join(" || ")})`;
  };
  for (let index = 0; index < activeSlots.length; index += 1) {
    const slot = activeSlots[index];
    if (slot.controller !== "custom_ai") continue;
    const player = index + 1;
    const stockLines = [];
    const economyLines = [];
    const campaignPurchaseLines = [];
    const races = slot.race === "Random" ? ["Terran", "Protoss", "Zerg"] : [slot.race];
    for (const race of races) {
      for (const unitType of COMBAT_AIR_BY_RACE[race]) {
        capLines.push(
          `    TechTreeSetProduceCap(${player}, "${unitType}", c_techCatUnit, 0);`
        );
      }
      for (const unitType of SUPPORT_AIR_BY_RACE[race]) {
        const cap = supportAirCap(slot.build, unitType, allowSupportAir);
        capLines.push(
          `    TechTreeSetProduceCap(${player}, "${unitType}", c_techCatUnit, ${cap});`
        );
      }
    }
    const preferred = PREFERRED_STOCK_BY_BUILD[slot.build];
    if (preferred === undefined) fail(`Unknown ground build for P${slot.slot}: ${slot.build}`);
    const preferredUpgrades = PREFERRED_UPGRADES_BY_BUILD[slot.build];
    if (preferredUpgrades === undefined) fail(`Missing upgrade plan for P${slot.slot}: ${slot.build}`);
    for (const upgradeType of preferredUpgrades) {
      stockLines.push(`    AISetStock(${player}, 1, "${upgradeType}");`);
    }
    const fixedCaps = FIXED_STRUCTURE_CAPS_BY_BUILD[slot.build];
    if (fixedCaps === undefined) fail(`Missing fixed production caps for P${slot.slot}: ${slot.build}`);
    for (const [unitType, count] of Object.entries(fixedCaps)) {
      capLines.push(
        `    TechTreeSetProduceCap(${player}, "${unitType}", c_techCatUnit, ${count});`
      );
    }
    const allowedGround = ALLOWED_GROUND_BY_BUILD[slot.build];
    if (allowedGround === undefined) fail(`Missing ground allow-list for P${slot.slot}: ${slot.build}`);
    if (allowedGround !== null && slot.race !== "Random") {
      for (const unitType of GROUND_COMBAT_BY_RACE[slot.race]) {
        if (!allowedGround.includes(unitType)) {
          capLines.push(
            `    TechTreeSetProduceCap(${player}, "${unitType}", c_techCatUnit, 0);`
          );
        }
      }
    }
    const baseInfrastructure = slot.build === "random_ground" && slot.race !== "Random"
      ? (RANDOM_INFRA_BY_RACE[slot.race] ?? {})
      : PREFERRED_INFRA_BY_BUILD[slot.build];
    if (baseInfrastructure === undefined) fail(`Missing infrastructure plan for P${slot.slot}: ${slot.build}`);
    // §63: 연구 구조물(포지/트와일라잇/진화장)이 빌드 인프라에 없으면 재고로
    // 보강한다. 이미 있는 항목은 빌드 쪽 수를 존중한다.
    const infrastructure = { ...baseInfrastructure };
    for (const [unitType, count] of Object.entries(RESEARCH_INFRA_BY_RACE[slot.race] ?? {})) {
      if (!(unitType in infrastructure)) infrastructure[unitType] = count;
    }
    for (const [unitType, count] of Object.entries(infrastructure)) {
      capLines.push(
        `    TechTreeSetProduceCap(${player}, "${unitType}", c_techCatUnit, ${count});`
      );
      stockLines.push(
        `    AISetStock(${player}, ${count}, "${unitType}");`
      );
    }
    const forcedInfrastructure = FORCED_INFRASTRUCTURE_BY_BUILD[slot.build] ?? [];
    const scalingPlan = slot.build === "random_ground" && slot.race !== "Random"
      ? RANDOM_SCALING_PRODUCTION_BY_RACE[slot.race]
      : SCALING_PRODUCTION_BY_BUILD[slot.build];
    if (scalingPlan === undefined) fail(`Missing scaling production plan for P${slot.slot}: ${slot.build}`);
    if (slot.race === "Random") {
      for (const [unitType, count] of Object.entries(preferred)) {
        stockLines.push(
          `    AISetStock(${player}, ${count * STOCK_SQUEEZE_MULTIPLIER}, "${unitType}");`
        );
      }
      economyLines.push(`    sc2team_RunEconomyGuard(${player});`);
      playerBlocks.push({ player, slot, stockLines, economyLines });
      continue;
    }
    const expansionGate = EXPANSION_GATE_INFRA_BY_BUILD[slot.build];
    if (expansionGate === undefined) fail(`Missing expansion gate for P${slot.slot}: ${slot.build}`);
    economyLines.push(
      `    bases = sc2team_CountCompletedTownHalls(${player}, "${slot.race}");`,
      "    if (bases < 1) { bases = 1; }",
      `    townHallTypeCount = sc2team_CountAllProduction(${player}, "${EXPANSION_TOWN_HALL_BY_RACE[slot.race]}");`,
      "    productionReady = true;",
      // §94: 모든 자원기지의 가스/일꾼/채취를 직접 보장한다.
      `    sc2team_RunEconomyGuard(${player});`,
      `    workerCount = sc2team_CountUnits(${player}, "SCV") + sc2team_CountUnits(${player}, "Probe") + sc2team_CountUnits(${player}, "Drone");`,
      `    workersShort = workerCount < sc2team_EconomyWorkerTarget(${player});`,
      // 일꾼 목표는 생산 보정에만 쓴다. 확장을 여기서 막으면 2기지에서
      // 32명(기지당 16명)을 채우기 전까지 다음 멀티 절차가 매 틱 취소된다.
    );
    // Mark successful normal-plan construction before any recovery order is
    // considered.  The latches intentionally never clear when a structure is
    // destroyed, so a later missing structure is eligible for AIBuild.
    for (const unitType of Object.keys(infrastructure)) {
      const infraIndex = rebuildInfraTypes.get(unitType);
      economyLines.push(
        `    if (sc2team_CountCompletedProduction(${player}, "${unitType}") >= 1) { gv_sc2team_InfraSeen[${player}][${infraIndex}] = true; }`,
      );
    }
    for (const request of forcedInfrastructure) {
      economyLines.push(
        `    currentCount = sc2team_CountAllProduction(${player}, "${request.unitType}");`,
        // Forced infrastructure is deliberately different from a rebuild:
        // the normal melee plan can skip it forever.  Its explicit completed
        // prerequisite makes the first AIBuild safe, so do not wait for an
        // impossible "seen once" latch before issuing it.
        `    if (currentCount < ${request.count} && ${completedAny(player, request.prerequisite)}) {`,
        `        AIBuild(${player}, c_makePriorityTown, AIGetMainTown(${player}), "${request.unitType}", 1, c_nearChokePoint);`,
        "    }",
      );
    }
    // §71: 테크 건물 재건. AISetStock 재고 요청만으로는 복불복이다 — 멜레
    // AI가 구조물 재고 요청을 무기한 무시하는 전례가 이미 있다(울트라리스크
    // 굴, FORCED_INFRASTRUCTURE 주석). 같은 게임에서 P3는 아머리를 재건하고
    // P4는 방치한 실관측이 그 비결정성의 증거다. 파괴로 수가 모자라면 매 틱
    // AIBuild로 직접 발주한다(건설 시작 즉시 CountAllProduction에 잡혀 중복
    // 발주는 없다).
    const forcedTypes = new Set(forcedInfrastructure.map((request) => request.unitType));
    for (const [unitType, count] of Object.entries(infrastructure)) {
      if (forcedTypes.has(unitType)) continue;
      const rebuildGate = REBUILD_PREREQUISITE[unitType];
      // §105.8(감사 B2·B4): 전제 게이트 없는 재건 발주는 빌드 자체를 실패시킨다.
      // §83.2가 선언한 "전 항목이 게이트를 갖는다"의 빌드타임 강제 — 종전에는
      // 표에서 빠진 항목이 무게이트 분기로 조용히 떨어졌다(Factory가 실례).
      if (rebuildGate === undefined) {
        fail(`재건 전제 게이트 없음: ${unitType} — REBUILD_PREREQUISITE에 추가할 것 (§83)`);
      }
      const infraIndex = rebuildInfraTypes.get(unitType);
      const openingSafe = SAFE_OPENING_AIBUILD.has(unitType);
      economyLines.push(
        `    currentCount = sc2team_CountAllProduction(${player}, "${unitType}");`,
        `    if ((${openingSafe ? "true" : `gv_sc2team_InfraSeen[${player}][${infraIndex}]`}) && currentCount < ${count} && ${completedAny(player, rebuildGate)}) {`,
        `        AIBuild(${player}, c_makePriorityTown, AIGetMainTown(${player}), "${unitType}", 1, c_nearChokePoint);`,
        "    }",
      );
    }
    if (Object.keys(scalingPlan).length > 0) {
      // §68: 은행이 쌓일수록(2500당 1개, 최대 +8) 생산 건물 목표를 올려 돈이
      // 생산 능력으로 흐르게 한다. 확장 준비 판정(productionReady)은 부유
      // 보너스를 뺀 기본 목표로만 따져 확장 시도를 막지 않는다.
      economyLines.push(
        `    richBonus = PlayerGetPropertyInt(${player}, c_playerPropMinerals) / 2500;`,
        "    if (richBonus > 8) { richBonus = 8; }",
      );
    }
    for (const [unitType, scale] of Object.entries(scalingPlan)) {
      const prerequisite = SCALING_PRODUCTION_PREREQUISITE[unitType];
      if (prerequisite === undefined) fail(`Missing build prerequisite for ${unitType}`);
      // §62: 팩토리는 상한 없음(사용자 지시). 나머지 스케일 구조물은 종전대로
      // 목표 수를 상한으로 유지한다.
      const capValue = unitType === "Factory" ? "-1" : "desired";
      economyLines.push(
        `    desired = ${scale.base} + ((bases - 1) * ${scale.perExpansion}) + richBonus;`,
        `    TechTreeSetProduceCap(${player}, "${unitType}", c_techCatUnit, ${capValue});`,
        `    AISetStock(${player}, desired + 1, "${unitType}");`,
        `    AISetStockUnitNext(${player}, desired + 1, "${unitType}", true);`,
        `    currentCount = sc2team_CountAllProduction(${player}, "${unitType}");`,
        `    if (currentCount < desired && sc2team_CountCompletedProduction(${player}, "${prerequisite}") >= 1) {`,
        `        AIBuild(${player}, c_makePriorityTown, AIGetMainTown(${player}), "${unitType}", 1, c_nearChokePoint);`,
        "    }",
        `    if (sc2team_CountCompletedProduction(${player}, "${unitType}") < desired - richBonus) { productionReady = false; }`,
      );
      if (unitType === "Factory") {
        // §62: AI가 기술실을 5~7개 중 3개에만 달아 멜레 메카닉 처리량이
        // 막히는 것이 실측됐다(§61). 팩토리 수만큼 기술실을 재고로 요청한다.
        economyLines.push(
          `    AISetStock(${player}, desired, "FactoryTechLab");`,
        );
      }
    }
    for (const [unitType, count] of Object.entries(expansionGate)) {
      economyLines.push(
        `    if (sc2team_CountCompletedProduction(${player}, "${unitType}") < ${count}) { productionReady = false; }`,
      );
    }
    if (slot.race === "Terran") {
      economyLines.push(...makeTerranAddonLines(player, slot.build, allowSupportAir));
    }
    const purchaseEntries = [];
    const meleeEntries = [];
    // §87: random_ground(종족 고정)는 선호 표가 비어 있어 종족별 기본 훈련
    // 세트를 쓴다(§71 RANDOM_INFRA_BY_RACE와 같은 원리). AISetStock 요청도
    // 같은 표로 낸다. 종족 Random은 빈 표 그대로(멜레 AI 단독).
    const stockSource = slot.build === "random_ground" && slot.race !== "Random"
      ? (RANDOM_TRAIN_BY_RACE[slot.race] ?? {})
      : preferred;
    for (const [unitType, count] of Object.entries(stockSource)) {
      // §68: 기지 수 비례 목표를 폐기하고 도달 불가능한 고정 목표를 건다 —
      // 멜레 AI가 목표를 채우고 생산을 멈추는 일이 없도록.
      stockLines.push(
        `    AISetStock(${player}, ${count * STOCK_SQUEEZE_MULTIPLIER}, "${unitType}");`
      );
      const purchase = CAMPAIGN_PURCHASE_BY_UNIT[unitType];
      if (campaignUnitsPilot && purchase !== undefined) {
        purchaseEntries.push({ unitType, purchase, count });
      } else {
        meleeEntries.push({ unitType, count });
      }
    }
    if (purchaseEntries.length > 0) {
      // 비율 기반 동적 우선순위(사용자 규칙, §61): 매 틱 구매 유닛끼리
      // 보유/목표 비율을 비교해 가장 부족한 종류부터 은행을 쓴다.
      //
      // §87: 틱당 1기 상한과 §62 교차 비율 게이트는 폐지(사용자 지시). 상한은
      // 공장 수와 무관하게 분당 4기를 강제해 "돈 많고 팩토리 많은데 안 뽑는"
      // 관측의 직접 원인이었고, 교차 게이트는 멜레 병종 비율이 낮게 고정된
      // 상황(직접 훈련 디스패처 도입 전)에서 구매를 영구 정지시키는 벽이었다.
      // 이제 부족한 종류부터 시작해 모든 종류가 각자 쿨다운·잔고 하한 안에서
      // 다중 구매한다. 은행 보호는 구매 함수 안의 매 구매 후 하한 재검사가 맡는다.
      const purchaseCall = (entry, indent) => {
        const p = entry.purchase;
        const maxCount = p.producer === "Larva" ? 2 : 0;
        return `${indent}purchasedCount = purchasedCount + sc2team_TryPurchaseCampaignUnit(${player}, "${p.producer}", "${p.prerequisite}", "${entry.unitType}", ${p.minerals}, ${p.gas}, ${p.supply}, ${p.cooldown}.0, ${p.customValue}, ${maxCount});`;
      };
      campaignPurchaseLines.push(
        "    purchaseBestRatio = 2.0;",
        "    purchasePick = 0;",
        "    purchasedCount = 0;",
      );
      purchaseEntries.forEach((entry, i) => {
        campaignPurchaseLines.push(
          `    desired = ${entry.count * STOCK_SQUEEZE_MULTIPLIER};`,
          `    purchaseCurrent = sc2team_CountUnits(${player}, "${entry.unitType}");`,
          "    if (purchaseCurrent < desired &&",
          "        IntToFixed(purchaseCurrent) / IntToFixed(desired) < purchaseBestRatio) {",
          "        purchaseBestRatio = IntToFixed(purchaseCurrent) / IntToFixed(desired);",
          `        purchasePick = ${i + 1};`,
          "    }",
        );
      });
      // 1패스: 가장 부족한 종류가 은행을 먼저 쓴다.
      purchaseEntries.forEach((entry, i) => {
        campaignPurchaseLines.push(
          `    ${i === 0 ? "if" : "else if"} (purchasePick == ${i + 1}) {`,
          purchaseCall(entry, "        "),
          "    }",
        );
      });
      // 2패스: 나머지 종류도 각자 쿨다운·하한·목표치 안에서 구매한다(1패스
      // 종류는 purchasePick 가드로 제외되므로 이중 구매가 없다).
      purchaseEntries.forEach((entry, i) => {
        campaignPurchaseLines.push(
          `    desired = ${entry.count * STOCK_SQUEEZE_MULTIPLIER};`,
          `    if (purchasePick != ${i + 1} && sc2team_CountUnits(${player}, "${entry.unitType}") < desired) {`,
          purchaseCall(entry, "        "),
          "    }",
        );
      });
    }
    // §69: 랩터 진화는 ling_bane/ultra_ling_bane뿐 아니라 종족이 확정된
    // random_ground 저그 슬롯도 구매하게 확장한다(저글링을 뽑으므로).
    // campaignUnitsPilot 조건은 유지.
    if (campaignUnitsPilot &&
        (preferredUpgrades.includes("SC2TeamRaptorEvolution") ||
         (slot.build === "random_ground" && slot.race === "Zerg"))) {
      campaignPurchaseLines.push(
        `    sc2team_TryPurchaseRaptorEvolution(${player});`,
      );
    }
    // §97: 맵의 실제 광물/가스 군집과 SC2 배치 그리드로 미리 검증한 좌표에
    // 일꾼 건설 명령을 직접 내린다(AIExpand는 좌표를 강제점으로 쓰지 않으므로
    // 쓰지 않는다). 시작 타운홀 15 내의 자원줄은 이미 점유된 기지로 제외되며,
    // 실패하면 다음 후보로 커서를 넘긴다.
    economyLines.push(
      `    totalBases = sc2team_CountAllTownHalls(${player}, "${slot.race}");`,
      `    expansionNow = TimerGetElapsed(gv_sc2team_CampaignProductionTimer);`,
      "    canExpand = false;",
      "    townHallCap = townHallTypeCount;",
      `    if (gv_sc2team_ExpansionPending[${player}]) {`,
      `        if (bases > gv_sc2team_ExpansionBaseCount[${player}] &&`,
      `            sc2team_ExpansionCandidateOwnedByPlayer(gv_sc2team_ExpansionRequestedCandidate[${player}], ${player})) {`,
      `            gv_sc2team_ExpansionPending[${player}] = false;`,
      `            gv_sc2team_NextExpansionAttempt[${player}] = expansionNow + 120.0;`,
      `        } else if (totalBases > gv_sc2team_ExpansionBaseCount[${player}]) {`,
      "            canExpand = true;",
      "            townHallCap = townHallTypeCount;",
      `        } else if (expansionNow < gv_sc2team_ExpansionStartDeadline[${player}] &&`,
      `                   sc2team_ExpansionBuilderActive(${player})) {`,
      "            canExpand = true;",
      "            townHallCap = townHallTypeCount + 1;",
      "        } else {",
      `            gv_sc2team_ExpansionPending[${player}] = false;`,
      `            gv_sc2team_NextExpansionAttempt[${player}] = expansionNow + 45.0;`,
      "        }",
      "    }",
      "    expansionTarget = null;",
      // 1단계 진행 중: 허가는 열지 않는다. 도착했을 때만 목표를 넘겨 2단계로 간다.
      `    if (!gv_sc2team_ExpansionPending[${player}] && gv_sc2team_ExpansionStaging[${player}]) {`,
      `        expansionStageTarget = gv_sc2team_ExpansionPoints[gv_sc2team_ExpansionRequestedCandidate[${player}]];`,
      `        if (sc2team_ExpansionBuilderAtTarget(${player}, expansionStageTarget)) {`,
      "            expansionTarget = expansionStageTarget;",
      "            canExpand = true;",
      "            townHallCap = townHallTypeCount + 1;",
      `        } else if (!sc2team_ExpansionBuilderAlive(${player}) ||`,
      `                   expansionNow >= gv_sc2team_ExpansionStageDeadline[${player}]) {`,
      `            gv_sc2team_ExpansionStaging[${player}] = false;`,
      `            gv_sc2team_NextExpansionAttempt[${player}] = expansionNow + 45.0;`,
      "        }",
      "    }",
      // 신규 확장 결정: 일꾼을 보내기만 하고 허가는 그대로 닫아 둔다.
      `    else if (!gv_sc2team_ExpansionPending[${player}] && bases < 5 && totalBases == bases &&`,
      `        expansionNow >= gv_sc2team_NextExpansionAttempt[${player}] &&`,
      `        PlayerGetPropertyInt(${player}, c_playerPropMinerals) >= 400) {`,
      `        expansionStageTarget = sc2team_NextExpansionPointP${player}(${player});`,
      "        if (expansionStageTarget != null) {",
      `            if (sc2team_TryStageExpansionWorker(${player}, "${slot.race}", expansionStageTarget)) {`,
      `                gv_sc2team_ExpansionStaging[${player}] = true;`,
      `                gv_sc2team_ExpansionStageDeadline[${player}] = expansionNow + 150.0;`,
      "            } else {",
      `                gv_sc2team_NextExpansionAttempt[${player}] = expansionNow + 45.0;`,
      "            }",
      "        }",
      "    }",
      // §105.8(감사 B1): 타운홀 전멸 비상구 — §96에 있던 안전장치가 §97/§98
      // 2단계 스테이징 재작성 때 기록 없이 사라졌던 것을 복원. totalBases가
      // 0이면 위의 어떤 분기도 허가를 열지 못해(스테이징은 살아있는 타운홀
      // 기반) 우리 코드도, 이 허가에 묶인 밀레 AI도 새 타운홀을 영영 못
      // 짓는다. 정상 게임 경로(totalBases >= 1)에는 영향이 없다.
      "    if (totalBases == 0) { canExpand = true; townHallCap = townHallTypeCount + 1; }",
      // 허가를 발주보다 **먼저** 적용한다(§96의 "한 번만 호출"은 그대로 지킨다).
      // sc2team_TryBuildExpansionAt는 UnitOrderIsValid로 일꾼을 고르는데, 그 판정은
      // 그 자리에서 즉시 이뤄지므로 이 두 줄이 뒤에 있으면 직전 틱의 "본진 금지"
      // 상태를 보고 매번 실패한다. 그러면 발주는 한 번도 성사되지 않으면서
      // townHallCap +1만 열려, 밀리 AI가 그 허가로 본진 앞에 타운홀을 쌓는다
      // (20분 계측에서 실측). 옛 AIExpand 경로는 비동기 요청이라 이 순서가
      // 무해했지만, 즉시 판정하는 직접 건설에는 치명적이다.
      `    TechTreeUnitAllow(${player}, "${EXPANSION_TOWN_HALL_BY_RACE[slot.race]}", canExpand);`,
      `    TechTreeSetProduceCap(${player}, "${EXPANSION_TOWN_HALL_BY_RACE[slot.race]}", c_techCatUnit, townHallCap);`,
      "    if (expansionTarget != null) {",
      `        expansionIssued = sc2team_TryBuildExpansionAt(${player}, "${slot.race}", expansionTarget);`,
      "        if (expansionIssued) {",
      `            gv_sc2team_ExpansionStaging[${player}] = false;`,
      `            gv_sc2team_ExpansionPending[${player}] = true;`,
      `            gv_sc2team_ExpansionBaseCount[${player}] = bases;`,
      `            gv_sc2team_ExpansionDeadline[${player}] = expansionNow + 180.0;`,
      `            gv_sc2team_ExpansionStartDeadline[${player}] = expansionNow + 40.0;`,
      "        } else {",
      `            gv_sc2team_ExpansionStaging[${player}] = false;`,
      `            gv_sc2team_NextExpansionAttempt[${player}] = expansionNow + 45.0;`,
      "        }",
      "    }",
    );
    // §68: saveForExpansion 생산 동결 전면 삭제(사용자 지시). 병력 생산 상한은
    // 어떤 단계에서도 걸지 않고, 구매·연구도 항상 돈다(자체 잔고 하한이 지킴).
    // §87 지출 순서는 훈련 → 구매 → 연구다. 셋 다 같은 잔고 하한(cost+500/+400)을
    // 쓰므로 순서가 곧 우선권인데, 구매를 앞에 두면 상한 없는 다중 구매가 매 틱
    // 가스를 하한(프레데터 100+400)까지 흡수해 그보다 하한이 높은 표준 병종
    // (전차 125+400, 토르 200+400)이 영구히 굶는다 — 20분 계측에서 mech/thor
    // 5개 슬롯 전차·토르 0기, 프레데터 구매가 없는 bio_tank만 전차 생산으로 실증.
    // §88: 보급 선제 확보 — 훈련 디스패처보다 먼저. 보급이 막히면 아래 훈련
    // 발주가 전부 무효가 되므로 순서가 곧 회복 속도다. 테란은 보급고 선제
    // 건설 + 궤도 사령부 SupplyDrop(즉시 +8), 프로토스는 파일런 선제 건설.
    if (slot.race === "Terran") {
      economyLines.push(
        `    sc2team_TrySupplyStructure(${player}, "SupplyDepot");`,
        `    sc2team_TryCalldownSupplies(${player});`,
      );
    } else if (slot.race === "Protoss") {
      economyLines.push(
        `    sc2team_TrySupplyStructure(${player}, "Pylon");`,
        // §91.9: AIBuild는 프로토스에서 정지한다 — 탐사정 직접 발주가 보장 경로.
        `    sc2team_TryBuildPylonDirect(${player});`,
      );
    }
    if (meleeEntries.length > 0) {
      economyLines.push(...makeTrainDispatchLines(player, slot.build, meleeEntries));
    }
    if (campaignPurchaseLines.length > 0) {
      economyLines.push(...campaignPurchaseLines);
    }
    // §63: AI 업그레이드 연구 — 유휴 연구 구조물에 직접 명령, 틱당 최대 1건.
    const researchLadder = researchLadderForSlot(slot, protossFaction);
    if (researchLadder) {
      economyLines.push(...makeResearchLines(player, researchLadder, "    "));
    }
    playerBlocks.push({ player, slot, stockLines, economyLines });
  }
  // §63 연구 프로브: 사람 슬롯(프로브 참가자)에도 같은 코드 경로를 적용해
  // 명령 인덱스·비용 차감·완료를 API 관측(자기 유닛의 orders/upgrade_ids)으로
  // 결정적으로 검증한다. 릴리스 맵에서는 이 플래그를 켜지 않는다.
  if (researchProbe) {
    const humanIndex = activeSlots.findIndex(
      (slot) => slot && slot.controller === "human"
    );
    if (humanIndex >= 0) {
      const humanSlot = activeSlots[humanIndex];
      const humanLadder = researchLadderForSlot(humanSlot, protossFaction);
      if (humanLadder) {
        playerBlocks.push({
          player: humanIndex + 1,
          stockLines: [],
          economyLines: makeResearchLines(humanIndex + 1, humanLadder, "    "),
        });
      }
    }
  }
  // §95: 집계 캐시 대상 타입 수집.
  //
  // 종전에는 sc2team_Count* 헬퍼 하나하나가 UnitGroup(null, player,
  // RegionEntireMap(), ...)로 그 플레이어의 유닛 전부를 새로 긁어 세었다.
  // 릴리스 설정(커스텀 AI 12명)에서 한 틱의 무조건 전체 스캔이 365회였고,
  // 조건부 타입별 그룹 질의까지 합치면 상한 1,121회다. 이제 플레이어 차례가
  // 오면 단 한 번 훑어 타입별 개수를 배열에 적재하고, 헬퍼는 배열을 읽는다.
  //
  // 표에 없는 타입은 **조용히 0이 되면 안 된다** — 그건 §83·§91.10과 같은
  // 무증상 전면 정지를 만든다. 그래서 인덱스가 없으면 종전 구현(*Live)으로
  // 떨어져 정확하되 느리게 동작한다. 아래 수집은 그 느린 경로를 없애기 위한
  // 최적화일 뿐, 정확성의 전제가 아니다.
  const COUNT_BASE_TYPES = [
    // 일꾼 — sc2team_EconomyWorkerType / sc2team_TryTrainEconomyWorkers
    "SCV", "Probe", "Drone",
    // 타운홀 — Count*TownHalls, sc2team_EconomyWorkerTarget이 이 표만 보고
    // 합산하므로 하나라도 빠지면 조용히 과소 집계된다. verify()가 강제한다.
    "CommandCenter", "OrbitalCommand", "PlanetaryFortress",
    "Nexus", "Hatchery", "Lair", "Hive",
    // 정적 헬퍼가 리터럴로 세는 것들. Gateway/WarpGate와 SupplyDepot/
    // SupplyDepotLowered는 별칭 합산이 필요해 항상 짝으로 있어야 한다.
    "Pylon", "SupplyDepot", "SupplyDepotLowered", "SpawningPool",
    "Gateway", "WarpGate",
    // §102: 가스 건물 — sc2team_CountGasStructures가 값싼 사전 게이트로
    // 합산한다. 하나라도 빠지면 게이트가 과소 집계되어 영영 닫히지 않는다.
    "Refinery", "RefineryRich", "Assimilator", "AssimilatorRich",
    "Extractor", "ExtractorRich",
  ];
  const countedTypes = new Set(COUNT_BASE_TYPES);
  const generatedText = playerBlocks
    .flatMap((block) => [...block.stockLines, ...block.economyLines])
    .join("\n");
  const collect = (pattern, groups) => {
    for (const match of generatedText.matchAll(pattern)) {
      for (const group of groups) {
        if (match[group]) countedTypes.add(match[group]);
      }
    }
  };
  collect(/sc2team_CountCompletedProduction\(\d+, "([^"]+)"\)/g, [1]);
  collect(/sc2team_CountAllProduction\(\d+, "([^"]+)"\)/g, [1]);
  collect(/sc2team_CountUnits\(\d+, "([^"]+)"\)/g, [1]);
  collect(/sc2team_TrySupplyStructure\(\d+, "([^"]+)"\)/g, [1]);
  // 애드온 헬퍼는 생산자와 애드온 양쪽을 센다.
  collect(/sc2team_TryBuildTerranAddon\(\d+, "([^"]+)", "([^"]+)"/g, [1, 2]);
  // 캠페인 구매: 선행 구조물은 CountCompletedProduction, 구매 유닛은 UnitCreate
  // 직후 캐시를 증분해야 하므로 둘 다 표에 필요하다.
  collect(/sc2team_TryPurchaseCampaignUnit\(\d+, "[^"]*", "([^"]+)", "([^"]+)"/g, [1, 2]);
  // 연구 사다리의 선행 구조물 게이트(sc2team_HasResearchTech).
  collect(
    /sc2team_TryResearchUpgrade\(\d+, "[^"]*", "[^"]*", \d+, "[^"]*", "[^"]*", "([^"]+)"/g,
    [1]
  );
  // 별칭 짝 보강. 한쪽만 있으면 합산이 조용히 틀린다.
  if (countedTypes.has("Gateway")) countedTypes.add("WarpGate");
  if (countedTypes.has("SupplyDepot")) countedTypes.add("SupplyDepotLowered");
  // sc2team_CountIndex는 유닛마다 호출되므로 흔한 타입을 앞에 둔다.
  const workerTypes = ["SCV", "Probe", "Drone"];
  const armyTypes = new Set();
  for (const slot of activeSlots) {
    if (!slot || slot.controller !== "custom_ai") continue;
    for (const unitType of Object.keys(PREFERRED_STOCK_BY_BUILD[slot.build] ?? {})) {
      armyTypes.add(unitType);
    }
    for (const unitType of Object.keys(RANDOM_TRAIN_BY_RACE[slot.race] ?? {})) {
      armyTypes.add(unitType);
    }
  }
  const rest = [...countedTypes].filter((unitType) => !workerTypes.includes(unitType));
  const countTypes = [
    ...workerTypes.filter((unitType) => countedTypes.has(unitType)),
    ...rest.filter((unitType) => armyTypes.has(unitType)),
    ...rest.filter((unitType) => !armyTypes.has(unitType)),
  ];
  const countIndexOf = new Map(countTypes.map((unitType, i) => [unitType, i]));
  const countIndexLines = countTypes.map(
    (unitType, i) =>
      `    ${i === 0 ? "if" : "else if"} (unitType == "${unitType}") { return ${i}; }`
  );
  // 별칭 합산에 쓰는 build-time 상수 인덱스. 짝이 없으면 -1이 되어 accessor가
  // 정확한 *Live 경로로 떨어진다.
  // 별칭 합산 분기. 짝이 표에 없으면 분기 자체를 만들지 않는다 — 그러면 그
  // 타입은 accessor의 -1 경로를 타고 정확한 *Live 구현으로 떨어진다.
  const aliasBranch = (array, primary, alias) => {
    if (!countIndexOf.has(alias)) return "";
    return `
    if (productionType == "${primary}") {
        total += gv_sc2team_${array}[player][${countIndexOf.get(alias)}];
    }`;
  };
  const aliasBranches = (array) =>
    aliasBranch(array, "Gateway", "WarpGate") +
    aliasBranch(array, "SupplyDepot", "SupplyDepotLowered");
  const townHallIndexExpr = (kind, types) => {
    const missing = types.filter((unitType) => !countIndexOf.has(unitType));
    if (missing.length > 0) {
      fail(`Town hall type missing from the count table: ${missing.join(", ")}`);
    }
    return types
      .map((unitType) => `gv_sc2team_${kind}[player][${countIndexOf.get(unitType)}]`)
      .join(" + ");
  };
  const TOWN_HALLS_BY_RACE = {
    Terran: ["CommandCenter", "OrbitalCommand", "PlanetaryFortress"],
    Protoss: ["Nexus"],
    Zerg: ["Hatchery", "Lair", "Hive"],
  };
  const ECONOMY_TOWN_HALLS = [
    "CommandCenter", "OrbitalCommand", "PlanetaryFortress",
    "Nexus", "Hatchery", "Lair", "Hive",
  ];
  if (EXPANSION_LAYOUT.version !== 1 || !Array.isArray(EXPANSION_LAYOUT.candidates)) {
    fail("Invalid expansion-layout.json: regenerate it with verification/analyze_expansion_layout.py");
  }
  const expansionCandidatesFor = (slot) => {
    if (!slot || slot.race === "Random") return [];
    const logicalSlot = String(slot.slot);
    return EXPANSION_LAYOUT.candidates
      .filter((candidate) =>
        candidate.covered_by_starts.length === 0 &&
        Array.isArray(candidate.race_positions?.[slot.race]))
      .map((candidate) => ({
        id: candidate.id,
        point: candidate.race_positions[slot.race],
        pathing: Number(candidate.pathing?.[logicalSlot] ?? 0),
      }))
      .sort((left, right) => {
        const leftUnreachable = left.pathing <= 0 ? 1 : 0;
        const rightUnreachable = right.pathing <= 0 ? 1 : 0;
        return leftUnreachable - rightUnreachable ||
          left.pathing - right.pathing || left.id - right.id;
      });
  };
  const expansionLayoutPoints = EXPANSION_LAYOUT.candidates.map((candidate) => {
    const point = candidate.race_positions?.Terran ??
      candidate.race_positions?.Protoss ?? candidate.race_positions?.Zerg;
    if (!Array.isArray(point)) fail(`Expansion candidate ${candidate.id} has no point`);
    return { id: candidate.id, point };
  });
  const expansionPointInitializers = expansionLayoutPoints
    .map(({ id, point }) =>
      `    gv_sc2team_ExpansionPoints[${id}] = Point(${Number(point[0]).toFixed(1)}, ${Number(point[1]).toFixed(1)});`)
    .join("\n");
  const expansionPointFunctions = playerBlocks
    .filter((block) => block.slot && block.slot.race !== "Random")
    .map((block) => {
      const candidates = expansionCandidatesFor(block.slot);
      if (candidates.length === 0) {
        fail(`No validated expansion candidates for P${block.slot.slot} ${block.slot.race}`);
      }
      const checks = candidates.map((candidate, index) => {
        const x = Number(candidate.point[0]).toFixed(1);
        const y = Number(candidate.point[1]).toFixed(1);
        return `    if (gv_sc2team_ExpansionCursor[player] <= ${index}) {\n` +
          `        target = Point(${x}, ${y});\n` +
          `        if (sc2team_ExpansionCandidateOpen(${candidate.id})) {\n` +
          `            gv_sc2team_ExpansionRequestedCandidate[player] = ${candidate.id};\n` +
          `            gv_sc2team_ExpansionCursor[player] = ${index + 1};\n` +
          `            return target;\n` +
          `        }\n` +
          `    }`;
      });
      // §102: 후보 개폐를 여기서 한 번만 계산한다. 종전에는 아래 후보 검사
      // 하나하나가 자기 반경 스캔을 새로 만들어 한 프레임에 최대 44개가 몰렸다.
      return `point sc2team_NextExpansionPointP${block.player} (int player) {\n` +
        `    point target;\n\n` +
        `    sc2team_RefreshExpansionClosed();\n${checks.join("\n")}\n` +
        `    gv_sc2team_ExpansionCursor[player] = 0;\n` +
        `    return null;\n}`;
    })
    .join("\n\n");
  const expansionInitialState = playerBlocks
    .filter((block) => block.slot && block.slot.race !== "Random")
    .map((block) => `    gv_sc2team_NextExpansionAttempt[${block.player}] = 60.0;`)
    .join("\n");
  // §95 라운드로빈: 한 틱에 한 플레이어만 처리한다. 전체 한 바퀴가 항상
  // 12게임초가 되도록 주기를 인원수로 나눈다 — 인원이 적을 때 주기가 그대로
  // 1초면 플레이어당 처리 빈도가 종전(15초)의 15배가 되어 생산·연구 속도가
  // 설정에 따라 달라진다. 한 바퀴를 고정하면 슬롯 수와 무관하게 동작이 같다.
  const STEER_CYCLE_SECONDS = 12.0;
  const steerCount = Math.max(playerBlocks.length, 1);
  const steerPeriod = (STEER_CYCLE_SECONDS / steerCount).toFixed(3);
  const steerFunctionName = (player) => `sc2team_SteerP${player}`;
  const steerDeclarations = `    int bases;
    int totalBases;
    int desired;
    int townHallTypeCount;
    int townHallCap;
    int currentCount;
    fixed expansionNow;
    point expansionTarget;
    point expansionStageTarget;
    bool canExpand;
    bool expansionIssued;
    bool productionReady;
    bool workersShort;
    int workerCount;
    int richBonus;
    int addonTarget;
    fixed purchaseBestRatio;
    int purchasePick;
    int purchaseCurrent;
    int purchasedCount;
    fixed trainBestRatio;
    int trainPick;
    int trainCurrent;
    bool researched;
    bool addonOrdered;`;
  const steerFunctions = playerBlocks
    .map((block) => {
      const body = [...block.stockLines, ...block.economyLines].join("\n");
      return `void ${steerFunctionName(block.player)} () {
${steerDeclarations}

    sc2team_RefreshCounts(${block.player});
${body}
}`;
    })
    .join("\n\n");
  const steerDispatch = playerBlocks
    .map(
      (block, i) =>
        `    ${i === 0 ? "if" : "else if"} (gv_sc2team_SteerCursor == ${i + 1}) { ${steerFunctionName(block.player)}(); }`
    )
    .join("\n");
  const steerInitialPass = playerBlocks
    .map((block) => `    ${steerFunctionName(block.player)}();`)
    .join("\n");

return `trigger gt_sc2team_ProductionSteering;
timer gv_sc2team_CampaignProductionTimer;
// Per-player, per-structure history for safe infrastructure recovery.  This
// table is generated to the exact set of structures used by the active map.
bool[16][${Math.max(rebuildInfraTypes.size, 1)}] gv_sc2team_InfraSeen;

// §95: 플레이어별 타입 집계 캐시. 차례가 온 플레이어의 유닛을 한 번만 훑어
// 채우고, 그 차례 동안 모든 sc2team_Count* 헬퍼가 이 배열을 읽는다.
int gv_sc2team_SteerCursor;
int[16][${countTypes.length}] gv_sc2team_CountAll;
int[16][${countTypes.length}] gv_sc2team_CountDone;
bool[16] gv_sc2team_CountReady;
bool[16] gv_sc2team_ExpansionPending;
int[16] gv_sc2team_ExpansionBaseCount;
int[16] gv_sc2team_ExpansionCursor;
int[16] gv_sc2team_ExpansionRequestedCandidate;
fixed[16] gv_sc2team_ExpansionDeadline;
// 건설이 아직 시작되지 않은 동안만 유효한 짧은 마감. 종전에는 완공 마감(180초)
// 하나로 townHallCap을 +1로 열어두었는데, 그 180초 내내 밀리 AI가 그 허가를
// 자기 자리(본진 앞)에 써버렸다 — 20분 계측에서 P12 넥서스 4채가 전부 시작점
// 13.5 이내에 몰린 원인이다. 착공 전 창구는 여기서 짧게 끊는다.
fixed[16] gv_sc2team_ExpansionStartDeadline;
unit[16] gv_sc2team_ExpansionBuilder;
// 1단계(이동) 진행 중 여부. 이동에는 테크트리 허가가 필요 없으므로 이 동안
// townHallCap은 닫아 둔다 — 확장 거리가 56~204인 이 맵에서 걷는 시간만큼
// 허가를 열어두면 밀리 AI가 자기 기지 옆(걸어서 몇 초)에 항상 먼저 짓는다.
bool[16] gv_sc2team_ExpansionStaging;
fixed[16] gv_sc2team_ExpansionStageDeadline;
fixed[16] gv_sc2team_NextExpansionAttempt;
point[${expansionLayoutPoints.length + 1}] gv_sc2team_ExpansionPoints;
// §102: 후보 개폐를 한 번의 스캔으로 미리 계산해 담는다(자세한 근거는
// sc2team_RefreshExpansionClosed 주석).
bool[${expansionLayoutPoints.length + 1}] gv_sc2team_ExpansionClosed;
// §102: 스크립트가 잠시 제어한 경제 일꾼 명단. §97이 전투 유닛 제어 해제에
// 쓴 것과 같은 방식이다 — 종전에는 해제 대상 몇 기를 찾으려고 매 턴 그
// 플레이어의 유닛 전부를 훑었다.
unitgroup[16] gv_sc2team_EconomyControlled;
// §102: 가스 건설 스캔 백오프. 지을 것이 없는데도 매 턴 완주하던 전체
// 스캔을 막는다. 기지 수가 변하면 즉시 다시 시도한다.
fixed[16] gv_sc2team_NextGasAttempt;
int[16] gv_sc2team_GasScanBases;
// §102: 생산자·구조물 그룹 캐시. 슬롯이 **여러 개**여야 한다 — 프로토스
// 코드젠은 관문 훈련과 차원 관문 소환을 병종마다 번갈아 부르고(관문 →
// 차원관문 → 관문 → …), 테란 연구 사다리는 엔지니어링 베이·무기고·병영
// 기술실·팩토리 기술실을 오간다. 1슬롯이면 매번 빗나가 아무것도 아끼지 못한다.
// sc2team_RefreshCounts가 턴 시작에 무효화한다.
string[4] gv_sc2team_ProducerCacheType;
int[4] gv_sc2team_ProducerCachePlayer;
unitgroup[4] gv_sc2team_ProducerCache;
int gv_sc2team_ProducerCacheNext;

bool sc2team_IsCompletedStructure (unit candidate) {
    return candidate != null && UnitIsAlive(candidate) &&
        !libNtve_gf_UnitIsUnderConstruction(candidate);
}

// §95: 타입 -> 집계 인덱스. 표에 없으면 -1이고, 호출자는 종전 전체 스캔
// 구현으로 떨어진다(느리지만 정확). 유닛마다 호출되므로 흔한 타입이 앞이다.
int sc2team_CountIndex (string unitType) {
${countIndexLines.join("\n")}
    return -1;
}

// §95: 한 플레이어의 유닛을 한 번 훑어 타입별 전체/완성 개수를 적재한다.
// 종전의 sc2team_Count* 호출 하나하나가 이 작업을 통째로 반복하고 있었다.
void sc2team_RefreshCounts (int player) {
    unitgroup playerUnits;
    unit currentUnit;
    int unitIndex;
    int typeIndex;
    int slot;

    // §102: 이 턴의 생산자 그룹 캐시를 무효화한다. RefreshCounts는 모든
    // 스티어 함수의 첫 문장이므로 여기가 유일한 턴 경계다.
    for (slot = 0; slot < 4; slot += 1) {
        gv_sc2team_ProducerCacheType[slot] = "";
        gv_sc2team_ProducerCachePlayer[slot] = 0;
    }
    gv_sc2team_ProducerCacheNext = 0;
    for (slot = 0; slot < ${countTypes.length}; slot += 1) {
        gv_sc2team_CountAll[player][slot] = 0;
        gv_sc2team_CountDone[player][slot] = 0;
    }
    playerUnits = UnitGroup(null, player, RegionEntireMap(), UnitFilter(0, 0, 0, 0), 0);
    unitIndex = UnitGroupCount(playerUnits, c_unitCountAlive);
    for (;; unitIndex -= 1) {
        currentUnit = UnitGroupUnitFromEnd(playerUnits, unitIndex);
        if (currentUnit == null) {
            break;
        }
        typeIndex = sc2team_CountIndex(UnitGetType(currentUnit));
        if (typeIndex < 0) {
            continue;
        }
        gv_sc2team_CountAll[player][typeIndex] += 1;
        if (sc2team_IsCompletedStructure(currentUnit)) {
            gv_sc2team_CountDone[player][typeIndex] += 1;
        }
    }
    gv_sc2team_CountReady[player] = true;
}

int sc2team_CountCompletedProductionLive (int player, string productionType) {
    unitgroup playerUnits;
    unit currentUnit;
    int unitIndex;
    int count = 0;
    string currentType;

    playerUnits = UnitGroup(null, player, RegionEntireMap(), UnitFilter(0, 0, 0, 0), 0);
    unitIndex = UnitGroupCount(playerUnits, c_unitCountAlive);
    for (;; unitIndex -= 1) {
        currentUnit = UnitGroupUnitFromEnd(playerUnits, unitIndex);
        if (currentUnit == null) {
            break;
        }
        currentType = UnitGetType(currentUnit);
        if (sc2team_IsCompletedStructure(currentUnit) &&
            (currentType == productionType ||
             (productionType == "Gateway" && currentType == "WarpGate") ||
             (productionType == "SupplyDepot" && currentType == "SupplyDepotLowered"))) {
            count += 1;
        }
    }
    return count;
}

int sc2team_CountAllProductionLive (int player, string productionType) {
    unitgroup playerUnits;
    unit currentUnit;
    int unitIndex;
    int count = 0;

    playerUnits = UnitGroup(null, player, RegionEntireMap(), UnitFilter(0, 0, 0, 0), 0);
    unitIndex = UnitGroupCount(playerUnits, c_unitCountAlive);
    for (;; unitIndex -= 1) {
        currentUnit = UnitGroupUnitFromEnd(playerUnits, unitIndex);
        if (currentUnit == null) {
            break;
        }
        if (UnitGetType(currentUnit) == productionType ||
            (productionType == "Gateway" && UnitGetType(currentUnit) == "WarpGate") ||
            (productionType == "SupplyDepot" && UnitGetType(currentUnit) == "SupplyDepotLowered")) {
            count += 1;
        }
    }
    return count;
}

int sc2team_CountCompletedTownHallsLive (int player, string race) {
    unitgroup playerUnits;
    unit currentUnit;
    int unitIndex;
    int count = 0;
    string currentType;

    playerUnits = UnitGroup(null, player, RegionEntireMap(), UnitFilter(0, 0, 0, 0), 0);
    unitIndex = UnitGroupCount(playerUnits, c_unitCountAlive);
    for (;; unitIndex -= 1) {
        currentUnit = UnitGroupUnitFromEnd(playerUnits, unitIndex);
        if (currentUnit == null) {
            break;
        }
        currentType = UnitGetType(currentUnit);
        if (!sc2team_IsCompletedStructure(currentUnit)) {
            continue;
        }
        if ((race == "Terran" &&
             (currentType == "CommandCenter" || currentType == "OrbitalCommand" ||
              currentType == "PlanetaryFortress")) ||
            (race == "Protoss" && currentType == "Nexus") ||
            (race == "Zerg" &&
             (currentType == "Hatchery" || currentType == "Lair" ||
              currentType == "Hive"))) {
            count += 1;
        }
    }
    return count;
}

int sc2team_CountAllTownHallsLive (int player, string race) {
    unitgroup playerUnits;
    unit currentUnit;
    int unitIndex;
    int count = 0;
    string currentType;

    playerUnits = UnitGroup(null, player, RegionEntireMap(), UnitFilter(0, 0, 0, 0), 0);
    unitIndex = UnitGroupCount(playerUnits, c_unitCountAlive);
    for (;; unitIndex -= 1) {
        currentUnit = UnitGroupUnitFromEnd(playerUnits, unitIndex);
        if (currentUnit == null) {
            break;
        }
        currentType = UnitGetType(currentUnit);
        if ((race == "Terran" &&
             (currentType == "CommandCenter" || currentType == "OrbitalCommand" ||
              currentType == "PlanetaryFortress")) ||
            (race == "Protoss" && currentType == "Nexus") ||
            (race == "Zerg" &&
             (currentType == "Hatchery" || currentType == "Lair" ||
              currentType == "Hive"))) {
            count += 1;
        }
    }
    return count;
}

int sc2team_CountUnitsLive (int player, string unitType) {
    return UnitGroupCount(
        UnitGroup(unitType, player, RegionEntireMap(), UnitFilter(0, 0, 0, 0), 0),
        c_unitCountAlive
    );
}

// §95: 아래 다섯 헬퍼가 공개 인터페이스다. 호출부(생성 코드 365곳)는 한 글자도
// 바뀌지 않았고, 데이터 출처만 "매번 전체 맵 스캔"에서 "차례 시작에 한 번 채운
// 배열"로 바뀌었다. 캐시가 준비되지 않았거나(차례 밖 호출) 타입이 표에 없으면
// 종전 구현으로 떨어진다 — 조용한 0은 §83·§91.10급 무증상 정지를 만든다.
int sc2team_CountAllProduction (int player, string productionType) {
    int typeIndex;
    int total;

    if (!gv_sc2team_CountReady[player]) {
        return sc2team_CountAllProductionLive(player, productionType);
    }
    typeIndex = sc2team_CountIndex(productionType);
    if (typeIndex < 0) {
        return sc2team_CountAllProductionLive(player, productionType);
    }
    total = gv_sc2team_CountAll[player][typeIndex];
    // 별칭: 관문은 차원 관문으로, 보급고는 내린 보급고로 변한다.${aliasBranches("CountAll")}
    return total;
}

int sc2team_CountCompletedProduction (int player, string productionType) {
    int typeIndex;
    int total;

    if (!gv_sc2team_CountReady[player]) {
        return sc2team_CountCompletedProductionLive(player, productionType);
    }
    typeIndex = sc2team_CountIndex(productionType);
    if (typeIndex < 0) {
        return sc2team_CountCompletedProductionLive(player, productionType);
    }
    total = gv_sc2team_CountDone[player][typeIndex];${aliasBranches("CountDone")}
    return total;
}

int sc2team_CountUnits (int player, string unitType) {
    int typeIndex;

    if (!gv_sc2team_CountReady[player]) {
        return sc2team_CountUnitsLive(player, unitType);
    }
    typeIndex = sc2team_CountIndex(unitType);
    if (typeIndex < 0) {
        return sc2team_CountUnitsLive(player, unitType);
    }
    return gv_sc2team_CountAll[player][typeIndex];
}

int sc2team_CountCompletedTownHalls (int player, string race) {
    if (!gv_sc2team_CountReady[player]) {
        return sc2team_CountCompletedTownHallsLive(player, race);
    }
    if (race == "Terran") {
        return ${townHallIndexExpr("CountDone", TOWN_HALLS_BY_RACE.Terran)};
    }
    else if (race == "Protoss") {
        return ${townHallIndexExpr("CountDone", TOWN_HALLS_BY_RACE.Protoss)};
    }
    else if (race == "Zerg") {
        return ${townHallIndexExpr("CountDone", TOWN_HALLS_BY_RACE.Zerg)};
    }
    return 0;
}

int sc2team_CountAllTownHalls (int player, string race) {
    if (!gv_sc2team_CountReady[player]) {
        return sc2team_CountAllTownHallsLive(player, race);
    }
    if (race == "Terran") {
        return ${townHallIndexExpr("CountAll", TOWN_HALLS_BY_RACE.Terran)};
    }
    else if (race == "Protoss") {
        return ${townHallIndexExpr("CountAll", TOWN_HALLS_BY_RACE.Protoss)};
    }
    else if (race == "Zerg") {
        return ${townHallIndexExpr("CountAll", TOWN_HALLS_BY_RACE.Zerg)};
    }
    return 0;
}

// §94: 일반 AI 경제 보장. 멜레 AI가 가스 건설·배정·일꾼 복구를 건너뛰어도
// 모든 자원기지의 광물(덩이당 2기)과 가스(개당 3기)를 채운다.
// §82: AIBuild cannot place Terran addons because they are attached to an
// existing producer.  This issues the native producer ability only when the
// building is complete, idle, and the engine says the attachment placement is
// valid.  Invalid/attached/blocked producers are skipped, not spammed.
// §95: 집계 래퍼(sc2team_CountAllProduction)를 쓰므로 그 뒤에 정의한다 —
// Galaxy는 사용 전 선언을 요구한다.
// §102: 생산자·구조물 그룹 캐시. 코드젠은 같은 건물 타입을 연속으로 여러 번
// 호출한다(관문 4종 + 차원관문 4종, 병영 3종, 팩토리 2~3종, 연구 사다리는
// 엔지니어링 베이·무기고를 최대 15회). 그때마다 전체 맵 UnitGroup을 새로
// 만들던 것을 한 턴 안에서 타입당 한 번으로 접는다.
//
// 스냅숏 재사용이 안전한 이유: 생산·연구 건물은 한 턴 도중에 생기거나 사라지지
// 않는다. 대기열은 그룹이 아니라 유닛에서 UnitOrderCount로 매번 새로 읽으므로,
// 앞선 호출이 발주한 결과가 뒤 호출의 대기열 상한 판정에 정상 반영된다.
//
// 훈련·연구·애드온이 함께 쓴다. 셋 다 완성 건물에 명령만 내리고 유닛을
// 없애지 않는다.
//
// **구매는 이 캐시를 쓰지 않는다.** 구매는 라바를 UnitRemove로 없애는데,
// 제거된 유닛이 남아 있는 스냅숏은 UnitGroupUnitFromEnd가 null을 돌려주게
// 만들어 순회를 조기 종료시킬 수 있다. 한 턴 안의 실행 순서가 훈련 → 구매 →
// 연구라, 훈련이 캐시에 올린 "Larva" 스냅숏은 구매가 라바를 지운 뒤에도
// 슬롯에 남는다 — 연구·애드온은 건물 타입만 요청하므로 그 슬롯을 되읽지
// 않는다. 여기에 구매를 끼워 넣으면 그 가정이 깨진다.
//
// Galaxy는 선언 후 사용이므로 첫 호출자(애드온)보다 앞에 있어야 한다.
unitgroup sc2team_ProducerGroup (int player, string producerType) {
    int slot;

    for (slot = 0; slot < 4; slot += 1) {
        if (gv_sc2team_ProducerCachePlayer[slot] == player &&
            gv_sc2team_ProducerCacheType[slot] == producerType) {
            return gv_sc2team_ProducerCache[slot];
        }
    }
    slot = gv_sc2team_ProducerCacheNext;
    gv_sc2team_ProducerCache[slot] =
        UnitGroup(producerType, player, RegionEntireMap(), UnitFilter(0, 0, 0, 0), 0);
    gv_sc2team_ProducerCachePlayer[slot] = player;
    gv_sc2team_ProducerCacheType[slot] = producerType;
    gv_sc2team_ProducerCacheNext = slot + 1;
    if (gv_sc2team_ProducerCacheNext >= 4) {
        gv_sc2team_ProducerCacheNext = 0;
    }
    return gv_sc2team_ProducerCache[slot];
}

bool sc2team_TryBuildTerranAddon (
    int player,
    string producerType,
    string addonType,
    string abilityLink,
    int commandIndex,
    int targetCount
) {
    unitgroup producers;
    unit currentUnit;
    int unitIndex;
    order addonOrder;

    if (targetCount <= 0 ||
        sc2team_CountAllProduction(player, addonType) >= targetCount) {
        return false;
    }
    producers = sc2team_ProducerGroup(player, producerType);
    unitIndex = UnitGroupCount(producers, c_unitCountAlive);
    for (;; unitIndex -= 1) {
        currentUnit = UnitGroupUnitFromEnd(producers, unitIndex);
        if (currentUnit == null) {
            break;
        }
        if (!sc2team_IsCompletedStructure(currentUnit) || UnitOrderCount(currentUnit) != 0) {
            continue;
        }
        addonOrder = OrderTargetingPoint(
            AbilityCommand(abilityLink, commandIndex),
            UnitGetPosition(currentUnit)
        );
        if (!UnitOrderIsValid(currentUnit, addonOrder)) {
            continue;
        }
        UnitIssueOrder(currentUnit, addonOrder, c_orderQueueReplace);
        return true;
    }
    return false;
}

bool sc2team_IsEconomyTownHall (unit candidate) {
    string unitType = UnitGetType(candidate);
    return unitType == "CommandCenter" || unitType == "OrbitalCommand" ||
        unitType == "PlanetaryFortress" || unitType == "Nexus" ||
        unitType == "Hatchery" || unitType == "Lair" || unitType == "Hive";
}

bool sc2team_IsEconomyMineral (unit candidate) {
    string unitType = UnitGetType(candidate);
    return unitType == "MineralField" || unitType == "MineralField750" ||
        unitType == "RichMineralField" || unitType == "RichMineralField750" ||
        unitType == "PurifierRichMineralField";
}

bool sc2team_IsEconomyGeyser (unit candidate) {
    string unitType = UnitGetType(candidate);
    return unitType == "VespeneGeyser" || unitType == "RichVespeneGeyser";
}

bool sc2team_IsEconomyGasStructure (unit candidate) {
    string unitType = UnitGetType(candidate);
    return unitType == "Refinery" || unitType == "RefineryRich" ||
        unitType == "Assimilator" || unitType == "AssimilatorRich" ||
        unitType == "Extractor" || unitType == "ExtractorRich";
}

string sc2team_EconomyWorkerType (int player) {
    if (sc2team_CountUnits(player, "SCV") > 0) { return "SCV"; }
    if (sc2team_CountUnits(player, "Probe") > 0) { return "Probe"; }
    if (sc2team_CountUnits(player, "Drone") > 0) { return "Drone"; }
    // 일꾼이 전멸해도 살아 있는 타운홀의 종족으로 복구한다.
    if (sc2team_CountCompletedTownHalls(player, "Terran") > 0) { return "SCV"; }
    if (sc2team_CountCompletedTownHalls(player, "Protoss") > 0) { return "Probe"; }
    if (sc2team_CountCompletedTownHalls(player, "Zerg") > 0) { return "Drone"; }
    return "";
}

string sc2team_EconomyHarvestAbility (string workerType) {
    if (workerType == "SCV") { return "SCVHarvest"; }
    if (workerType == "Probe") { return "ProbeHarvest"; }
    if (workerType == "Drone") { return "DroneHarvest"; }
    return "";
}

int sc2team_EconomyWorkerTargetLive (int player) {
    unitgroup halls;
    unit currentHall;
    int hallIndex;
    int target = 0;

    halls = UnitGroup(null, player, RegionEntireMap(), UnitFilter(0, 0, 0, 0), 0);
    hallIndex = UnitGroupCount(halls, c_unitCountAlive);
    for (;; hallIndex -= 1) {
        currentHall = UnitGroupUnitFromEnd(halls, hallIndex);
        if (currentHall == null) { break; }
        if (!sc2team_IsCompletedStructure(currentHall) || !sc2team_IsEconomyTownHall(currentHall)) {
            continue;
        }
        // 기존 일꾼을 자원별로 강제 배정하지 않기로 했으므로, 확장을 막는
        // 광물×2·가스×3 포화 목표도 폐기한다. 기지당 16기만 보충한다.
        target += 16;
    }
    return target;
}

// §95: 완성 자원기지 수 × 16. 캐시가 준비돼 있으면 배열 합산으로 끝난다.
int sc2team_EconomyWorkerTarget (int player) {
    if (gv_sc2team_CountReady[player]) {
        return (${townHallIndexExpr("CountDone", ECONOMY_TOWN_HALLS)}) * 16;
    }
    return sc2team_EconomyWorkerTargetLive(player);
}

unit sc2team_EconomyWorkerAt (int player, string workerType, point anchor, fixed now) {
    unitgroup workers;
    unit currentUnit;
    unit fallback = null;
    int unitIndex;

    workers = UnitGroup(workerType, player, RegionCircle(anchor, 22.0), UnitFilter(0, 0, 0, 0), 0);
    unitIndex = UnitGroupCount(workers, c_unitCountAlive);
    for (;; unitIndex -= 1) {
        currentUnit = UnitGroupUnitFromEnd(workers, unitIndex);
        if (currentUnit == null) { break; }
        // 18은 파일런 건설 중 탐사정, 20은 이 경제 틱에서 이미 고른 일꾼,
        // 22는 확장 스테이징/건설 반환 대기 일꾼(§105.8 감사 C3: 종전엔 가스
        // 피커만 22를 안 봐서 확장 이동 중인 일꾼을 뺏을 수 있었다).
        if (UnitGetCustomValue(currentUnit, 18) > now ||
            UnitGetCustomValue(currentUnit, 20) > now ||
            UnitGetCustomValue(currentUnit, 22) > now) {
            continue;
        }
        // §105.8(감사 C3): 멜레 AI가 건설을 보냈거나 짓고 있는 일꾼은 우리
        // 표식이 없어 fallback으로 선택되고, c_orderQueueReplace가 진행 중인
        // 멜레 AI 건설을 취소시켜 미완성 건물을 남긴다. "채취 중"만 fallback
        // 후보다. fallback 자체를 없애는 것은 금물 — 포화 기지엔 유휴 일꾼이
        // 없어 가스 건설이 §91.10식 조용히 죽은 기능이 된다.
        if (UnitOrderHasAbil(currentUnit, "TerranBuild") ||
            UnitOrderHasAbil(currentUnit, "ProtossBuild") ||
            UnitOrderHasAbil(currentUnit, "ZergBuild")) {
            continue;
        }
        if (UnitOrderCount(currentUnit) == 0) { return currentUnit; }
        if (fallback == null) { fallback = currentUnit; }
    }
    return fallback;
}

// §103: 이 일꾼이 그 지점까지 **실제로 걸어갈 수 있는가.**
//
// UnitOrderIsValid는 "그 자리에 그 건물을 놓을 수 있는가"만 본다. 경로는 보지
// 않는다. 그래서 절벽 위처럼 배치는 유효하지만 일꾼이 갈 수 없는 지점에도
// 명령이 정상적으로 발행되고, 일꾼은 길을 찾지 못한 채 서 있거나 엉뚱하게
// 돌아다닌다(사용자 실관측: 파일런을 언덕 위에 지으려 함). 배치 유효성과
// 도달 가능성은 서로 다른 검사이며, 직접 건설 명령에는 **둘 다** 필요하다.
//
// AIPathingCostUnit은 경로가 없으면 음수를 돌려준다 — Blizzard 자신의 판정과
// 같다(TactCampAI.galaxy는 반환값 < 0 을 실패로, LibCOMU.galaxy는 > 0 을
// 도달 가능으로 쓴다). 세 번째 인자 true는 AI.galaxy의
// c_ignoreEnemyBuildings와 같은 값이다(적 건물은 일시적 장애물이므로 무시).
//
// 비용 주의: 이건 실제 경로 탐색이다. 반드시 UnitOrderIsValid가 통과한 뒤에만
// (&& 단축 평가로) 부르고, 통과하는 첫 후보에서 즉시 반환해 호출 수를 묶는다.
bool sc2team_BuilderCanReach (unit builder, point target) {
    if (builder == null) { return false; }
    return AIPathingCostUnit(builder, target, true) >= 0;
}

// §102: 스크립트가 잠시 제어한 경제 일꾼을 명단에 올린다. 이 명단이 없으면
// 해제 대상 몇 기를 찾으려고 매 턴 그 플레이어의 유닛 전부를 훑어야 한다
// (§97이 전투 유닛 제어 해제에서 이미 같은 이유로 없앤 구조다).
// Galaxy는 선언 후 사용이므로 첫 호출자보다 앞에 있어야 한다.
void sc2team_TrackEconomyWorker (int player, unit worker) {
    if (worker == null) { return; }
    if (player >= 1 && player <= 15 &&
        !UnitGroupHasUnit(gv_sc2team_EconomyControlled[player], worker)) {
        UnitGroupAdd(gv_sc2team_EconomyControlled[player], worker);
    }
}

// AIExpand는 전달한 좌표를 강제 건설점으로 취급하지 않는다. 실제로는 밀리 AI가
// 안전하다고 판단한 기존 기지 주변에 다시 지을 수 있으므로, 오프라인에서 검증한
// 5x5 후보에는 일꾼의 종족별 본진 건설 명령을 직접 내린다.
bool sc2team_TryBuildExpansionAt (int player, string race, point target) {
    unitgroup workers;
    unit currentWorker;
    unit builder = null;
    unit fallback = null;
    order buildOrder;
    string workerType;
    int unitIndex;
    fixed currentDistance;
    fixed bestDistance = 100000.0;
    fixed fallbackDistance = 100000.0;
    fixed now = TimerGetElapsed(gv_sc2team_CampaignProductionTimer);

    if (race == "Terran") {
        workerType = "SCV";
        buildOrder = OrderTargetingPoint(AbilityCommand("TerranBuild", 0), target);
    }
    else if (race == "Protoss") {
        workerType = "Probe";
        buildOrder = OrderTargetingPoint(AbilityCommand("ProtossBuild", 0), target);
    }
    else if (race == "Zerg") {
        workerType = "Drone";
        buildOrder = OrderTargetingPoint(AbilityCommand("ZergBuild", 0), target);
    }
    else {
        return false;
    }
    workers = UnitGroup(workerType, player, RegionEntireMap(), UnitFilter(0, 0, 0, 0), 0);
    unitIndex = UnitGroupCount(workers, c_unitCountAlive);
    for (;; unitIndex -= 1) {
        currentWorker = UnitGroupUnitFromEnd(workers, unitIndex);
        if (currentWorker == null) { break; }
        // 1단계에서 이미 목표 지점까지 보내 둔 일꾼은 바쁨 표시(18/20/22)를
        // 스스로 달고 있으므로 예외로 통과시킨다. 그 일꾼이 목표에 서 있으니
        // 아래 최근접 선택에서 자연히 뽑힌다.
        if (currentWorker != gv_sc2team_ExpansionBuilder[player] &&
            (UnitGetCustomValue(currentWorker, 18) > now ||
             UnitGetCustomValue(currentWorker, 20) > now ||
             UnitGetCustomValue(currentWorker, 22) > now)) {
            continue;
        }
        if (!UnitOrderIsValid(currentWorker, buildOrder)) { continue; }
        currentDistance = DistanceBetweenPoints(UnitGetPosition(currentWorker), target);
        if (UnitOrderCount(currentWorker) == 0 && currentDistance < bestDistance) {
            builder = currentWorker;
            bestDistance = currentDistance;
        }
        else if (currentDistance < fallbackDistance) {
            fallback = currentWorker;
            fallbackDistance = currentDistance;
        }
    }
    if (builder == null) { builder = fallback; }
    if (builder == null) { return false; }
    // §103: 도달 가능성은 지형 속성이므로 일꾼마다 볼 필요가 없다. 후보를 다
    // 고른 뒤 선택된 일꾼으로 한 번만 확인한다(경로 탐색 호출 1회).
    if (!sc2team_BuilderCanReach(builder, target)) { return false; }
    AISetUnitScriptControlled(builder, true);
    UnitIssueOrder(builder, buildOrder, c_orderQueueReplace);
    UnitSetCustomValue(builder, 20, now + 180.0);
    UnitSetCustomValue(builder, 22, now + 180.0);
    sc2team_TrackEconomyWorker(player, builder);
    // 착공 전 확장 허가를 이 일꾼이 살아 있는 동안으로 한정하기 위해 기억한다.
    gv_sc2team_ExpansionBuilder[player] = builder;
    return true;
}

// 발주한 일꾼이 아직 살아서 명령을 수행 중인가. 죽거나 명령을 잃으면 확장
// 허가(townHallCap +1)를 즉시 닫아 밀리 AI가 대신 쓰지 못하게 한다.
bool sc2team_ExpansionBuilderActive (int player) {
    unit builder = gv_sc2team_ExpansionBuilder[player];

    if (builder == null) { return false; }
    if (!UnitIsAlive(builder)) { return false; }
    return UnitOrderCount(builder) > 0;
}

// 확장 1단계: 일꾼을 목표 지점으로 '이동만' 시킨다. 이동은 테크트리 허가가
// 필요 없으므로 걷는 동안 townHallCap을 열지 않아도 된다. 도착 후에야 허가를
// 열고 건설을 발주하므로, 밀리 AI가 그 허가를 가로챌 창구가 걷는 시간(먼
// 확장은 수십 초)에서 한 스티어 주기 수준으로 줄어든다.
bool sc2team_TryStageExpansionWorker (int player, string race, point target) {
    unitgroup workers;
    unit currentWorker;
    unit builder = null;
    string workerType;
    int unitIndex;
    fixed currentDistance;
    fixed bestDistance = 100000.0;
    fixed now = TimerGetElapsed(gv_sc2team_CampaignProductionTimer);

    if (race == "Terran") { workerType = "SCV"; }
    else if (race == "Protoss") { workerType = "Probe"; }
    else if (race == "Zerg") { workerType = "Drone"; }
    else { return false; }

    workers = UnitGroup(workerType, player, RegionEntireMap(), UnitFilter(0, 0, 0, 0), 0);
    unitIndex = UnitGroupCount(workers, c_unitCountAlive);
    for (;; unitIndex -= 1) {
        currentWorker = UnitGroupUnitFromEnd(workers, unitIndex);
        if (currentWorker == null) { break; }
        if (UnitGetCustomValue(currentWorker, 18) > now ||
            UnitGetCustomValue(currentWorker, 20) > now ||
            UnitGetCustomValue(currentWorker, 22) > now) {
            continue;
        }
        currentDistance = DistanceBetweenPoints(UnitGetPosition(currentWorker), target);
        if (currentDistance < bestDistance) {
            builder = currentWorker;
            bestDistance = currentDistance;
        }
    }
    if (builder == null) { return false; }
    // §103: 걸어갈 수 없는 확장 지점으로는 파견하지 않는다. 여기서 막지 않으면
    // 일꾼이 150초 스테이징 시한을 통째로 낭비하고 그동안 채취도 멈춘다.
    if (!sc2team_BuilderCanReach(builder, target)) { return false; }
    AISetUnitScriptControlled(builder, true);
    UnitIssueOrder(builder, OrderTargetingPoint(AbilityCommand("move", 0), target), c_orderQueueReplace);
    // 22를 함께 찍어야 sc2team_ReleaseEconomyHarvestWorkers가 도착·만료 시
    // 스크립트 제어를 반드시 돌려준다(제어가 남으면 일꾼 영구 정지가 된다).
    UnitSetCustomValue(builder, 20, now + 150.0);
    UnitSetCustomValue(builder, 22, now + 150.0);
    sc2team_TrackEconomyWorker(player, builder);
    gv_sc2team_ExpansionBuilder[player] = builder;
    return true;
}

bool sc2team_ExpansionBuilderAtTarget (int player, point target) {
    unit builder = gv_sc2team_ExpansionBuilder[player];

    if (builder == null) { return false; }
    if (!UnitIsAlive(builder)) { return false; }
    return DistanceBetweenPoints(UnitGetPosition(builder), target) <= 6.0;
}

// 이동 단계의 취소 판정은 '살아 있는가'만 본다. 명령 수 0은 취소 사유가 될 수
// 없다 — 목표에 도착하면 명령이 비는 것이 정상이고, 도착이야말로 우리가
// 기다리던 상태이기 때문이다. 이 둘을 섞으면 도착하는 순간 확장을 스스로
// 포기한다(실측: 새 타운홀 37 → 12).
bool sc2team_ExpansionBuilderAlive (int player) {
    unit builder = gv_sc2team_ExpansionBuilder[player];

    return builder != null && UnitIsAlive(builder);
}

// §102: 전체 스캔 대신 명단만 훑는다. 커스텀값 21/22가 모두 풀린 일꾼은
// 명단에서 내려 명단이 무한히 자라지 않게 한다.
void sc2team_ReleaseEconomyHarvestWorkers (int player, fixed now) {
    unit currentUnit;
    int unitIndex;

    unitIndex = UnitGroupCount(gv_sc2team_EconomyControlled[player], c_unitCountAll);
    for (;; unitIndex -= 1) {
        currentUnit = UnitGroupUnitFromEnd(gv_sc2team_EconomyControlled[player], unitIndex);
        if (currentUnit == null) { break; }
        if (!UnitIsAlive(currentUnit)) {
            UnitGroupRemove(gv_sc2team_EconomyControlled[player], currentUnit);
            continue;
        }
        if (UnitGetCustomValue(currentUnit, 21) > 0.0 && UnitGetCustomValue(currentUnit, 21) <= now) {
            AISetUnitScriptControlled(currentUnit, false);
            UnitSetCustomValue(currentUnit, 21, 0.0);
        }
        // 확장 건설 명령이 끝났거나 만료되면 SCV/Probe를 밀리 AI에 돌려준다.
        if (UnitGetCustomValue(currentUnit, 22) > 0.0 &&
            (UnitOrderCount(currentUnit) == 0 || UnitGetCustomValue(currentUnit, 22) <= now)) {
            AISetUnitScriptControlled(currentUnit, false);
            UnitSetCustomValue(currentUnit, 20, 0.0);
            UnitSetCustomValue(currentUnit, 22, 0.0);
        }
        if (UnitGetCustomValue(currentUnit, 21) <= 0.0 &&
            UnitGetCustomValue(currentUnit, 22) <= 0.0) {
            UnitGroupRemove(gv_sc2team_EconomyControlled[player], currentUnit);
        }
    }
}

// §102: 값싼 사전 게이트용 캐시 합산. 전부 gv_sc2team_CountAll 배열 읽기라
// UnitGroup을 만들지 않는다.
int sc2team_CountGasStructures (int player) {
    return sc2team_CountAllProduction(player, "Refinery") +
        sc2team_CountAllProduction(player, "RefineryRich") +
        sc2team_CountAllProduction(player, "Assimilator") +
        sc2team_CountAllProduction(player, "AssimilatorRich") +
        sc2team_CountAllProduction(player, "Extractor") +
        sc2team_CountAllProduction(player, "ExtractorRich");
}

int sc2team_CountAnyTownHalls (int player) {
    return sc2team_CountCompletedTownHalls(player, "Terran") +
        sc2team_CountCompletedTownHalls(player, "Protoss") +
        sc2team_CountCompletedTownHalls(player, "Zerg");
}

bool sc2team_TryBuildEconomyGas (int player) {
    unitgroup halls;
    unitgroup nearby;
    unit currentHall;
    unit currentUnit;
    unit builder;
    order buildOrder;
    string workerType = sc2team_EconomyWorkerType(player);
    int hallIndex;
    int unitIndex;
    int hallCount;
    fixed now = TimerGetElapsed(gv_sc2team_CampaignProductionTimer);

    if (workerType == "") { return false; }
    // §102: 이 함수는 45초 이후 매 턴 무조건 전체 스캔 1회 + 타운홀당 반경 10
    // 스캔을 완주했다. 가스를 다 지은 뒤에도 아무것도 하지 않으면서 끝까지
    // 돈다. 값싼 게이트 두 개를 앞에 둔다.
    //
    // (1) 기지당 간헐천 2개가 이 맵의 표준이므로, 가스 건물이 이미 그만큼이면
    //     지을 것이 확실히 없다. 캐시 배열 읽기뿐이라 비용이 없다.
    // (2) 간헐천이 1개뿐인 기지가 섞이면 (1)은 영영 닫히지 않는다. 그래서
    //     "전체 스캔을 했는데 아무것도 못 지었다"면 30초 쉰다. 기지 수가
    //     바뀌면(확장 완성) 즉시 다시 시도하므로 새 기지의 가스는 늦지 않는다.
    hallCount = sc2team_CountAnyTownHalls(player);
    if (sc2team_CountGasStructures(player) >= hallCount * 2) { return false; }
    if (now < gv_sc2team_NextGasAttempt[player] &&
        hallCount == gv_sc2team_GasScanBases[player]) {
        return false;
    }
    if (workerType == "SCV") {
        // Rich refinery: TerranBuild Build8 -> index 7.
    }
    else if (workerType == "Probe") {
        // ProtossBuild Build3 -> index 2; BuildOnAs picks AssimilatorRich.
    }
    else {
        // ZergBuild Build3 -> index 2; P15에서도 검증된 Extractor 명령이다.
    }
    halls = UnitGroup(null, player, RegionEntireMap(), UnitFilter(0, 0, 0, 0), 0);
    hallIndex = UnitGroupCount(halls, c_unitCountAlive);
    for (;; hallIndex -= 1) {
        currentHall = UnitGroupUnitFromEnd(halls, hallIndex);
        if (currentHall == null) { break; }
        if (!sc2team_IsCompletedStructure(currentHall) || !sc2team_IsEconomyTownHall(currentHall)) {
            continue;
        }
        nearby = UnitGroup(null, c_playerAny, RegionCircle(UnitGetPosition(currentHall), 10.0), UnitFilter(0, 0, 0, 0), 0);
        unitIndex = UnitGroupCount(nearby, c_unitCountAlive);
        for (;; unitIndex -= 1) {
            currentUnit = UnitGroupUnitFromEnd(nearby, unitIndex);
            if (currentUnit == null) { break; }
            if (!sc2team_IsEconomyGeyser(currentUnit)) { continue; }
            builder = sc2team_EconomyWorkerAt(player, workerType, UnitGetPosition(currentHall), now);
            if (builder == null) { return false; }
            if (workerType == "SCV") {
                buildOrder = OrderTargetingUnit(AbilityCommand("TerranBuild", 7), currentUnit);
            }
            else if (workerType == "Probe") {
                buildOrder = OrderTargetingUnit(AbilityCommand("ProtossBuild", 2), currentUnit);
            }
            else {
                buildOrder = OrderTargetingUnit(AbilityCommand("ZergBuild", 2), currentUnit);
            }
            if (!UnitOrderIsValid(builder, buildOrder)) { continue; }
            UnitIssueOrder(builder, buildOrder, c_orderQueueReplace);
            UnitSetCustomValue(builder, 20, now + 45.0);
            return true;
        }
    }
    // 전체 스캔이 아무것도 못 지었다. 기지 수가 그대로인 동안은 쉰다.
    gv_sc2team_NextGasAttempt[player] = now + 30.0;
    gv_sc2team_GasScanBases[player] = hallCount;
    return false;
}

// §102: 기존 일꾼의 채취 재배정 경로(강제 채취 함수와 그 하위 두 헬퍼)를
// 삭제했다. 셋 다 호출부가 하나도 없었고, verify()는 오히려 그 경로의 부활을
// 금지한다 — 기존 채취 명령을 다시 배정하면 §89.6의 일꾼 뭉침과 건설 취소가
// 재발한다. 게다가 그 안에는 전체 맵 스캔 2회와 "자원 하나마다 일꾼 전체
// 스캔"이라는 2차식 순회가 들어 있었다. 실행되지는 않았지만 다음 사람이
// 되살릴 위험이 있어 정의째 지운다. 기존 일꾼의 채취 배정은 밀리 AI 몫이라는
// 것이 §94 이후의 규칙이다. 금지 식별자는 verify.cjs에 목록으로 있다.

int sc2team_TryTrainEconomyWorkers (int player, int targetWorkers) {
    unitgroup halls;
    unitgroup larvae;
    unit currentHall;
    unit currentLarva;
    order trainOrder;
    int hallIndex;
    int larvaIndex;
    int currentWorkers = sc2team_CountUnits(player, "SCV") + sc2team_CountUnits(player, "Probe") + sc2team_CountUnits(player, "Drone");
    string hallType;

    if (currentWorkers >= targetWorkers) { return 0; }
    halls = UnitGroup(null, player, RegionEntireMap(), UnitFilter(0, 0, 0, 0), 0);
    hallIndex = UnitGroupCount(halls, c_unitCountAlive);
    for (;; hallIndex -= 1) {
        currentHall = UnitGroupUnitFromEnd(halls, hallIndex);
        if (currentHall == null) { break; }
        if (!sc2team_IsCompletedStructure(currentHall) || !sc2team_IsEconomyTownHall(currentHall)) { continue; }
        hallType = UnitGetType(currentHall);
        if ((hallType == "CommandCenter" || hallType == "OrbitalCommand" || hallType == "PlanetaryFortress") && UnitOrderCount(currentHall) < 2) {
            trainOrder = Order(AbilityCommand("CommandCenterTrain", 0));
            if (UnitOrderIsValid(currentHall, trainOrder)) {
                UnitIssueOrder(currentHall, trainOrder, c_orderQueueAddToEnd);
                currentWorkers += 1;
            }
        }
        else if (hallType == "Nexus" && UnitOrderCount(currentHall) < 2) {
            trainOrder = Order(AbilityCommand("NexusTrain", 0));
            if (UnitOrderIsValid(currentHall, trainOrder)) {
                UnitIssueOrder(currentHall, trainOrder, c_orderQueueAddToEnd);
                currentWorkers += 1;
            }
        }
        else if (hallType == "Hatchery" || hallType == "Lair" || hallType == "Hive") {
            larvae = UnitGroup("Larva", player, RegionCircle(UnitGetPosition(currentHall), 12.0), UnitFilter(0, 0, 0, 0), 0);
            larvaIndex = UnitGroupCount(larvae, c_unitCountAlive);
            for (;; larvaIndex -= 1) {
                currentLarva = UnitGroupUnitFromEnd(larvae, larvaIndex);
                if (currentLarva == null) { break; }
                if (UnitOrderCount(currentLarva) != 0) { continue; }
                trainOrder = Order(AbilityCommand("LarvaTrain", 0));
                if (UnitOrderIsValid(currentLarva, trainOrder)) {
                    UnitIssueOrder(currentLarva, trainOrder, c_orderQueueAddToEnd);
                    currentWorkers += 1;
                    break;
                }
            }
        }
        if (currentWorkers >= targetWorkers) { break; }
    }
    return currentWorkers;
}

void sc2team_RunEconomyGuard (int player) {
    int targetWorkers = sc2team_EconomyWorkerTarget(player);
    fixed now = TimerGetElapsed(gv_sc2team_CampaignProductionTimer);
    // 채취 보정 및 직접 확장 건설을 위해 잠시 제어한 일꾼을 반드시 반환한다.
    sc2team_ReleaseEconomyHarvestWorkers(player, now);
    // §91.5와 같은 오프닝 간섭을 피한다. 초기 멜레 계획이 시작 유닛의
    // 채굴·건설·첫 생산을 등록할 45초를 먼저 보장한 뒤에만 보정한다.
    if (now < 45.0) { return; }
    // 한 틱에 가스 건물 하나만 지어 건설 일꾼 중복 차출을 막는다.
    sc2team_TryBuildEconomyGas(player);
    // 초반 2분 30초는 멜레 AI가 자기 오프닝 생산·건설 순서를 완성하게 둔다.
    // 그 뒤부터는 일꾼이 전멸했거나 멜레 AI가 포화에 실패한 경우도 직접 복구한다.
    if (now >= 150.0) {
        sc2team_TryTrainEconomyWorkers(player, targetWorkers);
    }
    // 기존 일꾼의 채취 명령은 절대 바꾸지 않는다. 새 일꾼 보충만 직접
    // 보정하고, 가스/광물 배치는 멜레 AI의 안정된 기본 로직에 맡긴다.
}

// §87: 틱당 1기 상한 폐지(사용자 지시 — "돈 많고 팩토리 많으면 뭐해"). 종전에는
// 플레이어당·틱당 최대 1기라 공장이 몇 개든 분당 4기가 실질 상한이었다. 이제
// 쿨다운이 풀린 생산 건물 전부에서 구매하며, 지속 속도는 생산 건물별 쿨다운이,
// 순간 지출은 잔고 하한이 막는다. 하한은 매 구매 후 재검사한다(은행이 실시간으로
// 줄기 때문). maxCount는 라바 전용 안전장치다 — 라바는 구매가 소모(UnitRemove)
// 하므로 상한 없이는 한 틱에 라바 풀 전체가 사라져 드론·대군주 생산이 굶는다.
int sc2team_TryPurchaseCampaignUnit (
    int player,
    string producerType,
    string prerequisiteType,
    string unitType,
    int mineralCost,
    int gasCost,
    int supplyCost,
    fixed cooldown,
    int customValueIndex,
    int maxCount
) {
    unitgroup producers;
    unit currentUnit;
    int unitIndex;
    int bought = 0;
    int cacheIndex;
    fixed now;
    point spawnPoint;

    if (sc2team_CountCompletedProduction(player, prerequisiteType) < 1) {
        return 0;
    }
    now = TimerGetElapsed(gv_sc2team_CampaignProductionTimer);
    producers = UnitGroup(producerType, player, RegionEntireMap(), UnitFilter(0, 0, 0, 0), 0);
    unitIndex = UnitGroupCount(producers, c_unitCountAlive);
    for (;; unitIndex -= 1) {
        currentUnit = UnitGroupUnitFromEnd(producers, unitIndex);
        if (currentUnit == null) {
            break;
        }
        if (maxCount > 0 && bought >= maxCount) {
            break;
        }
        // 구매 잔고 하한선(사용자 규칙, §61): 구매 후에도 광물 500 / 가스 400이
        // 남아야 한다. 종전에는 하한이 없어 15초 틱마다 은행을 먼저 걷어갔고,
        // 기본 AI가 기술실·아머리·확장·일꾼에 쓸 저축을 못 해 생산이 말라 죽었다.
        // §91.11: 보급 검사는 SuppliesMade(건물이 실제로 공급하는 현재 상한)와
        // 비교해야 한다. 종전에는 SuppliesLimit(맵 천장 800)과 비교해서, 구매
        // 유닛만 보급 건물과 무관하게 인구 800까지 찍혀 나왔다 — 35게임분 계측에서
        // P1(mech_macro)이 보급고 3개(공급량 54)로 인구 700, 병력 266기를 굴렸고
        // 그중 250기가 골리앗·프레데터였다(정상 유닛은 16기). 캠페인 유닛이 없는
        // 프로토스는 파일런에 정직하게 묶여 165~317에서 멈췄다. 사용자가 관측한
        // "테란 400 vs 프로토스 60~80"의 정체는 종족 밸런스가 아니라 한쪽만
        // 보급 규칙을 우회하고 있던 것이다. CLAUDE.md의 "구매는 실제 자원·보급·
        // 테크 검사를 보존한다"가 원래 의도이며, 구현이 그 의도를 어기고 있었다.
        if (PlayerGetPropertyInt(player, c_playerPropMinerals) < mineralCost + 500 ||
            PlayerGetPropertyInt(player, c_playerPropVespene) < gasCost + 400 ||
            PlayerGetPropertyInt(player, c_playerPropSuppliesUsed) + supplyCost >
                PlayerGetPropertyInt(player, c_playerPropSuppliesMade)) {
            break;
        }
        if (sc2team_IsCompletedStructure(currentUnit) &&
            UnitGetCustomValue(currentUnit, customValueIndex) <= now) {
            PlayerModifyPropertyInt(player, c_playerPropMinerals, c_playerPropOperAdd, -mineralCost);
            PlayerModifyPropertyInt(player, c_playerPropVespene, c_playerPropOperAdd, -gasCost);
            spawnPoint = PointWithOffsetPolar(UnitGetPosition(currentUnit), 3.0, RandomFixed(0.0, 360.0));
            UnitCreate(1, unitType, c_unitCreateIgnorePlacement, player, spawnPoint, RandomFixed(0.0, 360.0));
            // §95: 구매는 UnitCreate로 유닛을 그 자리에서 만든다 — 이 차례
            // 안에서 뒤따르는 비율 판정(2패스)이 낡은 수를 읽지 않도록 캐시를
            // 직접 증분한다. 다른 발주(AIBuild/훈련 명령)는 유닛이 즉시
            // 생기지 않으므로 증분이 필요 없다.
            cacheIndex = sc2team_CountIndex(unitType);
            if (cacheIndex >= 0 && gv_sc2team_CountReady[player]) {
                gv_sc2team_CountAll[player][cacheIndex] += 1;
                gv_sc2team_CountDone[player][cacheIndex] += 1;
            }
            if (producerType == "Larva") {
                UnitRemove(currentUnit);
            }
            else {
                UnitSetCustomValue(currentUnit, customValueIndex, now + cooldown);
            }
            bought += 1;
        }
    }
    return bought;
}

// §87: 직접 훈련 디스패처. 멜레 AI의 AISetStock 단독 의존은 이 프로젝트에서
// 세 번 실측으로 기각됐다(§62 애드온, §71 인프라 — P3는 재건, P4는 영구 방치,
// §82). 병력만 아직 부탁(AISetStock)에 매달려 있었고, 그것이 "돈 많고 공장
// 많은데 병력을 안 뽑는" 사용자 관측의 구조적 원인이다. 유휴 생산 건물에
// 실제 훈련 명령을 직접 내린다 — 비용·보급·테크는 엔진(UnitOrderIsValid)이
// 정상 검사하므로 명령이 공짜 유닛을 만들지 않는다.
//
// 규칙:
// - c_orderQueueAddToEnd만 쓴다. 멜레 AI가 걸어둔 대기열을 절대 교체하지 않는다.
// - maxQueue(건물 2, 라바 1)까지만 채운다. 2면 반응로가 병렬 2기를 돌리고
//   일반 건물은 틱 사이(15초 < 대부분의 생산 시간) 유휴가 없다.
// - 잔고 하한(광물 cost+500 / 가스 cost+400 — §61 구매·§63 연구와 동일)을
//   매 발주 후 재검사한다. 가스 0짜리 유닛은 가스 하한을 보지 않는다(광물
//   전용 유닛이 가스 은행에 볼모로 잡히면 안 된다).
// - reserveAddonAbil이 비어 있지 않으면, 애드온을 아직 달 수 있는 생산 건물
//   1개를 틱마다 유휴로 남긴다. 이게 없으면 훈련 대기열이 모든 건물을 항상
//   점유해 §82 애드온 발주(유휴 건물 필요)가 영구히 굶는다.
// - leaveIdle(라바 3)만큼 생산자를 남긴다. 라바를 전부 쓰면 멜레 AI의 드론·
//   대군주 생산이 굶는다(§86에서 P15가 겪은 자멸 구조와 같은 이유).
int sc2team_TryTrainMeleeUnit (
    int player,
    string producerType,
    string abilLink,
    int commandIndex,
    int mineralCost,
    int gasCost,
    string reserveAddonAbil,
    int leaveIdle,
    int maxQueue
) {
    unitgroup producers;
    unit currentUnit;
    int unitIndex;
    int remaining;
    int issued = 0;
    bool addonReserved = false;
    order trainOrder;
    order addonOrder;

    trainOrder = Order(AbilityCommand(abilLink, commandIndex));
    producers = sc2team_ProducerGroup(player, producerType);
    remaining = UnitGroupCount(producers, c_unitCountAlive);
    unitIndex = remaining;
    for (;; unitIndex -= 1) {
        currentUnit = UnitGroupUnitFromEnd(producers, unitIndex);
        if (currentUnit == null) {
            break;
        }
        if (remaining <= leaveIdle) {
            break;
        }
        remaining -= 1;
        if (!sc2team_IsCompletedStructure(currentUnit)) {
            continue;
        }
        if (reserveAddonAbil != "" && !addonReserved && UnitOrderCount(currentUnit) == 0) {
            addonOrder = OrderTargetingPoint(
                AbilityCommand(reserveAddonAbil, 0),
                UnitGetPosition(currentUnit)
            );
            if (UnitOrderIsValid(currentUnit, addonOrder)) {
                addonReserved = true;
                continue;
            }
        }
        if (UnitOrderCount(currentUnit) >= maxQueue) {
            continue;
        }
        if (PlayerGetPropertyInt(player, c_playerPropMinerals) < mineralCost + 500 ||
            (gasCost > 0 &&
             PlayerGetPropertyInt(player, c_playerPropVespene) < gasCost + 400)) {
            break;
        }
        if (!UnitOrderIsValid(currentUnit, trainOrder)) {
            continue;
        }
        UnitIssueOrder(currentUnit, trainOrder, c_orderQueueAddToEnd);
        issued += 1;
    }
    return issued;
}

// §87: 차원 관문 훈련. 관문이 WarpGate로 변태하면 CAbilTrain이 아니라 소환
// 지점을 요구하는 별도 능력을 쓰므로 일반 훈련 헬퍼로는 명령이 나가지 않는다.
// 각 차원 관문 주변(동력장 안일 가능성이 높은 자기 위치 반경 3~7)에서 지점을
// 몇 번 시도하고, 배치·동력·비용·쿨다운 검증은 전부 엔진에 맡긴다.
int sc2team_TryWarpTrain (
    int player,
    string abilLink,
    int commandIndex,
    int mineralCost,
    int gasCost
) {
    unitgroup gates;
    unit currentUnit;
    int unitIndex;
    int attempt;
    int issued = 0;
    point warpPoint;
    order warpOrder;

    gates = sc2team_ProducerGroup(player, "WarpGate");
    unitIndex = UnitGroupCount(gates, c_unitCountAlive);
    for (;; unitIndex -= 1) {
        currentUnit = UnitGroupUnitFromEnd(gates, unitIndex);
        if (currentUnit == null) {
            break;
        }
        if (!sc2team_IsCompletedStructure(currentUnit) || UnitOrderCount(currentUnit) != 0) {
            continue;
        }
        if (PlayerGetPropertyInt(player, c_playerPropMinerals) < mineralCost + 500 ||
            (gasCost > 0 &&
             PlayerGetPropertyInt(player, c_playerPropVespene) < gasCost + 400)) {
            break;
        }
        for (attempt = 0; attempt < 4; attempt += 1) {
            warpPoint = PointWithOffsetPolar(
                UnitGetPosition(currentUnit), RandomFixed(3.0, 7.0), RandomFixed(0.0, 360.0)
            );
            warpOrder = OrderTargetingPoint(AbilityCommand(abilLink, commandIndex), warpPoint);
            if (UnitOrderIsValid(currentUnit, warpOrder)) {
                UnitIssueOrder(currentUnit, warpOrder, c_orderQueueAddToEnd);
                issued += 1;
                break;
            }
        }
    }
    return issued;
}

// §87: 기존 유닛 변태(저글링→맹독충, 바퀴→궤멸충, 히드라→가시지옥). 명령이
// 없는(유휴) 유닛만 변태시켜 전투·행군 중인 유닛을 방해하지 않는다. 45초
// 공격 브로드캐스트가 명령을 걸어둔 유닛은 자연히 건너뛴다.
int sc2team_TryMorphMeleeUnit (
    int player,
    string fromType,
    string abilLink,
    int commandIndex,
    int mineralCost,
    int gasCost,
    int maxCount
) {
    unitgroup sources;
    unit currentUnit;
    int unitIndex;
    int issued = 0;
    order morphOrder;

    morphOrder = Order(AbilityCommand(abilLink, commandIndex));
    sources = UnitGroup(fromType, player, RegionEntireMap(), UnitFilter(0, 0, 0, 0), 0);
    unitIndex = UnitGroupCount(sources, c_unitCountAlive);
    for (;; unitIndex -= 1) {
        currentUnit = UnitGroupUnitFromEnd(sources, unitIndex);
        if (currentUnit == null) {
            break;
        }
        if (issued >= maxCount) {
            break;
        }
        if (UnitOrderCount(currentUnit) != 0) {
            continue;
        }
        if (PlayerGetPropertyInt(player, c_playerPropMinerals) < mineralCost + 500 ||
            (gasCost > 0 &&
             PlayerGetPropertyInt(player, c_playerPropVespene) < gasCost + 400)) {
            break;
        }
        if (!UnitOrderIsValid(currentUnit, morphOrder)) {
            continue;
        }
        UnitIssueOrder(currentUnit, morphOrder, c_orderQueueAddToEnd);
        issued += 1;
    }
    return issued;
}

// §88: 보급 막힘 판정. §87 디스패처가 인구 최대까지 뽑는 속도를 멜레 AI의
// 보급 건물 건설이 못 따라가는 실관측(사용자: 테란 보급고 정체, 프로토스
// 파일런 미건설) 대응. 오프닝(사용 32 미만)과 800 상한 도달 시에는 꺼진다.
bool sc2team_SupplyBlocked (int player) {
    int used = PlayerGetPropertyInt(player, c_playerPropSuppliesUsed);
    int made = PlayerGetPropertyInt(player, c_playerPropSuppliesMade);
    int ceiling = PlayerGetPropertyInt(player, c_playerPropSuppliesLimit);

    // §91.10 — 이 함수는 §88 출시 이후 **한 번도 참을 돌려준 적이 없다.**
    //
    // 원래 식은 "사용량 >= 32 이고, 천장값 < 800 이고, (천장값 − 사용량) < 24"
    // 였는데, c_playerPropSuppliesLimit 은 현재 공급량이 아니라 맵이 설정한
    // **천장**(이 맵은 CRace FoodCeiling = 800)이다. 그래서 둘째 항은 항상
    // 거짓이고 셋째 항의 여유값도 항상 800 근처라, 두 항이 동시에 영구
    // 거짓이었다. 결과로
    // 파일런 선제 건설·보급고 선제 건설·궤도 사령부 보급 투하가 전부 죽어 있었다
    // — 사용자가 보고한 "프로토스가 보급 한도에서 파일런을 보충하지 않는다"가
    // 정확히 이것이다.
    //
    // 실증(추론이 아니라 실험으로 좁혔다): 게이트를 return true 로 우회하니
    // 10분에 파일런이 P10 3→27, P9 2→21, P11 3→19 로 폭증하고 테란 보급고도
    // 10→16 으로 늘었다. 이어서 게이트를 그 둘째 항 하나만 남기니
    // 다시 2~3 개로 정지 — 거짓인 항이 그 천장 비교임이 단독으로 확정됐다.
    //
    // 올바른 짝은 Blizzard 자신의 용법이다(starcoop LibCOMU.galaxy:12962 —
    // SuppliesUsed > SuppliesMade 가 보급 막힘). Made = 건물이 실제로 공급하는
    // 현재 상한, Limit = 그 상한이 더 오를 수 없는 천장.
    //
    // made < ceiling 은 최대 보급에서 무한 발주를 막는 원래 의도를 유지한다.
    return used >= 32 && made < ceiling && made - used < 32;
}

// §88: 보급 구조물(보급고/파일런) 선제 건설. §83 게이트: 완성 실적이 1개
// 이상일 때만 발주한다(래치 겸 선행조건 충족 증거 — 오프닝은 멜레 AI 소유).
// 동시 건설 2개 상한 — 매 틱 재평가되므로 상한이 없으면 보급이 풀릴 때까지
// 무한 중복 발주가 된다.
void sc2team_TrySupplyStructure (int player, string structureType) {
    int building;

    if (!sc2team_SupplyBlocked(player)) {
        return;
    }
    if (sc2team_CountCompletedProduction(player, structureType) < 1) {
        return;
    }
    // §91: 동시 건설 상한 2 → 4. 보급 건물 하나가 주는 여유(+8)는 §87
    // 디스패처의 한 틱 생산량보다 작아서 2개로는 따라잡지 못한다. 매 틱
    // 재평가되므로 상한 자체는 남겨둔다(없으면 무한 중복 발주).
    building = sc2team_CountAllProduction(player, structureType) -
        sc2team_CountCompletedProduction(player, structureType);
    if (building >= 4) {
        return;
    }
    AIBuild(player, c_makePriorityTown, AIGetMainTown(player), structureType, 1, c_nearChokePoint);
}

// §91.9 프로토스 파일런 직접 건설. §88의 AIBuild "부탁"은 프로토스에서 신뢰할
// 수 없다 — 16게임분 계측에서 테란 보급고는 1 → 10~14로 꾸준히 늘어난 반면
// 파일런은 6슬롯 중 3슬롯이 각각 14분·7분·6분간 완전히 정지했다(P9는 2개에서
// 14분 내내 그대로, 그 사이 관문은 7개까지 늘었다). 애드온(§62)·인프라(§71)·
// 연구(§63)·병력(§87)과 같은 결론이다: 재고 요청과 AIBuild는 무시될 수 있고
// 직접 명령만 보장 경로다. AIBuild는 그대로 둔다(가끔 통하고 해롭지 않다).
//
// 사용자 지시(§91.8): "인구 여유가 0이어도 지속적으로 파일런을 올린다면 괜찮아."
// 즉 목표는 여유 확보가 아니라 **정지하지 않는 것**이다.
//
// 프로토스 건설은 탐사정이 소환만 걸고 즉시 자유로워지므로 일꾼을 오래 묶지
// 않는다. 배치가 무효인 지점은 오류 없이 조용히 소멸하므로(§89.5) 발주 전에
// 반드시 UnitOrderIsValid로 후보를 검사한다 — P15 매크로 해처리와 같은 패턴.
// ProtossBuild 인덱스 1 = 파일런. BuildN → 커맨드 N-1 규약은 엔진 검증된 저그
// ZergBuild 값 8개(8=InfestationPit, 7=UltraliskCavern 포함)로 재현 확인했고,
// 파일런 슬롯을 덮어쓰는 레이어는 없다. 파일런은 InfoArray에 Requirements도
// ValidatorArray도 없어 테크 게이트가 아예 없다.
void sc2team_TryBuildPylonDirect (int player) {
    unitgroup halls;
    unitgroup probes;
    unit anchor;
    unit builder;
    point anchorPoint;
    point candidate;
    order buildOrder;
    int hallIndex;
    int hallsTried = 0;
    int probeIndex;
    int attempt;
    fixed now;

    if (!sc2team_SupplyBlocked(player)) {
        return;
    }
    if (PlayerGetPropertyInt(player, c_playerPropMinerals) < 100) {
        return;
    }
    // 동시 건설 상한. 매 틱 재평가되므로 상한이 없으면 무한 중복 발주가 된다.
    if (sc2team_CountAllProduction(player, "Pylon") -
        sc2team_CountCompletedProduction(player, "Pylon") >= 4) {
        return;
    }
    // 넥서스는 최대 3곳만 본다(트리거 연산 예산 — §89.6: 예산을 넘기면 스레드가
    // 중간에 죽어 이 틱의 나머지 경제 로직까지 통째로 사라진다).
    halls = UnitGroup("Nexus", player, RegionEntireMap(), UnitFilter(0, 0, 0, 0), 0);
    hallIndex = UnitGroupCount(halls, c_unitCountAlive);
    for (;; hallIndex -= 1) {
        anchor = UnitGroupUnitFromEnd(halls, hallIndex);
        if (anchor == null) {
            break;
        }
        if (hallsTried >= 3) {
            break;
        }
        if (!sc2team_IsCompletedStructure(anchor)) {
            continue;
        }
        hallsTried += 1;
        anchorPoint = UnitGetPosition(anchor);
        // §89.6 함정: 매 틱 같은 일꾼의 명령을 교체하면, 건설 지점까지 걷는 데
        // 틱(15초)보다 오래 걸리는 순간 영원히 걷기만 한다 — 건물이 안 생기니
        // in-flight도 0이라 같은 조건이 매 틱 재발한다. 실측에서 P10·P11이
        // 여유 0인 채로 파일런 3·4개에 9~10분간 묶인 것이 이것이다(가까운
        // 지점을 찾은 P9만 2 → 11로 늘었다). 발주한 탐사정에 만료 시각을
        // 찍어 두고(커스텀 값 18) 만료 전에는 다시 고르지 않는다.
        now = TimerGetElapsed(gv_sc2team_CampaignProductionTimer);
        probes = UnitGroup("Probe", player, RegionCircle(anchorPoint, 14.0), UnitFilter(0, 0, 0, 0), 0);
        probeIndex = UnitGroupCount(probes, c_unitCountAlive);
        for (;; probeIndex -= 1) {
            builder = UnitGroupUnitFromEnd(probes, probeIndex);
            if (builder == null) {
                break;
            }
            // §105.8(감사 C2): cv18만 보던 것을 자매 함수들과 같은 18/20/22
            // 3종 검사로 맞춘다. 스티어 순서가 가스 → 확장 스테이징 → 파일런
            // 이라, 같은 틱에 확장 이동(cv20/22)이나 간헐천 건설(cv20) 명령을
            // 받은 탐사정을 파일런이 c_orderQueueReplace로 덮어써 확장이 최대
            // 195초 정지했다. 반드시 continue — break면 그 넥서스를 통째로
            // 건너뛰어 §91.9가 고친 증상이 재발한다.
            if (UnitGetCustomValue(builder, 18) > now ||
                UnitGetCustomValue(builder, 20) > now ||
                UnitGetCustomValue(builder, 22) > now) {
                continue;
            }
            // 반경 7 / 9.5 / 12 / 14.5 / 17 × 각도 73도 간격으로 10개 후보.
            // 성숙한 본진은 관문·연결체로 꽉 차 있어 좁은 링만 보면 전부 무효다.
            attempt = 0;
            for (; attempt < 10; attempt += 1) {
                candidate = PointWithOffsetPolar(
                    anchorPoint,
                    7.0 + IntToFixed(attempt % 5) * 2.5,
                    IntToFixed(attempt) * 73.0
                );
                buildOrder = OrderTargetingPoint(AbilityCommand("ProtossBuild", 1), candidate);
                // §103: 배치 유효 + **도달 가능**이어야 한다. 종전에는 앞의
                // 검사만 해서 절벽 위 후보에도 명령이 나갔다.
                if (UnitOrderIsValid(builder, buildOrder) &&
                    sc2team_BuilderCanReach(builder, candidate)) {
                    // 건설 명령이 채취 명령을 지우므로, 착공 후 유휴가 되면 멜레
                    // AI에게 돌려주도록 sc2team_ReleaseEconomyHarvestWorkers(cv22)
                    // 추적에 등록한다. 등록 없이는 되돌아갈 채취 명령이 없어
                    // 탐사정이 그 자리에 영구히 서 있는다(사용자 실관측).
                    AISetUnitScriptControlled(builder, true);
                    UnitIssueOrder(builder, buildOrder, c_orderQueueReplace);
                    UnitSetCustomValue(builder, 18, now + 45.0);
                    UnitSetCustomValue(builder, 22, now + 45.0);
                    sc2team_TrackEconomyWorker(player, builder);
                    return;
                }
            }
            // 이 탐사정으로 유효 지점을 못 찾았으면 지형 문제다 — 같은 넥서스에서
            // 다른 탐사정을 시도해도 같은 결과이므로 다음 넥서스로 넘어간다.
            break;
        }
    }
}

// §88: SupplyDrop 미적용(버프 없음) 완성 보급고 하나를 찾는다.
unit sc2team_FindSupplyDropTarget (int player, string depotType) {
    unitgroup depots;
    unit currentUnit;
    int unitIndex;

    depots = UnitGroup(depotType, player, RegionEntireMap(), UnitFilter(0, 0, 0, 0), 0);
    unitIndex = UnitGroupCount(depots, c_unitCountAlive);
    for (;; unitIndex -= 1) {
        currentUnit = UnitGroupUnitFromEnd(depots, unitIndex);
        if (currentUnit == null) {
            break;
        }
        if (sc2team_IsCompletedStructure(currentUnit) &&
            UnitBehaviorCount(currentUnit, "SupplyDrop") == 0) {
            return currentUnit;
        }
    }
    return null;
}

// §88: 궤도 사령부 '추가 보급품 투하'(SupplyDrop 능력, Execute 인덱스 0,
// 에너지 50, 완성 보급고 대상 — 영구 +8, 기본 멜레에 있는 그 기술). 보급고당
// 1회만 의미가 있으므로 버프 없는 보급고를 찾아 틱당 1회 시전한다.
//
// §104 에너지 예비선 100 (사용자 지시: "궤도 사령부도 100 이상일 때만 사용").
// 종전 주석은 "보급 여유가 있으면 호출되지 않으니 지게로봇 에너지를 평시에
// 빼앗지 않는다"고 적었지만, 그 전제가 실제 동작과 어긋난다 — §87 디스패처는
// 인구 상한까지 계속 생산하도록 설계돼 있어 사실상 "평시"가 없고, 보급 막힘이
// 거의 상시 참이다. 궤도 에너지 재생은 초당 약 0.56이라 12초 틱마다 6.75만
// 차는데, 50이 모이는 순간 이 명령이 가져가므로 **에너지가 50 위로 올라갈 틈이
// 아예 없었다.** 결과로 밀레 AI는 스캐너 탐색(50)도 지게로봇(50)도 영영 쓰지
// 못한다 — 사용자 실관측 "스캔을 안 쓴다"가 이것이다.
//
// 100을 남기는 것이 아니라 100 **이상일 때만** 쓴다. 50을 쓰고도 50이 남으므로
// 밀레 AI 몫(스캔/지게로봇)이 항상 확보된다. 이것이 "우리 코드는 보조"라는
// 원칙의 구체형이다 — 우리가 먼저 집어가지 않는다.
void sc2team_TryCalldownSupplies (int player) {
    unitgroup orbitals;
    unit currentUnit;
    unit target;
    int unitIndex;
    order dropOrder;

    if (!sc2team_SupplyBlocked(player)) {
        return;
    }
    target = sc2team_FindSupplyDropTarget(player, "SupplyDepot");
    if (target == null) {
        target = sc2team_FindSupplyDropTarget(player, "SupplyDepotLowered");
    }
    if (target == null) {
        return;
    }
    dropOrder = OrderTargetingUnit(AbilityCommand("SupplyDrop", 0), target);
    orbitals = UnitGroup("OrbitalCommand", player, RegionEntireMap(), UnitFilter(0, 0, 0, 0), 0);
    unitIndex = UnitGroupCount(orbitals, c_unitCountAlive);
    for (;; unitIndex -= 1) {
        currentUnit = UnitGroupUnitFromEnd(orbitals, unitIndex);
        if (currentUnit == null) {
            break;
        }
        if (sc2team_IsCompletedStructure(currentUnit) &&
            UnitGetPropertyFixed(currentUnit, c_unitPropEnergy, c_unitPropCurrent) >= 100.0 &&
            UnitOrderIsValid(currentUnit, dropOrder)) {
            UnitIssueOrder(currentUnit, dropOrder, c_orderQueueAddToEnd);
            return;
        }
    }
}

bool sc2team_TryPurchaseRaptorEvolution (int player) {
    if (TechTreeUpgradeCount(player, "SC2TeamRaptorEvolution", c_techCountQueuedOrBetter) >= 1) {
        return false;
    }
    if (sc2team_CountCompletedProduction(player, "SpawningPool") < 1 ||
        (sc2team_CountCompletedProduction(player, "Lair") < 1 &&
         sc2team_CountCompletedProduction(player, "Hive") < 1) ||
        PlayerGetPropertyInt(player, c_playerPropMinerals) < 100 ||
        PlayerGetPropertyInt(player, c_playerPropVespene) < 100) {
        return false;
    }
    PlayerModifyPropertyInt(player, c_playerPropMinerals, c_playerPropOperAdd, -100);
    PlayerModifyPropertyInt(player, c_playerPropVespene, c_playerPropOperAdd, -100);
    TechTreeUpgradeAddLevel(player, "SC2TeamRaptorEvolution", 1);
    return true;
}

// §69: 요구 구조물-테크 게이트 헬퍼. 완성된 요구 구조물이 1개 이상 있으면 참.
// "Lair"는 Hive로 변태하면 사라지므로 Hive도 Lair 요구를 충족한 것으로 본다.
bool sc2team_HasResearchTech (int player, string prereqStructure) {
    if (sc2team_CountCompletedProduction(player, prereqStructure) >= 1) {
        return true;
    }
    if (prereqStructure == "Lair" &&
        sc2team_CountCompletedProduction(player, "Hive") >= 1) {
        return true;
    }
    return false;
}

// §63: 유휴 연구 구조물 하나에 연구 명령을 직접 내린다. 멜레 AI에 부탁하는
// AISetStock은 기술실 요청이 무시된 전례(§62)가 있어 쓰지 않는다. 명령이므로
// 비용·연구 시간·요구조건은 엔진이 정상 처리한다. 이미 대기열 이상으로 잡힌
// 업그레이드와 선행 레벨 미완료는 건너뛰어, 요구조건 미충족 명령이 매 틱
// 연구 슬롯을 헛소모하지 않게 한다.
// §69: prerequisiteStructure(비면 무시)가 있으면 완성 요구 구조물이 없을 때
// false를 돌려 명령 자체를 내지 않는다. 명령을 냈다가 요구조건 미충족으로
// 거부돼도 이 함수는 true를 돌려 뒤 엔트리를 굶기므로(틱당 1건), 군락/번식지
// 요구 업그레이드는 게이트로 미리 막아야 한다.
bool sc2team_TryResearchUpgrade (
    int player,
    string structureType,
    string abilLink,
    int commandIndex,
    string upgradeType,
    string prerequisiteUpgrade,
    string prerequisiteStructure,
    int mineralCost,
    int gasCost
) {
    unitgroup structures;
    unit currentUnit;
    int unitIndex;

    if (TechTreeUpgradeCount(player, upgradeType, c_techCountQueuedOrBetter) >= 1) {
        return false;
    }
    if (prerequisiteUpgrade != "" &&
        TechTreeUpgradeCount(player, prerequisiteUpgrade, c_techCountCompleteOnly) < 1) {
        return false;
    }
    if (prerequisiteStructure != "" &&
        !sc2team_HasResearchTech(player, prerequisiteStructure)) {
        return false;
    }
    // 연구 잔고 하한선. §91까지는 구매와 같은 +500/+400이었는데, 그 값이면
    // 연구는 영원히 발주되지 않는다: 지출 순서가 훈련 → 구매 → 연구인데 훈련
    // 디스패처가 매 틱 자기 하한(불곰 가스 25+400=425)까지 은행을 빨아먹고,
    // 연구 하한은 그보다 높다(1레벨 100+400=500). 즉 연구 차례에는 항상
    // 하한 미달이다 — 16분 계측에서 커스텀 AI 테란 5슬롯의 무/방이 0~1레벨,
    // bio_tank(P2)는 공학연구소를 2분에 지어놓고 16분까지 보병 업그레이드
    // 0레벨이었다(순수 멜레 AI 대조군 P4가 오히려 기계공 1레벨).
    //
    // §61의 은행 고갈은 "상한 없는 다중 구매"가 원인이었고, 연구는 플레이어당
    // 틱당 1건이 하드 상한이라 같은 위험이 없다. 그래서 예비금만 줄인다.
    if (PlayerGetPropertyInt(player, c_playerPropMinerals) < mineralCost + 150 ||
        PlayerGetPropertyInt(player, c_playerPropVespene) < gasCost + 100) {
        return false;
    }
    structures = sc2team_ProducerGroup(player, structureType);
    unitIndex = UnitGroupCount(structures, c_unitCountAlive);
    for (;; unitIndex -= 1) {
        currentUnit = UnitGroupUnitFromEnd(structures, unitIndex);
        if (currentUnit == null) {
            break;
        }
        if (sc2team_IsCompletedStructure(currentUnit) && UnitOrderCount(currentUnit) == 0) {
            UnitIssueOrder(currentUnit, Order(AbilityCommand(abilLink, commandIndex)), c_orderQueueReplace);
            return true;
        }
    }
    return false;
}

void sc2team_ApplyAirProductionCaps () {
${capLines.join("\n")}
}

// §97: AIExpand가 요청 중심에서 비꾸어 지어도 해당 자원기지를
// 점유한 것으로 인식한다. 반경 숫자 하나로 판정하면 가까운 별개
// 멀티를 막거나 비꺐 타운홀을 놓친다. 대신 주변 타운홀을 전체
// 후보의 Voronoi 영역(가장 가까운 후보 하나)에 귀속시킨다.
// §102: 후보 개폐를 한 번의 타운홀 스캔으로 전부 미리 계산한다.
//
// 종전 구조: sc2team_ExpansionCandidateOpen이 후보 하나마다 반경 45짜리
// c_playerAny UnitGroup을 새로 만들고, 그 안에서 찾은 타운홀마다 57개 후보와
// 거리를 비교했다. sc2team_NextExpansionPointP<N>은 열린 후보가 나올 때까지
// 이걸 최대 44번 연달아 호출하므로, 확장 탐색이 도는 턴 하나에 UnitGroup
// 생성 44개가 한 프레임에 몰렸다(§102 감사: 그 턴 총 92개 중 45개 = 49%).
// 확장 재시도 쿨다운이 45~120초이고 커스텀 슬롯이 12개라, 통계적으로 4~10초에
// 한 번씩 이 스파이크가 온다 — 사용자가 보고한 "3~5초마다 0.5~1초 정지"의
// 주기와 일치한다.
//
// 판정 결과는 종전과 정확히 같다. 종전 규칙은 후보 C에 대해 "반경 45 안의
// 타운홀 H 중 nearest(H) == C 이거나 dist(H,C) < 10 이면 C는 닫힘"이었다.
// nearest(H) == C 인 경우 dist(H,C)가 곧 nearestDistance이므로
// nearestDistance <= 45.0 검사가 종전의 반경 조건과 동치이고, dist < 10 규칙은
// 10 < 45라 반경 조건에 항상 포함된다. 그래서 타운홀 쪽에서 한 번에 계산해도
// 같은 집합이 닫힌다.
void sc2team_RefreshExpansionClosed () {
    unitgroup halls;
    unit townHall;
    point hallPoint;
    int unitIndex;
    int testIndex;
    int nearestIndex;
    fixed testDistance;
    fixed nearestDistance;

    for (testIndex = 1; testIndex <= ${expansionLayoutPoints.length}; testIndex += 1) {
        gv_sc2team_ExpansionClosed[testIndex] = false;
    }
    halls = UnitGroup(null, c_playerAny, RegionEntireMap(), UnitFilter(0, 0, 0, 0), 0);
    unitIndex = UnitGroupCount(halls, c_unitCountAlive);
    for (;; unitIndex -= 1) {
        townHall = UnitGroupUnitFromEnd(halls, unitIndex);
        if (townHall == null) { break; }
        if (!sc2team_IsEconomyTownHall(townHall)) { continue; }
        hallPoint = UnitGetPosition(townHall);
        nearestIndex = 0;
        nearestDistance = 100000.0;
        for (testIndex = 1; testIndex <= ${expansionLayoutPoints.length}; testIndex += 1) {
            testDistance = DistanceBetweenPoints(
                hallPoint, gv_sc2team_ExpansionPoints[testIndex]
            );
            if (testDistance < nearestDistance) {
                nearestDistance = testDistance;
                nearestIndex = testIndex;
            }
            // 어떤 후보에도 귀속되지 않은 채 밀착한 타운홀도 그 후보를 막는다.
            // 타운홀 5x5 두 채는 약 5 거리면 공존하고, 후보 사이 최소 간격은
            // 13.15(그다음 15.03)이므로 10.0은 정당한 후보를 하나도 닫지 않는다.
            if (testDistance < 10.0) {
                gv_sc2team_ExpansionClosed[testIndex] = true;
            }
        }
        // 귀속(Voronoi)으로 닫는다. 이미 다른 후보의 영역에 속한 타운홀은 이
        // 후보를 막을 이유가 없다 — 종전에 거리 검사가 앞에 있던 시절에는
        // 후보 34처럼 시작 타운홀에서 13.15 떨어진 정당한 별개 자원기지가
        // 영구히 닫혔다(P12의 최근접 확장이 그 자리라, 20분 계측에서 P12는
        // 원거리 확장을 한 번도 못 하고 밀리 AI가 본진 앞에 넥서스만 4채 쌓았다).
        if (nearestIndex > 0 && nearestDistance <= 45.0) {
            gv_sc2team_ExpansionClosed[nearestIndex] = true;
        }
    }
}

bool sc2team_ExpansionCandidateOpen (int requestedIndex) {
    return !gv_sc2team_ExpansionClosed[requestedIndex];
}

bool sc2team_ExpansionCandidateOwnedByPlayer (int requestedIndex, int player) {
    unitgroup nearby;
    unit townHall;
    int unitIndex;
    point target;

    if (requestedIndex <= 0) { return false; }
    target = gv_sc2team_ExpansionPoints[requestedIndex];
    nearby = UnitGroup(null, player, RegionCircle(target, 8.0), UnitFilter(0, 0, 0, 0), 0);
    unitIndex = UnitGroupCount(nearby, c_unitCountAlive);
    for (;; unitIndex -= 1) {
        townHall = UnitGroupUnitFromEnd(nearby, unitIndex);
        if (townHall == null) { break; }
        if (sc2team_IsEconomyTownHall(townHall)) { return true; }
    }
    return false;
}

${expansionPointFunctions}

${steerFunctions}

// §95: 라운드로빈 스케줄러. 종전에는 이 함수 하나가 커스텀 AI 전원의 경제·
// 생산·구매·연구를 한 번에 실행했다 — 릴리스 설정(12명)에서 한 호출에 무조건
// 전체 맵 스캔 365회(조건부까지 상한 1,121회), 유닛 수백 기 × 수백 회 순회가
// SC2 시뮬레이션 스레드를 통째로 잡아 사용자가 관측한 주기적 화면 정지를
// 만들었다. 이제 한 번 발화에 플레이어 하나만 처리한다.
//
// 주기는 ${steerPeriod}s × ${steerCount}명 = 한 바퀴 ${STEER_CYCLE_SECONDS}게임초다. 인원수로 나누는 이유는
// 슬롯 수가 달라져도 플레이어당 처리 간격을 고정하기 위해서다(고정 1초로 두면
// 2인 게임에서 플레이어당 빈도가 종전의 7.5배가 되어 생산·연구 속도가 설정에
// 따라 달라진다). 종전 15초 → ${STEER_CYCLE_SECONDS}초로 오히려 조금 잦아졌다.
bool sc2team_ProductionSteering_Func (bool testConds, bool runActions) {
    if (!runActions) {
        return true;
    }
    gv_sc2team_SteerCursor += 1;
    if (gv_sc2team_SteerCursor > ${steerCount}) {
        gv_sc2team_SteerCursor = 1;
    }
${steerDispatch}
    return true;
}

void sc2team_InitializeProductionRules () {
    int initPlayer;

    gv_sc2team_CampaignProductionTimer = TimerCreate();
    TimerStart(gv_sc2team_CampaignProductionTimer, 1000000.0, false, c_timeGame);
    // §102: 경제 일꾼 제어 명단 초기화(§97 전투 명단과 같은 방식).
    for (initPlayer = 1; initPlayer <= 15; initPlayer += 1) {
        gv_sc2team_EconomyControlled[initPlayer] = UnitGroupEmpty();
    }
    for (initPlayer = 0; initPlayer < 4; initPlayer += 1) {
        gv_sc2team_ProducerCacheType[initPlayer] = "";
        gv_sc2team_ProducerCachePlayer[initPlayer] = 0;
    }
    gv_sc2team_ProducerCacheNext = 0;
    sc2team_ApplyAirProductionCaps();
    // 개시 1회는 전원 실행한다(종전과 같음). 게임 시작 시점에는 플레이어당
    // 유닛이 10기 남짓이라 비용이 무시할 수준이고, 목표 재고·생산 상한이
    // 첫 바퀴를 기다리지 않고 곧바로 걸린다.
    gv_sc2team_SteerCursor = 0;
${expansionPointInitializers}
${expansionInitialState}
${steerInitialPass}
    gt_sc2team_ProductionSteering = TriggerCreate("sc2team_ProductionSteering_Func");
    TriggerAddEventTimePeriodic(gt_sc2team_ProductionSteering, ${steerPeriod}, c_timeGame);
}

`;
}

module.exports = {
  makeResearchLines,
  makeTerranAddonLines,
  makeProductionRules,
};
