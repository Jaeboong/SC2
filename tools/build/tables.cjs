const { fail } = require("./util.cjs");

// 빌드 구성 데이터 표: 종족·빌드별 유닛 조합, 목표 재고, 연구 사다리,
// 인프라/생산 건물 표. 순수 데이터와 그 조회 헬퍼만 둔다 — 맵을 만드는
// 로직은 넣지 않는다.

const MAP_NAME_KO = "유럽 섬멸전 Custom AI v1.25.0";
const MAP_NAME_EN = "Europe Melee Custom AI v1.25.0";
// Keep this list minimal, and re-run the roster probe after touching it.
//
// Only the Terran roster models (Predator, Goliath, Medic) need a campaign
// archive; the Zerg models (Aberration, Raptor, Torrasque) already resolve from
// the base install. Adding Swarm Story pulls in Campaigns/Swarm.SC2Campaign,
// which redefines FactoryTrain Train20 to Hellion and silently steals the slot
// our Goliath purchase uses, leaving SC2TeamGoliath with ability_id 0.
const CAMPAIGN_ASSET_DEPENDENCIES = [
  "bnet:Liberty (Campaign)/0.0/999,file:Campaigns/Liberty.SC2Campaign",
];
const PROTOSS_FACTIONS = new Set(["Standard", "Aiur", "Nerazim", "Purifier", "Taldarim"]);
const PROTOSS_FACTION_SENTINEL_MODEL = {
  Aiur: "Dragoon",
  Nerazim: "SC2TeamImmortalNerazimModel",
  Purifier: "SC2TeamStalkerPurifierModel",
  Taldarim: "SC2TeamColossusTaldarimModel",
};

const COMBAT_AIR_BY_RACE = {
  Terran: ["VikingFighter", "Banshee", "Liberator", "Battlecruiser"],
  Protoss: ["Phoenix", "VoidRay", "Oracle", "Carrier", "Tempest", "Mothership"],
  Zerg: ["Mutalisk", "Corruptor", "BroodLord", "Viper"],
};

const SUPPORT_AIR_BY_RACE = {
  Terran: ["Medivac", "Raven"],
  Protoss: ["Observer", "WarpPrism"],
  Zerg: ["OverlordTransport", "Overseer"],
};

const SUPPORT_AIR_CAP = {
  Medivac: 4,
  Raven: 2,
  Observer: 3,
  WarpPrism: 2,
  OverlordTransport: 2,
  Overseer: 3,
};

const SUPPORT_AIR_CAP_OVERRIDES_BY_BUILD = {
  hellion_tank: { Medivac: 0 },
  thor_tank: { Medivac: 0 },
  mech_macro: { Medivac: 0 },
};

function supportAirCap(build, unitType, allowSupportAir) {
  if (!allowSupportAir) return 0;
  return SUPPORT_AIR_CAP_OVERRIDES_BY_BUILD[build]?.[unitType]
    ?? SUPPORT_AIR_CAP[unitType];
}

const GROUND_COMBAT_BY_RACE = {
  Terran: [
    "Marine", "Marauder", "Reaper", "Ghost", "Hellion", "HellionTank",
    "SiegeTank", "Thor", "WidowMine", "Cyclone", "SC2TeamGoliath",
    "SC2TeamPredator", "SC2TeamMedic",
  ],
  Protoss: [
    "Zealot", "Stalker", "Sentry", "Adept", "HighTemplar", "DarkTemplar",
    "Archon", "Immortal", "Colossus", "Disruptor",
  ],
  Zerg: [
    "Zergling", "Baneling", "Roach", "Ravager", "Hydralisk", "LurkerMP",
    "Infestor", "SwarmHostMP", "Ultralisk", "HotSTorrasque", "SC2TeamAberration",
  ],
};

// Desired standing-army counts. AISetStock updates the absolute target for the
// listed item without clearing Blizzard's worker, economy, upgrade, or supply
// stock plan. Re-applying it periodically also wins over race build functions
// that would otherwise replace the weaker AISetStockUnitNext hints.
//
// §68: 병력 상한 철폐(사용자 지시 — "어떤 상황에서도 병력에 상한을 두지 마라").
// 아래 표의 수치는 병종 간 비율로만 쓰이고, 실제 AISetStock 목표는
// STOCK_SQUEEZE_MULTIPLIER 배(도달 불가능한 수준)로 키워 멜레 AI가 인구
// 한도까지 끊임없이 생산하게 한다. 공격 타이밍 사이드카(makeStockTargets)는
// 1배 값을 유지한다 — required_power는 MAX_ATTACK_POWER로 클램프되므로
// 출격 판정을 바꾸지 않기 위해서다.
const PREFERRED_STOCK_BY_BUILD = {
  bio: { Marine: 24, Marauder: 8, SC2TeamMedic: 4 },
  bio_tank: { Marine: 18, Marauder: 8, SiegeTank: 6, SC2TeamMedic: 3 },
  // §91: 사용자 요청 — 공장 기반 빌드는 사이클론도 쓴다.
  hellion_tank: { Hellion: 10, SiegeTank: 8, Cyclone: 6, SC2TeamPredator: 6, SC2TeamGoliath: 5 },
  thor_tank: { Thor: 5, SiegeTank: 8, Hellion: 6, Cyclone: 5, SC2TeamGoliath: 8, SC2TeamPredator: 4 },
  // mech_macro는 사용자 요청으로 화염차를 빼고 그 보급(8기×2=16)을
  // 공성전차·골리앗·프레데터에 재배분했다 (+2씩 = 6+4+6 보급).
  mech_macro: { Thor: 5, SiegeTank: 10, Cyclone: 6, SC2TeamGoliath: 10, SC2TeamPredator: 8 },
  gateway: { Zealot: 14, Stalker: 12, Sentry: 3 },
  stalker_immortal: { Stalker: 16, Immortal: 6 },
  zealot_archon: { Zealot: 18, HighTemplar: 6 },
  immortal_colossus: { Stalker: 10, Immortal: 6, Colossus: 5 },
  disruptor_ground: { Zealot: 8, Stalker: 12, Disruptor: 6 },
  ling_bane: { Zergling: 40, Baneling: 16 },
  roach_ravager: { Roach: 20, Ravager: 8 },
  roach_hydra: { Roach: 14, Hydralisk: 14, SC2TeamAberration: 6 },
  hydra_lurker: { Hydralisk: 20, LurkerMP: 8 },
  ultra_ling_bane: { HotSTorrasque: 6, SC2TeamAberration: 8, Zergling: 36, Baneling: 12 },
  random_ground: {},
};

// §68: 가장 작은 빌드(합계 ~40기)도 인구 800을 넘기는 배수.
const STOCK_SQUEEZE_MULTIPLIER = 16;

const PREFERRED_UPGRADES_BY_BUILD = {
  bio: [], bio_tank: [], hellion_tank: [], thor_tank: [], mech_macro: [],
  gateway: [], stalker_immortal: [], zealot_archon: [], immortal_colossus: [],
  disruptor_ground: [],
  ling_bane: ["SC2TeamRaptorEvolution"],
  roach_ravager: [], roach_hydra: [], hydra_lurker: [],
  ultra_ling_bane: ["SC2TeamRaptorEvolution"],
  random_ground: [],
};

