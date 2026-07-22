// 런타임 지원 Galaxy 생성: 팀 설정, 고정 시작 지점, P15 야생 저그, 그리고
// 최종 스크립트 조립. 유닛 제어(브리지·수비·통제)는 unit_control.cjs, 생산/
// 경제 규칙은 production.cjs가 만든 문자열을 여기서 조립 순서대로 잇는다.
//
// 조립 순서는 브리지 → 생산 순을 유지한다. §60의 "경제 블록이
// sc2team_IssueSupport를 재사용한다"는 서술은 낡은 것으로 확인됐다(2026-07-22
// 감사: 호출부는 브리지 자신뿐) — 지금 순서를 지키는 이유는 재사용이 아니라
// 산출물 바이트 동일성이다.

const { fail, readGalaxyTemplate } = require("./util.cjs");
const { makeProductionRules } = require("./production.cjs");
const { makeUnitControlBlock } = require("./unit_control.cjs");

function makeRuntimeSupport(activeSlots, humanRuntimeId, fullVision, strategyBridge, bridgeProbe, meleeOnly, allowSupportAir, campaignUnitsPilot, campaignUnitsProbeDamage, researchProbe, protossFaction = "Standard", wildZergActive = true, unitControlActive = false) {
  const vision = fullVision
    ? `\n    VisRevealArea(${humanRuntimeId}, RegionEntireMap(), 0.0, false);`
    : "";
  const alliances = [];
  for (let first = 1; first <= activeSlots.length; first += 1) {
    for (let second = first + 1; second <= activeSlots.length; second += 1) {
      const setting = activeSlots[first - 1].team === activeSlots[second - 1].team
        ? "libNtve_ge_AllianceSetting_AllyWithSharedVision"
        : "libNtve_ge_AllianceSetting_Enemy";
      alliances.push(`    libNtve_gf_SetAlliance(${first}, ${second}, ${setting});`);
      alliances.push(`    libNtve_gf_SetAlliance(${second}, ${first}, ${setting});`);
    }
  }
  const { bridgeDeclarations, bridgeInit } = makeUnitControlBlock(activeSlots, humanRuntimeId, strategyBridge, bridgeProbe, unitControlActive);
  const productionRules = strategyBridge && !bridgeProbe
    ? makeProductionRules(activeSlots, allowSupportAir, campaignUnitsPilot, researchProbe, protossFaction)
    : "";
  const nativeTorrasqueInit = campaignUnitsPilot
    ? activeSlots
        .map((slot, index) => ({ slot, player: index + 1 }))
        .filter(({ slot }) => slot.race === "Zerg")
        .map(({ player }) => [
          `    TechTreeUnitAllow(${player}, "HotSTorrasque", true);`,
          `    TechTreeUpgradeAddLevel(${player}, "HotSTorrasque", 1);`,
        ].join("\n"))
        .join("\n")
    : "";
  const torrasqueProbe = campaignUnitsProbeDamage
    ? `trigger gt_sc2team_TorrasqueProbeDamage;

bool sc2team_TorrasqueProbeDamage_Func (bool testConds, bool runActions) {
    unitgroup targetUnits;
    unit currentUnit;
    int unitIndex;

    if (!runActions) {
        return true;
    }
    targetUnits = UnitGroup("HotSTorrasque", 1, RegionEntireMap(), UnitFilter(0, 0, 0, 0), 0);
    unitIndex = UnitGroupCount(targetUnits, c_unitCountAlive);
    for (;; unitIndex -= 1) {
        currentUnit = UnitGroupUnitFromEnd(targetUnits, unitIndex);
        if (currentUnit == null) {
            break;
        }
        if (UnitGetPropertyFixed(currentUnit, c_unitPropLife, c_unitPropCurrent) <= 2.0 &&
            UnitGetCustomValue(currentUnit, 26) < 1.0) {
            UnitSetCustomValue(currentUnit, 26, 1.0);
            UnitDamage(currentUnit, "SC2TeamTorrasqueProbeDamage", currentUnit, 0.0);
        }
    }
    return true;
}

void sc2team_InitializeTorrasqueProbeDamage () {
    UnitCreate(1, "HotSTorrasque", c_unitCreateIgnorePlacement, 1, PlayerStartLocation(1), 0.0);
    gt_sc2team_TorrasqueProbeDamage = TriggerCreate("sc2team_TorrasqueProbeDamage_Func");
    TriggerAddEventTimePeriodic(gt_sc2team_TorrasqueProbeDamage, 0.0625, c_timeGame);
}

`
    : "";
  const torrasqueProbeInit = campaignUnitsProbeDamage
    ? "\n    sc2team_InitializeTorrasqueProbeDamage();"
    : "";
  // V3 wild Zerg remains a normal lobby Computer. The V3 Zerg root returns
  // before ZergInit while user-int 145 is zero, so no invalid main state is
  // required. Preplaced combat units are held with the same engine-native
  // script-control mechanism verified in V2, while Drones and structures stay
  // autonomous. At 7:00 the trigger releases both the build and held units.
  const v3WildDelay = meleeOnly && wildZergActive
    ? `trigger gt_sc2team_V3WildRelease;
int gv_sc2team_V3WildHoldPhase = 0;
const int c_sc2teamV3WildHoldMark = 40;

void sc2team_V3SetWildCombatControl (bool controlled) {
    unitgroup wildUnits = UnitGroup(null, 15, RegionEntireMap(), UnitFilter(0, 0, 0, 0), 0);
    unit currentUnit;
    string unitType;
    int unitIndex = UnitGroupCount(wildUnits, c_unitCountAlive);

    for (;; unitIndex -= 1) {
        currentUnit = UnitGroupUnitFromEnd(wildUnits, unitIndex);
        if (currentUnit == null) {
            break;
        }
        unitType = UnitGetType(currentUnit);
        if (UnitTypeTestAttribute(unitType, c_unitAttributeStructure) ||
            unitType == "Drone" || unitType == "Larva" || unitType == "Egg" ||
            unitType == "Overlord" || unitType == "OverlordTransport" ||
            unitType == "Overseer") {
            continue;
        }
        if (controlled) {
            UnitSetCustomValue(currentUnit, c_sc2teamV3WildHoldMark, 1.0);
            AISetUnitScriptControlled(currentUnit, true);
        }
        else if (UnitGetCustomValue(currentUnit, c_sc2teamV3WildHoldMark) == 1.0) {
            AISetUnitScriptControlled(currentUnit, false);
            UnitSetCustomValue(currentUnit, c_sc2teamV3WildHoldMark, 0.0);
        }
    }
}

bool sc2team_V3WildRelease_Func (bool testConds, bool runActions) {
    if (!runActions) {
        return true;
    }
    if (AIGetTime() < 420.0) {
        sc2team_V3SetWildCombatControl(true);
        gv_sc2team_V3WildHoldPhase = 1;
        return true;
    }
    AISetUserInt(15, 142, 301);
    AISetUserInt(15, 144, 0);
    AISetUserInt(15, 145, 1);
    AISetSpecificState(15, 1, 1);
    AISetSpecificState(15, 2, 1);
    AISetSpecificState(15, 3, 1);
    sc2team_V3SetWildCombatControl(false);
    gv_sc2team_V3WildHoldPhase = 2;
    TriggerEnable(gt_sc2team_V3WildRelease, false);
    return true;
}

void sc2team_InitializeV3WildDelay () {
    AISetUserInt(15, 142, 301);
    AISetUserInt(15, 144, 0);
    AISetUserInt(15, 145, 0);
    gt_sc2team_V3WildRelease = TriggerCreate("sc2team_V3WildRelease_Func");
    TriggerAddEventTimePeriodic(gt_sc2team_V3WildRelease, 2.0, c_timeGame);
}

`
    : "";
  // P15 is the map's neutral-hostile owner, not a lobby Computer player, so
  // Blizzard's melee AI cannot run it.  Its preplaced Zerg camps instead get a
  // small self-contained wildlife controller.  P15 is not a lobby Computer,
  // so this supplies the missing economy loop as well as strictly local
  // patrol/defense after the opening.
  // The P14 decoration migration below deliberately feeds the same controller.
  // §93: 런처에서 야생 저그를 끄면 채취 전용 컨트롤러로 바꾼다. 명령은
  // DroneHarvest 하나뿐이며, 승격을 되돌린 빌더 쪽 변경과 짝을 이룬다.
  const hostileWildAI = meleeOnly
    ? wildZergActive
      ? v3WildDelay
      : ""
    : readGalaxyTemplate(wildZergActive ? "hostile_wild_ai" : "hostile_wild_idle");
  const hostileWildInit = meleeOnly
    ? ""
    : wildZergActive
      ? "\n    sc2team_InitializeHostileWildAI();"
      : "\n    sc2team_InitializeHostileWildIdle();";
  return `// SC2TEAM_CUSTOM_BEGIN
// Logical location slots are compacted to consecutive runtime player IDs.
${bridgeDeclarations}${productionRules}${torrasqueProbe}${hostileWildAI}void sc2team_InitializeRuntime () {
${alliances.join("\n")}
${vision}${bridgeInit}
${nativeTorrasqueInit}${torrasqueProbeInit}${hostileWildInit}
}
// SC2TEAM_CUSTOM_END`;
}

