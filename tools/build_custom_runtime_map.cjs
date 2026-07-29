#!/usr/bin/env node

const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { Archive } = require("@jamiephan/stormlib");

const { fail } = require("./build/util.cjs");
const { PREFERRED_STOCK_BY_BUILD } = require("./build/tables.cjs");
const {
  validateConfig,
  patchPlayers,
  parseMapInfoPlayers,
} = require("./build/mapinfo.cjs");
const { patchMapScript } = require("./build/runtime.cjs");
const { verify } = require("./build/verify.cjs");
const {
  patchCampaignAssetDependencies,
  patchDocumentHeaderDependencies,
  patchLocalization,
  patchHotkeys,
  patchNativeTorrasque,
  patchNativeCampaignRosterParents,
  patchWildZergStart,
  patchWildZergForeignUnits,
  patchCampaignRoster,
  patchProtossFaction,
  patchSupplyCeiling,
  patchHostileDecorations,
} = require("./build/archive.cjs");

function makeStockTargets(activeSlots) {
  const slots = [];
  for (let index = 0; index < activeSlots.length; index += 1) {
    const slot = activeSlots[index];
    if (slot.controller !== "custom_ai") continue;
    const preferred = PREFERRED_STOCK_BY_BUILD[slot.build];
    if (preferred === undefined) fail(`Unknown ground build for P${slot.slot}: ${slot.build}`);
    const stock = {};
    for (const [unitType, count] of Object.entries(preferred)) {
      stock[unitType] = {
        count,
        perExpansion: slot.race === "Random" ? 0 : Math.max(1, Math.ceil(count * 0.6)),
      };
    }
    slots.push({
      runtime_player: index + 1,
      logical_slot: slot.slot,
      build: slot.build,
      race: slot.race,
      stock,
    });
  }
  return { version: 1, slots };
}

function assertMapInfoCapacity(source, activeSlots) {
  const archive = Archive.open(source);
  try {
    const playerSlots = parseMapInfoPlayers(archive.readFile("MapInfo"))
      .filter((player) => player.id >= 1 && player.id <= 14);
    if (playerSlots.length < activeSlots.length) {
      fail(
        `MapInfo has ${playerSlots.length} player slots but the configuration needs ${activeSlots.length}`
      );
    }
  } finally {
    archive.close();
  }
}