// §63: 멜레 AI는 이 맵에서 무기/방어 업그레이드를 연구하지 않는다(사용자
// 실관측). AISetStock 기술실 요청이 무시된 전례(§62)가 있어 부탁이 아니라
// 트리거가 유휴 연구 구조물에 연구 명령을 직접 내린다. 명령이라 비용·시간·
// 요구조건이 전부 정상 적용되고, 잔고 하한(광물 +500 / 가스 +400)과 틱당
// 1건 제한으로 §61의 은행 고갈을 재발시키지 않는다.
//
// index는 어빌리티 명령 인덱스(= InfoArray "ResearchN"의 N-1)다. 비용은
// liberty→swarm→swarmmulti→voidmulti 레이어를 합성한 현행 멜레 값이며,
// 값이 틀려도 실제 차감은 엔진이 하므로 잔고 하한 판정에만 쓰인다.
// prereqUpgrade가 있으면 그 업그레이드 완료 후에만 명령을 내려, 요구조건
// 미충족 명령이 매 틱 연구 슬롯을 헛소모하는 것을 막는다.
// §105.8(감사 C1-1): 무/방/실드 2~3레벨의 구조물 요구조건을 vendor
// RequirementData(liberty, 후속 레이어 재정의 0건 확인)에서 도출해 채웠다.
// 게이트 없는 상위 레벨 발주는 매 틱 발주→거부→true 로 틱을 소모해, 정당하게
// 가능한 하위 엔트리를 영구히 굶긴다(틱당 1건 상한). prereqStructure "Lair"는
// sc2team_HasResearchTech가 Hive로도 충족 처리한다(Alias_Lair와 동형).
const RESEARCH_TERRAN_INFANTRY = [
  { structure: "EngineeringBay", abil: "EngineeringBayResearch", index: 2, upgrade: "TerranInfantryWeaponsLevel1", prereqUpgrade: null, minerals: 100, gas: 100 },
  { structure: "EngineeringBay", abil: "EngineeringBayResearch", index: 6, upgrade: "TerranInfantryArmorsLevel1", prereqUpgrade: null, minerals: 100, gas: 100 },
  { structure: "EngineeringBay", abil: "EngineeringBayResearch", index: 3, upgrade: "TerranInfantryWeaponsLevel2", prereqUpgrade: "TerranInfantryWeaponsLevel1", prereqStructure: "Armory", minerals: 150, gas: 150 },
  { structure: "EngineeringBay", abil: "EngineeringBayResearch", index: 7, upgrade: "TerranInfantryArmorsLevel2", prereqUpgrade: "TerranInfantryArmorsLevel1", prereqStructure: "Armory", minerals: 150, gas: 150 },
  { structure: "EngineeringBay", abil: "EngineeringBayResearch", index: 4, upgrade: "TerranInfantryWeaponsLevel3", prereqUpgrade: "TerranInfantryWeaponsLevel2", prereqStructure: "Armory", minerals: 200, gas: 200 },
  { structure: "EngineeringBay", abil: "EngineeringBayResearch", index: 8, upgrade: "TerranInfantryArmorsLevel3", prereqUpgrade: "TerranInfantryArmorsLevel2", prereqStructure: "Armory", minerals: 200, gas: 200 },
];
const RESEARCH_TERRAN_VEHICLE = [
  { structure: "Armory", abil: "ArmoryResearch", index: 5, upgrade: "TerranVehicleWeaponsLevel1", prereqUpgrade: null, minerals: 100, gas: 100 },
  { structure: "Armory", abil: "ArmoryResearch", index: 14, upgrade: "TerranVehicleAndShipArmorsLevel1", prereqUpgrade: null, minerals: 100, gas: 100 },
  { structure: "Armory", abil: "ArmoryResearch", index: 6, upgrade: "TerranVehicleWeaponsLevel2", prereqUpgrade: "TerranVehicleWeaponsLevel1", minerals: 175, gas: 175 },
  { structure: "Armory", abil: "ArmoryResearch", index: 15, upgrade: "TerranVehicleAndShipArmorsLevel2", prereqUpgrade: "TerranVehicleAndShipArmorsLevel1", minerals: 175, gas: 175 },
  { structure: "Armory", abil: "ArmoryResearch", index: 7, upgrade: "TerranVehicleWeaponsLevel3", prereqUpgrade: "TerranVehicleWeaponsLevel2", minerals: 250, gas: 250 },
  { structure: "Armory", abil: "ArmoryResearch", index: 16, upgrade: "TerranVehicleAndShipArmorsLevel3", prereqUpgrade: "TerranVehicleAndShipArmorsLevel2", minerals: 250, gas: 250 },
];
// 보호막(방패)은 트와일라잇 없이도 연구 가능하므로 2레벨 게이트 앞에 둔다.
const RESEARCH_PROTOSS_GROUND = [
  { structure: "Forge", abil: "ForgeResearch", index: 0, upgrade: "ProtossGroundWeaponsLevel1", prereqUpgrade: null, minerals: 100, gas: 100 },
  { structure: "Forge", abil: "ForgeResearch", index: 3, upgrade: "ProtossGroundArmorsLevel1", prereqUpgrade: null, minerals: 100, gas: 100 },
  { structure: "Forge", abil: "ForgeResearch", index: 6, upgrade: "ProtossShieldsLevel1", prereqUpgrade: null, minerals: 150, gas: 150 },
  { structure: "Forge", abil: "ForgeResearch", index: 1, upgrade: "ProtossGroundWeaponsLevel2", prereqUpgrade: "ProtossGroundWeaponsLevel1", prereqStructure: "TwilightCouncil", minerals: 150, gas: 150 },
  { structure: "Forge", abil: "ForgeResearch", index: 4, upgrade: "ProtossGroundArmorsLevel2", prereqUpgrade: "ProtossGroundArmorsLevel1", prereqStructure: "TwilightCouncil", minerals: 150, gas: 150 },
  { structure: "Forge", abil: "ForgeResearch", index: 2, upgrade: "ProtossGroundWeaponsLevel3", prereqUpgrade: "ProtossGroundWeaponsLevel2", prereqStructure: "TwilightCouncil", minerals: 200, gas: 200 },
  { structure: "Forge", abil: "ForgeResearch", index: 5, upgrade: "ProtossGroundArmorsLevel3", prereqUpgrade: "ProtossGroundArmorsLevel2", prereqStructure: "TwilightCouncil", minerals: 200, gas: 200 },
  { structure: "Forge", abil: "ForgeResearch", index: 7, upgrade: "ProtossShieldsLevel2", prereqUpgrade: "ProtossShieldsLevel1", prereqStructure: "TwilightCouncil", minerals: 200, gas: 200 },
  { structure: "Forge", abil: "ForgeResearch", index: 8, upgrade: "ProtossShieldsLevel3", prereqUpgrade: "ProtossShieldsLevel2", prereqStructure: "TwilightCouncil", minerals: 250, gas: 250 },
];
const RESEARCH_ZERG_ARMOR = [
  { structure: "EvolutionChamber", abil: "evolutionchamberresearch", index: 3, upgrade: "ZergGroundArmorsLevel1", prereqUpgrade: null, minerals: 100, gas: 100 },
  { structure: "EvolutionChamber", abil: "evolutionchamberresearch", index: 4, upgrade: "ZergGroundArmorsLevel2", prereqUpgrade: "ZergGroundArmorsLevel1", prereqStructure: "Lair", minerals: 150, gas: 150 },
  { structure: "EvolutionChamber", abil: "evolutionchamberresearch", index: 5, upgrade: "ZergGroundArmorsLevel3", prereqUpgrade: "ZergGroundArmorsLevel2", prereqStructure: "Hive", minerals: 200, gas: 200 },
];
const RESEARCH_ZERG_MELEE = [
  { structure: "EvolutionChamber", abil: "evolutionchamberresearch", index: 0, upgrade: "ZergMeleeWeaponsLevel1", prereqUpgrade: null, minerals: 100, gas: 100 },
  RESEARCH_ZERG_ARMOR[0],
  { structure: "EvolutionChamber", abil: "evolutionchamberresearch", index: 1, upgrade: "ZergMeleeWeaponsLevel2", prereqUpgrade: "ZergMeleeWeaponsLevel1", prereqStructure: "Lair", minerals: 150, gas: 150 },
  RESEARCH_ZERG_ARMOR[1],
  { structure: "EvolutionChamber", abil: "evolutionchamberresearch", index: 2, upgrade: "ZergMeleeWeaponsLevel3", prereqUpgrade: "ZergMeleeWeaponsLevel2", prereqStructure: "Hive", minerals: 200, gas: 200 },
  RESEARCH_ZERG_ARMOR[2],
];
const RESEARCH_ZERG_MISSILE = [
  { structure: "EvolutionChamber", abil: "evolutionchamberresearch", index: 6, upgrade: "ZergMissileWeaponsLevel1", prereqUpgrade: null, minerals: 100, gas: 100 },
  RESEARCH_ZERG_ARMOR[0],
  { structure: "EvolutionChamber", abil: "evolutionchamberresearch", index: 7, upgrade: "ZergMissileWeaponsLevel2", prereqUpgrade: "ZergMissileWeaponsLevel1", prereqStructure: "Lair", minerals: 150, gas: 150 },
  RESEARCH_ZERG_ARMOR[1],
  { structure: "EvolutionChamber", abil: "evolutionchamberresearch", index: 8, upgrade: "ZergMissileWeaponsLevel3", prereqUpgrade: "ZergMissileWeaponsLevel2", prereqStructure: "Hive", minerals: 200, gas: 200 },
  RESEARCH_ZERG_ARMOR[2],
];