function patchMapScript(script, activeSlots, humanRuntimeId, fullVision, strategyBridge, bridgeProbe, meleeOnly, allowSupportAir, campaignUnitsPilot, campaignUnitsProbeDamage, researchProbe, protossFaction = "Standard", wildZergActive = true, unitControlActive = false) {
  const block = /\/\/ SC2TEAM_CUSTOM_BEGIN[\s\S]*?\/\/ SC2TEAM_CUSTOM_END/;
  if (!block.test(script)) fail("SC2TEAM custom block is missing");
  let updated = script.replace(
    block,
    makeRuntimeSupport(
      activeSlots,
      humanRuntimeId,
      fullVision,
      strategyBridge,
      bridgeProbe,
      meleeOnly,
      allowSupportAir,
      campaignUnitsPilot,
      campaignUnitsProbeDamage,
      researchProbe,
      protossFaction,
      wildZergActive,
      unitControlActive
    )
  );
  updated = updated.replace(/sc2team_Initialize7v7\s*\(\s*\)\s*;/g, "sc2team_InitializeRuntime();");
  updated = updated.replace(/sc2team_InitializeProBotTest\s*\(\s*\)\s*;/g, "sc2team_InitializeRuntime();");
  // A previously generated runtime map may already contain this call outside
  // the replaceable custom block. Normalize it before adding the current one.
  updated = updated.replace(
    /^\s*sc2team_InitializeProductionRules\s*\(\s*\)\s*;\s*$/gm,
    ""
  );
  // Probe maps isolate the bridge. Normal strategy maps keep Blizzard's melee
  // economy/production AI and override army-level decisions externally.
  if ((!strategyBridge || bridgeProbe) && !meleeOnly) {
    updated = updated.replace(/^\s*MeleeInitAI\s*\(\s*\)\s*;\s*$/gm, "");
  }
  if (!updated.includes("sc2team_InitializeRuntime();")) {
    fail("Could not replace the map initialization call");
  }
  if (strategyBridge && !bridgeProbe && !meleeOnly) {
    updated = updated.replace(
      /MeleeInitAI\s*\(\s*\)\s*;/,
      "MeleeInitAI();\n    sc2team_InitializeProductionRules();"
    );
  }
  if (meleeOnly && wildZergActive) {
    updated = updated.replace(
      /MeleeInitAI\s*\(\s*\)\s*;/,
      "MeleeInitAI();\n    sc2team_InitializeV3WildDelay();"
    );
  }
  if ((!strategyBridge || bridgeProbe) && !meleeOnly && /MeleeInitAI\s*\(/.test(updated)) {
    fail("MeleeInitAI is still enabled");
  }
  return updated;
}


module.exports = {
  makeRuntimeSupport,
  patchMapScript,
};