function main() {
  const [sourceArg, outputArg, configArg] = process.argv.slice(2);
  if (!sourceArg || !outputArg || !configArg) {
    console.error("Usage: build_custom_runtime_map.cjs <source> <output> <config.json>");
    process.exit(2);
  }
  const source = path.resolve(sourceArg);
  const output = path.resolve(outputArg);
  const configPath = path.resolve(configArg);
  if (!fs.existsSync(source)) fail(`Source map not found: ${source}`);
  const config = JSON.parse(fs.readFileSync(configPath, "utf8"));
  const human = validateConfig(config);
  // SC2 always promotes the sole Participant ahead of Computer players, even
  // when RequestCreateGame lists Computers first. Mirror that engine order in
  // MapInfo so runtime P1 receives the selected human location.
  const activeSlots = [
    human,
    ...config.slots.filter((slot) => slot.controller === "custom_ai"),
  ];
  const humanRuntimeId = 1;
  if (config.observer_mode) {
    // §66 옵저버 모드: 게임은 Participant 없이 만들어지고(사람 슬롯도 진짜
    // 컴퓨터, API 클라이언트는 Observer로 참가) 런타임 ID는 지금과 같은
    // 순서(사람 슬롯 먼저 = P1)로 배정된다(엔진 실측). 여기서는 사람 슬롯을
    // 커스텀 AI 슬롯처럼 취급해 생산 규칙·목표 재고·연구 트리거를 똑같이
    // 받게만 하면 된다. 참가자에게 AIStart/AIMeleeStart로 멜레 AI를 붙이는
    // 건 4가지 조합 모두 엔진이 무시했다(§66 실측) — 시도하지 말 것.
    // 런처가 빌드 유효성을 보장한다(종족에 안 맞으면 기본 빌드로 교체).
    if ((!config.strategy_bridge || config.bridge_probe) && !config.melee_only) {
      fail("observer_mode requires the strategy bridge or melee_only mode");
    }
    activeSlots[0] = { ...human, controller: "custom_ai" };
  }
  assertMapInfoCapacity(source, activeSlots);

  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "sc2-custom-runtime-"));
  const staged = path.join(tempDir, "map.SC2Map");
  try {
    fs.copyFileSync(source, staged);
    const archive = Archive.open(staged);
    let assignments;
    try {
      // §90: 야생 저그를 실제 로비 컴퓨터 슬롯으로 승격시킨다. 시작 지점은
      // 1시 본진(알파 둥지) 자리로 옮긴 여분의 StartLoc 이다. 중립 적대로는
      // 전투 유닛을 생산할 수 없다는 것이 프로브 12판으로 확정됐다.
      //
      // §93: 런처에서 야생 저그를 끄면 이 승격을 통째로 건너뛴다. 그것이 바로
      // "생산 금지"의 구현이다 — 맵 트리거만 비우면 P15 는 여전히 로비 컴퓨터라
      // 블리자드 멜레 AI 가 대신 생산한다. 승격이 없으면 중립 적대로 돌아가고,
      // 그 상태에서 엔진이 허용하는 것은 드론·대군주뿐이며(§90 실측) 그 둘조차
      // 발주할 코드가 비활성 컨트롤러에는 없다.
      const wildZergActive = config.wild_zerg !== false;
      // §105: 유닛 제어 모듈(브리지·공격 브로드캐스트·지원·본진 방어)은 opt-in.
      // 기본 off — 병력 지휘는 밀레 AI 자율이고 우리 레이어는 생산·보급·확장
      // 보조만 한다. bridge_probe 맵은 브리지 계측이 목적이므로 항상 포함.
      const unitControlActive = config.unit_control === true;
      const mapInfoBuffer = archive.readFile("MapInfo");
      const usedStartPoints = new Set(
        parseMapInfoPlayers(mapInfoBuffer)
          .filter((player) => player.id >= 1 && player.id <= 14)
          .map((player) => player.startPoint)
      );
      let wildStartPoint = null;
      if (wildZergActive) {
        const wildStart = patchWildZergStart(archive, usedStartPoints);
        wildStartPoint = wildStart.startPoint;
        console.log(
          `Wild Zerg start point ${wildStart.startPoint} at ${wildStart.position}` +
          (wildStart.moved ? " (moved onto the alpha nest)" : " (user placement kept)")
        );
      } else {
        console.log("Wild Zerg: disabled (neutral hostile, harvest only)");
      }
      const playerPatch = patchPlayers(
        mapInfoBuffer,
        activeSlots,
        wildStartPoint
      );
      assignments = playerPatch.assignments;
      archive.addBuffer("MapInfo", playerPatch.mapInfo);
      archive.addString(
        "MapScript.galaxy",
        patchMapScript(
          archive.readFileAsString("MapScript.galaxy", "utf8"),
          activeSlots,
          humanRuntimeId,
          Boolean(config.full_vision),
          Boolean(config.strategy_bridge),
          Boolean(config.bridge_probe),
          Boolean(config.melee_only),
          config.allow_support_air !== false,
          Boolean(config.campaign_units_pilot),
          Boolean(config.campaign_units_probe_damage),
          Boolean(config.research_probe),
          config.protoss_faction ?? "Standard",
          wildZergActive,
          unitControlActive
        ),
        { encoding: "utf8" }
      );
      patchLocalization(archive, config.protoss_faction ?? "Standard");
      patchHotkeys(archive);
      if (config.campaign_units_pilot) {
        patchCampaignAssetDependencies(archive);
        patchDocumentHeaderDependencies(archive);
        patchNativeTorrasque(archive);
        patchNativeCampaignRosterParents(archive);
        patchCampaignRoster(archive);
      }
      patchProtossFaction(archive, config.protoss_faction ?? "Standard");
      patchSupplyCeiling(archive);
      const movedDecorations = patchHostileDecorations(archive);
      if (movedDecorations.movedP14 > 0 || movedDecorations.movedP7Overlords > 0) {
        console.log(
          `Hostile decorations: moved ${movedDecorations.movedP14} player-14 units and ${movedDecorations.movedP7Overlords} player-7 Overlords to player 15`
        );
      }
      // §90.9: 야생 저그에 섞인 프로토스 선배치 유닛 제거. P14 이관 뒤에 돈다.
      const foreign = patchWildZergForeignUnits(archive);
      if (foreign.total > 0) {
        const detail = Object.entries(foreign.removed)
          .map(([type, count]) => `${type} x${count}`)
          .join(", ");
        console.log(`Wild Zerg: removed ${foreign.total} Protoss units (${detail})`);
      }
      archive.compact();
      verify(archive, config, humanRuntimeId, assignments, activeSlots);
    } finally {
      archive.close();
    }
    fs.mkdirSync(path.dirname(output), { recursive: true });
    fs.copyFileSync(staged, output);
    const targetsPath = `${output}.targets.json`;
    fs.writeFileSync(
      targetsPath,
      JSON.stringify(makeStockTargets(activeSlots), null, 2)
    );
    console.log(`Built: ${output}`);
    console.log(`Stock targets: ${targetsPath}`);
    console.log(
      `Slot mapping: ${assignments.map((item) => `P${item.logicalSlot}->runtime P${item.runtimeId}`).join(", ")}`
    );
    console.log(`Human slot: P${human.slot} -> runtime P${humanRuntimeId}`);
    console.log(
      `Built-in melee AI: ${(config.strategy_bridge && !config.bridge_probe) || config.melee_only ? "enabled" : "disabled"}`
    );
    console.log(
      `Unit control module: ${config.bridge_probe ? "enabled (bridge probe)" : config.unit_control === true ? "enabled" : "disabled (melee AI commands its own army)"}`
    );
  } finally {
    fs.rmSync(tempDir, { recursive: true, force: true });
  }
}

try {
  main();
} catch (error) {
  console.error(`ERROR: ${error.message}`);
  process.exitCode = 1;
}