// §69: 기술(테크) 업그레이드 사다리. 무/방/실드에 더해 실제 전투력을 바꾸는
// 테크 업그레이드도 §63 연구 트리거로 직접 연구시킨다(멜레 AI는 이 맵에서
// 아무 업그레이드도 스스로 연구하지 않는다 — 사용자 실관측). index/abil/비용은
// vendor/sc2gamedata-source의 liberty→swarm→swarmmulti→voidmulti 합성 CAbilResearch
// InfoArray(ResearchN → index N-1)에서 직접 확인했다.
//
// prereqStructure: 요구 구조물-테크 게이트(빈 문자열이면 무시). 요구조건 미충족
// 명령을 매 틱 발행하면 sc2team_TryResearchUpgrade가 명령을 낸 뒤 true를 돌려
// 뒤 엔트리를 영원히 굶기므로(틱당 1건), 군락(Hive)/번식지(Lair) 요구 업그레이드는
// 여기서 미리 막는다. "Lair"는 Hive로 변태해도 충족된 것으로 본다.

// 테란 바이오(BarracksTechLab): 전투 자극제/전투 방패/진탕탄.
const RESEARCH_TERRAN_BIO_TECH = [
  { structure: "BarracksTechLab", abil: "BarracksTechLabResearch", index: 0, upgrade: "Stimpack", prereqUpgrade: null, prereqStructure: "", minerals: 100, gas: 100 },
  { structure: "BarracksTechLab", abil: "BarracksTechLabResearch", index: 1, upgrade: "ShieldWall", prereqUpgrade: null, prereqStructure: "", minerals: 100, gas: 100 },
  { structure: "BarracksTechLab", abil: "BarracksTechLabResearch", index: 2, upgrade: "PunisherGrenades", prereqUpgrade: null, prereqStructure: "", minerals: 50, gas: 50 },
];
// 테란 화염차 청염(FactoryTechLab). 실 upgrade id는 HighCapacityBarrels.
const RESEARCH_TERRAN_HELLION_TECH = [
  { structure: "FactoryTechLab", abil: "FactoryTechLabResearch", index: 1, upgrade: "HighCapacityBarrels", prereqUpgrade: null, prereqStructure: "", minerals: 100, gas: 100 },
];
// §91: 사이클론 매그필드 가속기. 실 upgrade id는 CycloneLockOnDamageUpgrade이고
// FactoryTechLabResearch InfoArray Research10 → index 9다. voidmulti 최종 기술실
// 카드에 올라온 사이클론 연구 버튼은 이것 하나뿐이며, 나머지 두 후보
// (CycloneRapidFireLaunchers / HurricaneThrusters)는 TechTreeCheat 플래그가 붙은
// 사문화 항목이다(후자는 효과인 이동속도 3.375가 이미 유닛에 박혀 있어 무효과).
const RESEARCH_TERRAN_CYCLONE_TECH = [
  { structure: "FactoryTechLab", abil: "FactoryTechLabResearch", index: 9, upgrade: "CycloneLockOnDamageUpgrade", prereqUpgrade: null, prereqStructure: "", minerals: 100, gas: 100 },
];

// 프로토스 테크. 차원 관문·돌진은 전 빌드, 나머지는 조건부(해당 유닛 보유 빌드).
const RESEARCH_PROTOSS_WARPGATE = { structure: "CyberneticsCore", abil: "CyberneticsCoreResearch", index: 6, upgrade: "WarpGateResearch", prereqUpgrade: null, prereqStructure: "", minerals: 50, gas: 50 };
const RESEARCH_PROTOSS_CHARGE = { structure: "TwilightCouncil", abil: "TwilightCouncilResearch", index: 0, upgrade: "Charge", prereqUpgrade: null, prereqStructure: "", minerals: 100, gas: 100 };
const RESEARCH_PROTOSS_BLINK = { structure: "TwilightCouncil", abil: "TwilightCouncilResearch", index: 1, upgrade: "BlinkTech", prereqUpgrade: null, prereqStructure: "", minerals: 150, gas: 150 };
const RESEARCH_PROTOSS_STORM = { structure: "TemplarArchive", abil: "TemplarArchivesResearch", index: 4, upgrade: "PsiStormTech", prereqUpgrade: null, prereqStructure: "", minerals: 200, gas: 200 };
const RESEARCH_PROTOSS_THERMALLANCE = { structure: "RoboticsBay", abil: "RoboticsBayResearch", index: 5, upgrade: "ExtendedThermalLance", prereqUpgrade: null, prereqStructure: "", minerals: 150, gas: 150 };

