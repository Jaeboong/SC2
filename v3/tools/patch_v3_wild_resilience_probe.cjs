// Test-only P15 local-wipe injector. Never used by the launcher or V3 builder.
"use strict";

const { Archive } = require("../../tools/node_modules/@jamiephan/stormlib");

const [mapPath] = process.argv.slice(2);
if (!mapPath || process.argv.length !== 3) {
  throw new Error("usage: node patch_v3_wild_resilience_probe.cjs <map.SC2Map>");
}

const DECLARATION_MARKER = "// SC2TEAM_CUSTOM_END";
const INIT_MARKER = "    sc2team_InitializeV3WildBootstrap();";
const PROBE_SOURCE = `trigger gt_v3WildResilienceWipe;

bool v3WildResilienceWipe_Func (bool testConds, bool runActions) {
    unitgroup wildUnits;
    unit currentUnit;
    int unitIndex;
    point alpha = Point(237.5, 240.5);

    if (!runActions || AIGetTime() < 361.0) {
        return true;
    }
    wildUnits = UnitGroup(null, 15, RegionEntireMap(), UnitFilter(0, 0, 0, 0), 0);
    unitIndex = UnitGroupCount(wildUnits, c_unitCountAlive);
    for (;; unitIndex -= 1) {
        currentUnit = UnitGroupUnitFromEnd(wildUnits, unitIndex);
        if (currentUnit == null) {
            break;
        }
        if (DistanceBetweenPoints(UnitGetPosition(currentUnit), alpha) > 42.0) {
            UnitRemove(currentUnit);
        }
    }
    TriggerEnable(gt_v3WildResilienceWipe, false);
    return true;
}

void v3WildResilienceWipe_Initialize () {
    gt_v3WildResilienceWipe = TriggerCreate("v3WildResilienceWipe_Func");
    TriggerAddEventTimePeriodic(gt_v3WildResilienceWipe, 1.0, c_timeGame);
}

`;

const archive = Archive.open(mapPath);
try {
  let script = archive.readFileAsString("MapScript.galaxy", "utf8");
  if (!script.includes(DECLARATION_MARKER) || !script.includes(INIT_MARKER)) {
    throw new Error("V3 wild bootstrap markers are missing");
  }
  if (script.includes("v3WildResilienceWipe_Func")) {
    throw new Error("resilience probe is already installed");
  }
  script = script.replace(DECLARATION_MARKER, PROBE_SOURCE + DECLARATION_MARKER);
  script = script.replace(
    INIT_MARKER,
    INIT_MARKER + "\n    v3WildResilienceWipe_Initialize();",
  );
  archive.addString("MapScript.galaxy", script, { encoding: "utf8" });
  archive.compact();
} finally {
  archive.close();
}

console.log("V3_WILD_RESILIENCE_PROBE_PATCH=PASS");