// 저그 테크. 게이트: 아드레날린/가시지옥 두 업그레이드는 Hive, 원심 갈고리/
// 아교질 재생은 Lair 요구. 히드라 두 업그레이드는 소굴(HydraliskDen)만 요구해
// 게이트 없음(게임데이터 RequirementData의 Use 노드 부재로 확인). 울트라 두
// 업그레이드는 동굴 자체가 Hive를 요구하므로 별도 게이트 불필요.
const RESEARCH_ZERG_LING_SPEED = { structure: "SpawningPool", abil: "SpawningPoolResearch", index: 1, upgrade: "zerglingmovementspeed", prereqUpgrade: null, prereqStructure: "", minerals: 100, gas: 100 };
const RESEARCH_ZERG_LING_ADRENAL = { structure: "SpawningPool", abil: "SpawningPoolResearch", index: 0, upgrade: "zerglingattackspeed", prereqUpgrade: null, prereqStructure: "Hive", minerals: 200, gas: 200 };
const RESEARCH_ZERG_BANE_HOOKS = { structure: "BanelingNest", abil: "BanelingNestResearch", index: 0, upgrade: "CentrificalHooks", prereqUpgrade: null, prereqStructure: "Lair", minerals: 100, gas: 100 };
const RESEARCH_ZERG_ROACH_GLIAL = { structure: "RoachWarren", abil: "RoachWarrenResearch", index: 1, upgrade: "GlialReconstitution", prereqUpgrade: null, prereqStructure: "Lair", minerals: 100, gas: 100 };
const RESEARCH_ZERG_HYDRA_SPINES = { structure: "HydraliskDen", abil: "HydraliskDenResearch", index: 0, upgrade: "EvolveGroovedSpines", prereqUpgrade: null, prereqStructure: "", minerals: 75, gas: 75 };
const RESEARCH_ZERG_HYDRA_MUSCLE = { structure: "HydraliskDen", abil: "HydraliskDenResearch", index: 1, upgrade: "EvolveMuscularAugments", prereqUpgrade: null, prereqStructure: "", minerals: 100, gas: 100 };
const RESEARCH_ZERG_LURKER_TALONS = { structure: "LurkerDenMP", abil: "LurkerDenResearch", index: 0, upgrade: "DiggingClaws", prereqUpgrade: null, prereqStructure: "Hive", minerals: 100, gas: 100 };
const RESEARCH_ZERG_LURKER_RANGE = { structure: "LurkerDenMP", abil: "LurkerDenResearch", index: 1, upgrade: "LurkerRange", prereqUpgrade: null, prereqStructure: "Hive", minerals: 150, gas: 150 };
const RESEARCH_ZERG_ULTRA_CHITIN = { structure: "UltraliskCavern", abil: "UltraliskCavernResearch", index: 2, upgrade: "ChitinousPlating", prereqUpgrade: null, prereqStructure: "", minerals: 150, gas: 150 };
const RESEARCH_ZERG_ULTRA_ANABOLIC = { structure: "UltraliskCavern", abil: "UltraliskCavernResearch", index: 0, upgrade: "AnabolicSynthesis", prereqUpgrade: null, prereqStructure: "", minerals: 150, gas: 150 };

function interleaveResearch(first, second) {
  const merged = [];
  const length = Math.max(first.length, second.length);
  for (let i = 0; i < length; i += 1) {
    if (i < first.length) merged.push(first[i]);
    if (i < second.length) merged.push(second[i]);
  }
  return merged;
}

// §69: 저그 종족 통합 사다리 — random_ground 저그는 지상 유닛 전반을 뽑으므로
// 근접/원거리 무기를 교차하고 방어는 레벨당 1번만(중복 제거) 넣은 뒤, 모든 저그
// 테크 업그레이드를 뒤에 붙인다. 기존 무/방 엔트리 객체를 재사용해 재배열만 한다
// (RESEARCH_ZERG_MELEE[0/2/4] = 근접 1/2/3레벨, MISSILE[0/2/4] = 원거리 1/2/3레벨,
//  ARMOR[0/1/2] = 방어 1/2/3레벨).
const RESEARCH_ZERG_TECH_ALL = [
  RESEARCH_ZERG_LING_SPEED, RESEARCH_ZERG_LING_ADRENAL, RESEARCH_ZERG_BANE_HOOKS,
  RESEARCH_ZERG_ROACH_GLIAL, RESEARCH_ZERG_HYDRA_SPINES, RESEARCH_ZERG_HYDRA_MUSCLE,
  RESEARCH_ZERG_LURKER_TALONS, RESEARCH_ZERG_LURKER_RANGE,
  RESEARCH_ZERG_ULTRA_CHITIN, RESEARCH_ZERG_ULTRA_ANABOLIC,
];
const RESEARCH_ZERG_COMBINED = [
  RESEARCH_ZERG_MELEE[0], RESEARCH_ZERG_MISSILE[0], RESEARCH_ZERG_ARMOR[0],
  RESEARCH_ZERG_MELEE[2], RESEARCH_ZERG_MISSILE[2], RESEARCH_ZERG_ARMOR[1],
  RESEARCH_ZERG_MELEE[4], RESEARCH_ZERG_MISSILE[4], RESEARCH_ZERG_ARMOR[2],
  ...RESEARCH_ZERG_TECH_ALL,
];

const RESEARCH_LADDER_BY_BUILD = {
  // §91: 테크 업그레이드를 무/방 사다리 **앞**에 둔다(사용자 지시 — "본인이
  // 쓰는 주력 병력 관련 업글은 모두 해야함. 특히 기술실 관련 업글").
  // 사다리는 틱당 1건이고 무/방은 선행 레벨 게이트로 직렬이므로, 뒤에 둔 테크는
  // 앞의 6~12개가 전부 끝나야 차례가 온다 — 16분 계측에서 bio_tank가 1번
  // 항목에서 멈춰 있어 13번째인 자극제는 시도조차 되지 않았다. 테크는 서로
  // 독립적이고 값도 싸므로 앞에 두는 편이 전투력 반영이 빠르다. 해당 연구
  // 구조물이 없으면 그 항목은 false를 돌려 그냥 다음으로 넘어간다.
  bio: [...RESEARCH_TERRAN_BIO_TECH, ...RESEARCH_TERRAN_INFANTRY],
  bio_tank: [
    ...RESEARCH_TERRAN_BIO_TECH,
    ...interleaveResearch(RESEARCH_TERRAN_INFANTRY, RESEARCH_TERRAN_VEHICLE),
  ],
  hellion_tank: [...RESEARCH_TERRAN_HELLION_TECH, ...RESEARCH_TERRAN_CYCLONE_TECH, ...RESEARCH_TERRAN_VEHICLE],
  thor_tank: [...RESEARCH_TERRAN_HELLION_TECH, ...RESEARCH_TERRAN_CYCLONE_TECH, ...RESEARCH_TERRAN_VEHICLE],
  // 화염차 미생산 → 청염 제외. 사이클론은 §91에서 편성에 들어갔으므로 포함.
  mech_macro: [...RESEARCH_TERRAN_CYCLONE_TECH, ...RESEARCH_TERRAN_VEHICLE],
  // 차원 관문·돌진은 전 빌드; 점멸은 추적자 보유 빌드(Aiur는 사다리에서 제외).
  gateway: [...RESEARCH_PROTOSS_GROUND, RESEARCH_PROTOSS_WARPGATE, RESEARCH_PROTOSS_CHARGE, RESEARCH_PROTOSS_BLINK],
  stalker_immortal: [...RESEARCH_PROTOSS_GROUND, RESEARCH_PROTOSS_WARPGATE, RESEARCH_PROTOSS_CHARGE, RESEARCH_PROTOSS_BLINK],
  zealot_archon: [...RESEARCH_PROTOSS_GROUND, RESEARCH_PROTOSS_WARPGATE, RESEARCH_PROTOSS_CHARGE, RESEARCH_PROTOSS_STORM],
  immortal_colossus: [...RESEARCH_PROTOSS_GROUND, RESEARCH_PROTOSS_WARPGATE, RESEARCH_PROTOSS_CHARGE, RESEARCH_PROTOSS_BLINK, RESEARCH_PROTOSS_THERMALLANCE],
  disruptor_ground: [...RESEARCH_PROTOSS_GROUND, RESEARCH_PROTOSS_WARPGATE, RESEARCH_PROTOSS_CHARGE, RESEARCH_PROTOSS_BLINK],
  ling_bane: [...RESEARCH_ZERG_MELEE, RESEARCH_ZERG_LING_SPEED, RESEARCH_ZERG_LING_ADRENAL, RESEARCH_ZERG_BANE_HOOKS],
  roach_ravager: [...RESEARCH_ZERG_MISSILE, RESEARCH_ZERG_ROACH_GLIAL],
  roach_hydra: [...RESEARCH_ZERG_MISSILE, RESEARCH_ZERG_ROACH_GLIAL, RESEARCH_ZERG_HYDRA_SPINES, RESEARCH_ZERG_HYDRA_MUSCLE],
  hydra_lurker: [...RESEARCH_ZERG_MISSILE, RESEARCH_ZERG_HYDRA_SPINES, RESEARCH_ZERG_HYDRA_MUSCLE, RESEARCH_ZERG_LURKER_TALONS, RESEARCH_ZERG_LURKER_RANGE],
  ultra_ling_bane: [...RESEARCH_ZERG_MELEE, RESEARCH_ZERG_LING_SPEED, RESEARCH_ZERG_LING_ADRENAL, RESEARCH_ZERG_BANE_HOOKS, RESEARCH_ZERG_ULTRA_CHITIN, RESEARCH_ZERG_ULTRA_ANABOLIC],
  random_ground: null, // 종족이 정해진 슬롯은 아래 RESEARCH_LADDER_BY_RACE 사용.
};

const RESEARCH_LADDER_BY_RACE = {
  Terran: interleaveResearch(RESEARCH_TERRAN_INFANTRY, RESEARCH_TERRAN_VEHICLE),
  // §69: 프로토스 random_ground도 지상 전반을 뽑으므로 전 빌드 공용인 차원 관문·
  // 돌진·점멸을 붙인다(Aiur는 researchLadderForSlot에서 점멸 제외).
  Protoss: [...RESEARCH_PROTOSS_GROUND, RESEARCH_PROTOSS_WARPGATE, RESEARCH_PROTOSS_CHARGE, RESEARCH_PROTOSS_BLINK],
  Zerg: RESEARCH_ZERG_COMBINED,
};

// §63: 연구 구조물이 빌드 인프라에 없으면 사다리가 첫 항목에서 영원히 멈춘다.
// 종족별 연구 구조물(+프로토스 2레벨 요구조건 트와일라잇)을 재고로 보강한다.
// §91.8 사용자 지시: "포지를 짓는 대신 사이버를 안 올리는 건 치명적. 추적자,
// 용기병 그리고 사이버 올려야 이후 테크가 가능하므로 포지, 사이버 둘 다 필수".
// 사이버네틱스 코어는 프로토스 테크 척추다 — 추적자/용기병(Aiur)뿐 아니라
// 트와일라잇·로보틱스의 전제이기도 하다. 그런데 빌드별 인프라 표에서 사이버를
// 명시한 건 gateway·stalker_immortal 둘뿐이고, zealot_archon·immortal_colossus·
// disruptor_ground 는 없었다 — 즉 중반에 사이버가 파괴되면 아무도 다시 짓지
// 않고 그 슬롯의 테크가 통째로 죽는다. 종족 공용으로 올려 전 프로토스 슬롯이
// 재건 대상으로 삼게 한다. 재건 발주는 §71 래치(한 번 완성된 적 있음) +
// 전제 게이트(관문/차원 관문)를 그대로 받으므로 오프닝에는 간섭하지 않는다.
const RESEARCH_INFRA_BY_RACE = {
  Terran: {},          // 엔베이/아머리는 빌드별 PREFERRED_INFRA가 이미 강제.
  Protoss: { CyberneticsCore: 1, Forge: 1, TwilightCouncil: 1 },
  Zerg: { EvolutionChamber: 1 },
};

// Blizzard's melee AI does not put newly introduced unit IDs into its own
// production queue.  Runtime purchases below preserve the normal economy and
// tech requirements, charge the real costs, and use one cooldown per producer.
//
// `customValue` is a per-unit storage slot index, and the purchase stamps the
// producing structure's slot with the time its cooldown expires.  It must be
// unique per unit type, not per producer type: two entries sharing an index
// share one cooldown on every structure they have in common, so each blocks
// the other.  Goliath and Predator both shipped as 21 and silently contended
// for every Factory.  Slots 26 and 31 are taken by the Torrasque probe marker
// and the script-control release timer, so keep new entries below 26.
// verifyPurchaseCooldownSlots() enforces the uniqueness at build time.
const CAMPAIGN_PURCHASE_BY_UNIT = {
  HotSTorrasque: {
    producer: "Larva", prerequisite: "UltraliskCavern",
    minerals: 300, gas: 200, supply: 6, cooldown: 60, customValue: 19,
  },
  SC2TeamAberration: {
    producer: "Larva", prerequisite: "InfestationPit",
    minerals: 200, gas: 75, supply: 3, cooldown: 45, customValue: 20,
  },
  SC2TeamGoliath: {
    producer: "Factory", prerequisite: "Armory",
    minerals: 150, gas: 50, supply: 2, cooldown: 40, customValue: 21,
  },
  SC2TeamPredator: {
    producer: "Factory", prerequisite: "Factory",
    minerals: 100, gas: 100, supply: 3, cooldown: 35, customValue: 23,
  },
  SC2TeamMedic: {
    producer: "Barracks", prerequisite: "BarracksTechLab",
    minerals: 75, gas: 50, supply: 2, cooldown: 30, customValue: 22,
  },
};

// §87: 직접 훈련 디스패처 표. 멜레 AI의 AISetStock 단독 의존이 §62/§71/§82에서
// 세 번 기각됐으므로, 병력도 유휴 생산 건물에 실제 훈련 명령을 직접 내린다.
//
// index는 합성 카탈로그(liberty.sc2mod → liberty.sc2campaign → swarm.sc2mod →
// swarmmulti.sc2mod → voidmulti.sc2mod)의 CAbilTrain/CAbilWarpTrain InfoArray
// "TrainN" → 커맨드 N-1 규약으로 도출했고, 독립 반증 에이전트가 레이어별 원문
// 재유도로 전수 확인했다(§87 워크플로우). 인덱스가 틀리면 엉뚱한 유닛이 나오거나
// "조용한 무동작"이 되므로, 값을 바꿀 때는 반드시 벤더 레이어를 재유도할 것.
//
// 주의 사항(워크플로우 발견):
// - 맹독충 변태는 liberty의 MorphZerglingToBaneling(CAbilTrain)이 아니다 —
//   voidmulti가 같은 카드 슬롯을 CAbilMorph MorphToBaneling으로 교체했다.
//   CAbilMorph는 커맨드 0=Execute, 1=Cancel.
// - 가시지옥도 같은 패턴: swarm의 LurkerAspectMP가 아니라 voidmulti가 재배선한
//   MorphToLurker다.
// - Disruptor(Train19→18)는 벤더에 void.sc2mod AbilData가 없어 원문 근거가
//   불완전했다(합성 추정). §87.7 20분 계측에서 P10이 Disruptor를 실제 생산해
//   인덱스 18 확정(틀렸다면 무동작이거나 다른 유닛이 나왔을 것).
// - 저글링 Train2는 커맨드 1회에 2기가 나온다(비용 50은 2기 값).
// - minerals/gas는 §63 연구와 같은 용도: 실제 차감은 엔진이 하고, 여기 값은
//   잔고 하한 판정에만 쓰인다. aliases는 부족 비율 계산에 합산할 변형 타입.
const DIRECT_TRAIN_BY_UNIT = {
  // 테란
  Marine:    { group: "Barracks", producer: "Barracks", abil: "BarracksTrain", index: 0, minerals: 50, gas: 0 },
  Marauder:  { group: "Barracks", producer: "Barracks", abil: "BarracksTrain", index: 3, minerals: 100, gas: 25 },
  Hellion:   { group: "Factory", producer: "Factory", abil: "FactoryTrain", index: 5, minerals: 100, gas: 0, aliases: ["HellionTank"] },
  SiegeTank: { group: "Factory", producer: "Factory", abil: "FactoryTrain", index: 1, minerals: 150, gas: 125, aliases: ["SiegeTankSieged"] },
  Thor:      { group: "Factory", producer: "Factory", abil: "FactoryTrain", index: 4, minerals: 300, gas: 200 },
  // §91: 사이클론 = FactoryTrain Train8 → index 7. voidmulti 최종 공장 카드
  // (UnitData.xml LayoutButtons Face="BuildCyclone" AbilCmd="FactoryTrain,Train8")와
  // starcoop ArmyCategoryData의 유닛↔어빌커맨드 명시 바인딩 두 곳에서 유도했고,
  // 같은 방법으로 기존 확정값(전차 Train2→1, 토르 Train5→4, 화염차 Train6→5)이
  // 재현되는 것을 확인했다. 비용은 void→voidmulti 합성값(가스는 150→100 하향).
  Cyclone:   { group: "Factory", producer: "Factory", abil: "FactoryTrain", index: 7, minerals: 150, gas: 100 },
  // 프로토스 (관문/차원 관문 인덱스는 완전히 동일 — 워크플로우 확인)
  Zealot:      { group: "Gateway", producer: "Gateway", abil: "GatewayTrain", index: 0, warpAbil: "WarpGateTrain", warpIndex: 0, minerals: 100, gas: 0 },
  Stalker:     { group: "Gateway", producer: "Gateway", abil: "GatewayTrain", index: 1, warpAbil: "WarpGateTrain", warpIndex: 1, minerals: 125, gas: 50 },
  Sentry:      { group: "Gateway", producer: "Gateway", abil: "GatewayTrain", index: 5, warpAbil: "WarpGateTrain", warpIndex: 5, minerals: 50, gas: 100 },
  HighTemplar: { group: "Gateway", producer: "Gateway", abil: "GatewayTrain", index: 3, warpAbil: "WarpGateTrain", warpIndex: 3, minerals: 50, gas: 150 },
  Immortal:  { group: "Robotics", producer: "RoboticsFacility", abil: "RoboticsFacilityTrain", index: 3, minerals: 250, gas: 100 },
  Colossus:  { group: "Robotics", producer: "RoboticsFacility", abil: "RoboticsFacilityTrain", index: 2, minerals: 300, gas: 200 },
  Disruptor: { group: "Robotics", producer: "RoboticsFacility", abil: "RoboticsFacilityTrain", index: 18, minerals: 150, gas: 150 },
  // 저그 (LarvaTrain 인덱스는 P15 §85.6에서 이미 엔진 검증된 앵커와 일치)
  Zergling:  { group: "Larva", producer: "Larva", abil: "LarvaTrain", index: 1, minerals: 50, gas: 0 },
  Roach:     { group: "Larva", producer: "Larva", abil: "LarvaTrain", index: 9, minerals: 75, gas: 25 },
  Hydralisk: { group: "Larva", producer: "Larva", abil: "LarvaTrain", index: 3, minerals: 100, gas: 50 },
  Baneling:  { group: "Larva", morphFrom: "Zergling", abil: "MorphToBaneling", index: 0, minerals: 25, gas: 25 },
  Ravager:   { group: "Larva", morphFrom: "Roach", abil: "MorphToRavager", index: 0, minerals: 25, gas: 75 },
  LurkerMP:  { group: "Larva", morphFrom: "Hydralisk", abil: "MorphToLurker", index: 0, minerals: 50, gas: 100 },
};

const PREFERRED_INFRA_BY_BUILD = {
  // §63: bio의 Armory는 보병 2레벨 업그레이드 요구조건용.
  bio: { Factory: 1, Starport: 1, EngineeringBay: 1, Armory: 1 },
  bio_tank: { Starport: 1, EngineeringBay: 1, Armory: 1 },
  hellion_tank: { Barracks: 1, Starport: 1, Armory: 1 },
  thor_tank: { Barracks: 1, Starport: 1, Armory: 2 },
  mech_macro: { Barracks: 1, Starport: 1, Armory: 2 },
  gateway: { CyberneticsCore: 1, TwilightCouncil: 1, RoboticsFacility: 1 },
  stalker_immortal: { CyberneticsCore: 1 },
  zealot_archon: { TwilightCouncil: 1, TemplarArchive: 1, RoboticsFacility: 1 },
  immortal_colossus: { RoboticsBay: 1 },
  disruptor_ground: { RoboticsBay: 1 },
  ling_bane: { SpawningPool: 1, BanelingNest: 1 },
  roach_ravager: { SpawningPool: 1, RoachWarren: 1 },
  roach_hydra: { SpawningPool: 1, RoachWarren: 1, HydraliskDen: 1 },
  hydra_lurker: { SpawningPool: 1, HydraliskDen: 1, LurkerDenMP: 1 },
  ultra_ling_bane: {
    SpawningPool: 1, BanelingNest: 1, InfestationPit: 1, UltraliskCavern: 1,
  },
  random_ground: {},
};

// §71: random_ground(종족 고정) 슬롯의 인프라. 빌드별 표가 비어 있어 테크
// 건물이 파괴되면 아무도 재요청하지 않았다(사용자 실관측: P12 저그가 확장만
// 하고 산란못을 다시 안 올림). 종족만 알면 쓰는 핵심 테크를 채운다. 종족
// Random(진짜 무작위)은 빌드 시점에 종족을 몰라 기존처럼 빈 표를 쓴다.
const RANDOM_INFRA_BY_RACE = {
  Terran: { EngineeringBay: 1, Armory: 1 },
  Protoss: { CyberneticsCore: 1 },
  Zerg: { SpawningPool: 1, RoachWarren: 1, HydraliskDen: 1, BanelingNest: 1 },
};

// §87: random_ground(종족 고정) 슬롯의 직접 훈련 세트. 빌드별 선호 표가 비어
// 있어 디스패처가 훈련 호출을 하나도 만들지 않았다(릴리스 설정 P13 프로토스
// 관측: 호출 0개 — 사용자가 불평한 "돈 많아도 조금씩만 뽑는" 상태 그대로).
// RANDOM_INFRA_BY_RACE와 같은 원리로 종족만 알면 뽑을 수 있는 표준 멜레
// 병종만 채운다. 캠페인 유닛은 넣지 않는다(구매 경로는 빌드별 선호 표 소관).
// 종족 Random(진짜 무작위)은 빌드 시점에 종족을 몰라 기존처럼 멜레 AI 단독.
const RANDOM_TRAIN_BY_RACE = {
  Terran: { Marine: 12, Marauder: 6, SiegeTank: 8, Cyclone: 5, Thor: 4 },
  Protoss: { Zealot: 10, Stalker: 12, Immortal: 5 },
  Zerg: { Zergling: 24, Roach: 14, Hydralisk: 12 },
};

// §71: 재건 발주(AIBuild)의 전제 게이트(any-of — 형태 변이 타입 포함).
// 요구조건 미충족 AIBuild는 "조용한 무시"가 아니라 멜레 AI 빌드 관리자를
// 재운다: v1.16.0 첫 계측에서 시작 시점에 전제가 없는 무게이트 발주(병영,
// 히드라굴)를 받은 슬롯 전원이 20분 내내 일꾼·확장·생산 0으로 죽었고,
// v1.15.1 대조군은 전부 정상이었다. 그래서 모든 재건 발주는 ① 그 건물이
// 한 번 완성된 적 있어야 하고(래치 gv_sc2team_InfraSeen — 오프닝 빌드
// 불간섭) ② 아래 전제 중 하나가 완성돼 있어야 나간다.
const REBUILD_PREREQUISITE = {
  Barracks: ["SupplyDepot", "SupplyDepotLowered"],
  EngineeringBay: ["CommandCenter", "OrbitalCommand", "PlanetaryFortress"],
  Armory: ["Factory"],
  Starport: ["Factory"],
  // §105.8(감사 B2): 전 인프라 19종 중 게이트가 없던 것은 Factory 하나뿐이었다
  // (bio 빌드만 Factory를 인프라로 갖는다). 전제는 이미 실전 검증된
  // SCALING_PRODUCTION_PREREQUISITE.Factory와 동일 — 새로운 가정이 없다.
  // 완성 병영 0 상태의 Factory 발주는 §83 실측의 빌드 매니저 영구 정지 패턴.
  Factory: ["Barracks"],
  // §91: 넥서스가 아니라 사이버네틱스 코어를 전제로 둔다. 포지를 §91에서
  // SAFE_OPENING_AIBUILD에 넣자(래치 없이 첫 발주 허용) 전제가 넥서스뿐이라
  // 0분부터 발주됐고, 멜레 AI의 오프닝 테크 순서에 끼어들어 사이버를 밀어냈다
  // — 재계측 6분 시점에 프로토스 6슬롯이 포지 1 / 사이버 0 / 병력 0기였다
  // (같은 시점 수정 전은 포지 0 / 사이버 1 / 병력 4~14기). 어떤 프로토스
  // 빌드에서도 사이버가 포지보다 먼저 올라가므로, 이 전제는 재건 경로를
  // 막지 않으면서 오프닝 간섭만 없앤다.
  Forge: ["CyberneticsCore"],
  CyberneticsCore: ["Gateway", "WarpGate"],
  TwilightCouncil: ["CyberneticsCore"],
  TemplarArchive: ["TwilightCouncil"],
  RoboticsFacility: ["CyberneticsCore"],
  RoboticsBay: ["RoboticsFacility"],
  SpawningPool: ["Hatchery", "Lair", "Hive"],
  // §91: 진화장도 포지와 같은 이유로 산란못 뒤에 세운다(부화장만 전제로 두면
  // 0분 발주가 되어 저글링 타이밍을 밀어낸다).
  EvolutionChamber: ["SpawningPool"],
  BanelingNest: ["SpawningPool"],
  RoachWarren: ["SpawningPool"],
  HydraliskDen: ["Lair", "Hive"],
  LurkerDenMP: ["HydraliskDen"],
  InfestationPit: ["Lair", "Hive"],
  UltraliskCavern: ["Hive"],
};

// These research structures have simple, stable prerequisites.
// AISetStock can ignore their initial request indefinitely, while the old
// InfraSeen latch only permits recovery after a building has already existed.
// Permit a first AIBuild only after the prerequisite gate above is satisfied.
//
// §91: 포지(Forge)와 진화장(EvolutionChamber)을 추가했다. 16분 계측에서
// 프로토스 6슬롯 중 P8·P11은 포지가 0개, P9는 13분에야 1개였고, 포지가 없는
// 슬롯은 프로토스 사다리 9개 항목이 전부 1번에서 죽어 공/방/실드가 16분간
// 0레벨이었다(포지가 있던 P10·P13만 1/1/1). AISetStock 재고 요청만으로는
// 멜레 AI가 무기한 무시한다는 §62/§71의 그 패턴이며, 같은 슬롯의 트와일라잇은
// 멜레 AI가 자기 계획으로 지어서 살아남은 것이 대조가 된다. 두 건물 모두
// 전제(넥서스 / 부화장 계열)가 항상 충족돼 있어 §83의 빌드 관리자 정지
// 위험이 없다 — 그래서 래치 없이 첫 발주를 허용해도 안전하다.
const SAFE_OPENING_AIBUILD = new Set([
  "EngineeringBay", "Armory", "Forge", "EvolutionChamber",
]);

// Blizzard's Zerg melee plan may reach Hive and then indefinitely skip the
// Ultralisk Cavern even while AISetStock requests both the structure and
// Ultralisks.  This one late-tech structure is essential to the selected
// Torrasque build, so reinforce the stock request with an explicit normal
// AIBuild request once its real prerequisite is complete.
const FORCED_INFRASTRUCTURE_BY_BUILD = {
  ultra_ling_bane: [
    { unitType: "UltraliskCavern", prerequisite: "Hive", count: 1 },
  ],
};

// Scales production with completed income bases. `base` is the one-base
// target and `perExpansion` is added for every completed expansion.
const SCALING_PRODUCTION_BY_BUILD = {
  bio: { Barracks: { base: 4, perExpansion: 2 } },
  bio_tank: {
    Barracks: { base: 3, perExpansion: 1 },
    Factory: { base: 2, perExpansion: 1 },
  },
  // §62: 팩토리 강제 증설은 기술실 현실(AI가 3개 안팎만 부착)에 맞춰
  // 확장당 1개로 축소. 대신 팩토리 생산 상한은 두지 않는다(사용자 지시) —
  // AI가 스스로 더 짓는 것은 막지 않는다.
  hellion_tank: { Factory: { base: 3, perExpansion: 1 } },
  thor_tank: { Factory: { base: 3, perExpansion: 1 } },
  mech_macro: { Factory: { base: 3, perExpansion: 1 } },
  gateway: { Gateway: { base: 4, perExpansion: 2 } },
  stalker_immortal: {
    Gateway: { base: 3, perExpansion: 1 },
    RoboticsFacility: { base: 2, perExpansion: 1 },
  },
  zealot_archon: { Gateway: { base: 4, perExpansion: 2 } },
  immortal_colossus: {
    Gateway: { base: 3, perExpansion: 1 },
    RoboticsFacility: { base: 2, perExpansion: 1 },
  },
  disruptor_ground: {
    Gateway: { base: 3, perExpansion: 1 },
    RoboticsFacility: { base: 2, perExpansion: 1 },
  },
  ling_bane: {},
  roach_ravager: {},
  roach_hydra: {},
  hydra_lurker: {},
  ultra_ling_bane: {},
  random_ground: {},
};

const SCALING_PRODUCTION_PREREQUISITE = {
  Barracks: "SupplyDepot",
  Factory: "Barracks",
  Gateway: "Pylon",
  RoboticsFacility: "CyberneticsCore",
};

const RANDOM_SCALING_PRODUCTION_BY_RACE = {
  Terran: {
    Barracks: { base: 2, perExpansion: 1 },
    Factory: { base: 1, perExpansion: 1 },
  },
  Protoss: { Gateway: { base: 4, perExpansion: 2 } },
  Zerg: {},
};

// Non-scaling tech/air-production caps. Scaling structures receive their cap
// from the completed-base formula every production tick.
const FIXED_STRUCTURE_CAPS_BY_BUILD = {
  bio: { Factory: 1, Starport: 1 },
  bio_tank: { Starport: 1 },
  hellion_tank: { Barracks: 1, Starport: 1 },
  thor_tank: { Barracks: 1, Starport: 1 },
  mech_macro: { Barracks: 1, Starport: 1 },
  gateway: { RoboticsFacility: 1, Stargate: 0 },
  stalker_immortal: { Stargate: 0 },
  zealot_archon: { RoboticsFacility: 1, Stargate: 0 },
  immortal_colossus: { Stargate: 0 },
  disruptor_ground: { Stargate: 0 },
  ling_bane: { Spire: 0, GreaterSpire: 0 },
  roach_ravager: { Spire: 0, GreaterSpire: 0 },
  roach_hydra: { Spire: 0, GreaterSpire: 0 },
  hydra_lurker: { Spire: 0, GreaterSpire: 0 },
  ultra_ling_bane: { Spire: 0, GreaterSpire: 0 },
  random_ground: {},
};

const EXPANSION_GATE_INFRA_BY_BUILD = {
  bio: { Factory: 1, Starport: 1 },
  bio_tank: { Starport: 1 },
  hellion_tank: { Barracks: 1, Starport: 1 },
  thor_tank: { Barracks: 1, Starport: 1, Armory: 1 },
  mech_macro: { Barracks: 1, Starport: 1 },
  gateway: { CyberneticsCore: 1, RoboticsFacility: 1 },
  stalker_immortal: { CyberneticsCore: 1 },
  zealot_archon: { TwilightCouncil: 1, TemplarArchive: 1 },
  immortal_colossus: { RoboticsBay: 1 },
  disruptor_ground: { RoboticsBay: 1 },
  ling_bane: { SpawningPool: 1, BanelingNest: 1 },
  roach_ravager: { SpawningPool: 1, RoachWarren: 1 },
  roach_hydra: { SpawningPool: 1, RoachWarren: 1, HydraliskDen: 1 },
  hydra_lurker: { SpawningPool: 1, HydraliskDen: 1, LurkerDenMP: 1 },
  ultra_ling_bane: { SpawningPool: 1, BanelingNest: 1, InfestationPit: 1 },
  random_ground: {},
};

const EXPANSION_TOWN_HALL_BY_RACE = {
  Terran: "CommandCenter",
  Protoss: "Nexus",
  Zerg: "Hatchery",
};

const ALLOWED_GROUND_BY_BUILD = {
  bio: ["Marine", "Marauder", "SC2TeamMedic"],
  bio_tank: ["Marine", "Marauder", "SiegeTank", "SC2TeamMedic"],
  hellion_tank: ["Hellion", "HellionTank", "SiegeTank", "Cyclone", "SC2TeamGoliath", "SC2TeamPredator"],
  thor_tank: ["Thor", "SiegeTank", "Hellion", "HellionTank", "Cyclone", "SC2TeamGoliath", "SC2TeamPredator"],
  mech_macro: ["Thor", "SiegeTank", "Cyclone", "SC2TeamGoliath", "SC2TeamPredator"],
  gateway: ["Zealot", "Stalker", "Sentry"],
  stalker_immortal: ["Stalker", "Immortal"],
  zealot_archon: ["Zealot", "HighTemplar", "Archon"],
  immortal_colossus: ["Stalker", "Immortal", "Colossus"],
  disruptor_ground: ["Zealot", "Stalker", "Disruptor"],
  ling_bane: ["Zergling", "Baneling"],
  roach_ravager: ["Roach", "Ravager"],
  roach_hydra: ["Roach", "Hydralisk", "SC2TeamAberration"],
  hydra_lurker: ["Hydralisk", "LurkerMP"],
  ultra_ling_bane: ["HotSTorrasque", "SC2TeamAberration", "Zergling", "Baneling"],
  random_ground: null,
};

function researchLadderForSlot(slot, protossFaction = "Standard") {
  let ladder = slot.build === "random_ground"
    ? (slot.race === "Random" ? null : RESEARCH_LADDER_BY_RACE[slot.race])
    : RESEARCH_LADDER_BY_BUILD[slot.build];
  if (ladder === undefined) fail(`Missing research ladder for P${slot.slot}: ${slot.build}`);
  // §69: Aiur 파벌은 추적자를 드라군으로 교체하며 점멸 어빌리티를 제거한다
  // (protoss/aiur/UnitData.xml: Stalker AbilArray index 5 removed). 점멸 연구는
  // 무용지물이므로 Aiur 프로토스 슬롯 사다리에서 뺀다. 돌진은 Aiur 질럿이
  // 유지하므로(질럿은 소용돌이만 추가) 그대로 둔다.
  if (ladder && slot.race === "Protoss" && protossFaction === "Aiur") {
    ladder = ladder.filter((entry) => entry.upgrade !== "BlinkTech");
  }
  return ladder;
}

const HOTKEY_PROFILE_SUFFIXES = ["", "_NRS", "_SC1", "_USD", "_USDL"];

// Chosen against the vanilla command cards these buttons are added to:
// Barracks uses A/D/R/G, Factory uses E/W/S/C/T, Larva uses D/V/Z/R/H/F/M/C/U/S,
// Spawning Pool uses M/A. Each key below is free on its own card.
const ROSTER_HOTKEYS = {
  SC2TeamMedic: "C",
  SC2TeamPredator: "P",
  SC2TeamGoliath: "G",
  SC2TeamAberration: "B",
  HotSTorrasque: "K",
  SC2TeamRaptorEvolution: "R",
};

module.exports = {
  HOTKEY_PROFILE_SUFFIXES,
  ROSTER_HOTKEYS,
  researchLadderForSlot,
  MAP_NAME_KO,
  MAP_NAME_EN,
  CAMPAIGN_ASSET_DEPENDENCIES,
  PROTOSS_FACTIONS,
  PROTOSS_FACTION_SENTINEL_MODEL,
  COMBAT_AIR_BY_RACE,
  SUPPORT_AIR_BY_RACE,
  SUPPORT_AIR_CAP,
  SUPPORT_AIR_CAP_OVERRIDES_BY_BUILD,
  supportAirCap,
  GROUND_COMBAT_BY_RACE,
  PREFERRED_STOCK_BY_BUILD,
  STOCK_SQUEEZE_MULTIPLIER,
  PREFERRED_UPGRADES_BY_BUILD,
  RESEARCH_TERRAN_INFANTRY,
  RESEARCH_TERRAN_VEHICLE,
  RESEARCH_PROTOSS_GROUND,
  RESEARCH_ZERG_ARMOR,
  RESEARCH_ZERG_MELEE,
  RESEARCH_ZERG_MISSILE,
  RESEARCH_TERRAN_BIO_TECH,
  RESEARCH_TERRAN_HELLION_TECH,
  RESEARCH_TERRAN_CYCLONE_TECH,
  RESEARCH_PROTOSS_WARPGATE,
  RESEARCH_PROTOSS_CHARGE,
  RESEARCH_PROTOSS_BLINK,
  RESEARCH_PROTOSS_STORM,
  RESEARCH_PROTOSS_THERMALLANCE,
  RESEARCH_ZERG_LING_SPEED,
  RESEARCH_ZERG_LING_ADRENAL,
  RESEARCH_ZERG_BANE_HOOKS,
  RESEARCH_ZERG_ROACH_GLIAL,
  RESEARCH_ZERG_HYDRA_SPINES,
  RESEARCH_ZERG_HYDRA_MUSCLE,
  RESEARCH_ZERG_LURKER_TALONS,
  RESEARCH_ZERG_LURKER_RANGE,
  RESEARCH_ZERG_ULTRA_CHITIN,
  RESEARCH_ZERG_ULTRA_ANABOLIC,
  interleaveResearch,
  RESEARCH_ZERG_TECH_ALL,
  RESEARCH_ZERG_COMBINED,
  RESEARCH_LADDER_BY_BUILD,
  RESEARCH_LADDER_BY_RACE,
  RESEARCH_INFRA_BY_RACE,
  CAMPAIGN_PURCHASE_BY_UNIT,
  DIRECT_TRAIN_BY_UNIT,
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
};
