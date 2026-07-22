// V2 보조 트리거를 melee_only 맵에 주입한다.
//
//   node patch_v2_assist.cjs <map> <plan.json>
//
// plan.json:
//   {
//     "expansion": { "enabled": true, "cap": 4, "period": 60 },
//     "army":      { "enabled": true, "scale": 2.0, "period": 10 },
//     "players":   [ { "runtime": 2, "race": "Terran", "slot": 2 }, ... ]
//   }
//
// players 에는 **보조를 받을 AI 플레이어만** 넣는다. 사람 슬롯은 참가자라
// 밀레 AI가 안 붙으므로 제외해야 한다(옵저버 모드에서는 사람 슬롯도 컴퓨터가
// 되므로 호출부가 포함시킨다).
//
// 쓰는 네이티브는 전부 AI 엔진 조회/기록이다. UnitGroup 생성도, 전체 맵 스캔도,
// 유닛 순회도 없다 — §95 프리즈의 원인이었던 것들이 하나도 없다.
"use strict";
const fs = require("fs");
const { Archive } = require("@jamiephan/stormlib");

const [mapPath, planPath] = process.argv.slice(2);
if (!mapPath || !planPath) {
  console.error("usage: node patch_v2_assist.cjs <map> <plan.json>");
  process.exit(2);
}

function fail(message) {
  console.error(`V2 보조 주입 실패: ${message}`);
  process.exit(1);
}

const plan = JSON.parse(fs.readFileSync(planPath, "utf8"));
const players = Array.isArray(plan.players) ? plan.players : [];
const expansion = plan.expansion || {};
const army = plan.army || {};

// Galaxy fixed 리터럴은 소수점이 있어야 한다.
function fixedLit(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) fail(`fixed 값이 잘못됐습니다: ${value}`);
  return Number.isInteger(n) ? `${n}.0` : String(n);
}

const blocks = [];
const inits = [];

if (expansion.enabled && players.length > 0) {
  const cap = Number(expansion.cap || 4);
  if (!Number.isInteger(cap) || cap < 1) fail(`기지 상한이 잘못됐습니다: ${expansion.cap}`);
  const cases = players.map(
    (p) => `    v2_ExpandOne(${p.runtime}, ${cap});   // P${p.slot} ${p.race}`
  );
  blocks.push(`
trigger gt_v2_expand;

// 주 자원기지 건물 이름을 **런타임 종족**으로 고른다. 로비에서 무작위 종족을
// 고르면 빌드 시점에는 종족을 알 수 없으므로 이름을 못 박을 수 없다.
// PlayerRace 는 "Terr" / "Prot" / "Zerg" 를 돌려준다.
string v2_TownHallFor (int player) {
    string raceName = PlayerRace(player);

    if (raceName == "Terr") { return "CommandCenter"; }
    if (raceName == "Prot") { return "Nexus"; }
    return "Hatchery";
}

// 확장 보조: 좌표를 강요하지 않는다. "본진에서부터 찾아서 확장해라"만 요청하고
// 어디에 지을지는 밀레 AI 가 정한다. V1 §97 이 이 네이티브를 금지한 이유가
// "우리 좌표를 안 지킨다"였는데, V2 는 좌표를 주지 않으므로 그 이유가 없다.
void v2_ExpandOne (int player, int cap) {
    if (AIGetNumEstablishedTowns(player) >= cap) { return; }
    if (!AIHasNearbyOpenExpansion(player)) { return; }
    AIExpand(player, AIGetTownLocation(player, AIGetMainTown(player)), v2_TownHallFor(player));
}

bool v2_expand_Func (bool testConds, bool runActions) {
    if (!runActions) { return true; }
${cases.join("\n")}
    return true;
}

void v2_InitializeExpand () {
    gt_v2_expand = TriggerCreate("v2_expand_Func");
    TriggerAddEventTimePeriodic(gt_v2_expand, ${fixedLit(expansion.period || 60)}, c_timeGame);
}
`);
  inits.push("    v2_InitializeExpand();");
}

const production = plan.production || {};
if (production.enabled && players.length > 0) {
  // 배율을 **정수 퍼센트**로 넘긴다. Galaxy 쪽에서 fixed↔int 변환 네이티브를
  // 쓰지 않으려는 것 — 미선언 네이티브 하나면 맵 스크립트가 통째로 죽는다.
  const percent = Math.round(Number(production.scale || 2) * 100);
  if (!Number.isFinite(percent) || percent < 100) {
    fail(`생산건물 배율이 잘못됐습니다: ${production.scale}`);
  }
  const cases = players.map(
    (p) => `    v2_ProductionOne(${p.runtime}, ${percent});   // P${p.slot} ${p.race}`
  );
  blocks.push(`
trigger gt_v2_production;

// 생산건물 보조: 밀레 AI 가 **이미 1개 이상 완성한 종류만** 개수를 배율만큼
// 올린다. 0개인 종류는 건드리지 않는다 — 그것이 "빌드를 바꾸지 않는다" 는
// 보증이다. 바이오닉 슬롯에 군수공장을 억지로 끼워 넣지 않는다.
//
// **왜 AIBuild 인가.** AISetStock 계열은 세 번 다 무효였다: AISetStockExtra,
// c_stockForced 덧셈(4판), c_stockForced 배율 3배(사용자 실측). V1 §71 이 이미
// 같은 결론을 내려놨다 — "AISetStock 만으로는 밀레 AI 가 비결정적으로 무시한다.
// 명시적 AIBuild 재발주만 확실하다." 병력 배율은 먹히는데 생산 능력이 안 따라오는
// 모순을 풀려면 여기만 강제해야 한다(사용자 판단).
//
// **왜 §83 이 재발하지 않는가.** §83 이 빌드 매니저를 영구 정지시킨 것은
// **전제조건 미충족** AIBuild 였다. 여기서는 c_techCountCompleteOnly 가 1 이상,
// 즉 그 종류를 **이미 완성해서 갖고 있는** 경우에만 발주한다. 병영이 완성돼
// 있다는 것은 보급고가 있다는 증명이므로 전제조건 충족이 구조적으로 보장된다.
// V1 의 InfraSeen 래치("한 번 완성한 적 있음")보다 엄격하다 — 지금 갖고 있어야
// 한다. 전멸하면 우리는 손을 뗀다(재건은 밀레 AI 몫).
//
// 큐 폭주 방지: 이미 예약분(QueuedOrBetter)이 목표에 닿으면 발주하지 않고,
// 한 번에 1개씩만 넣는다.
void v2_StockProduction (int player, string what, int percent) {
    int done = AITechCount(player, what, c_techCountCompleteOnly);
    int queued = AITechCount(player, what, c_techCountQueuedOrBetter);
    int want;

    if (done < 1) { return; }
    want = done * percent / 100;
    if (want <= done) { want = done + 1; }
    // 요청도 같이 남긴다. 무해하고 가끔 반영된다(V1 §87 과 같은 모양).
    AISetStockEx(player, c_townMain, want, what, c_makeDefault, c_stockForced);
    if (queued >= want) { return; }
    AIBuild(player, c_makePriorityTown, AIGetMainTown(player), what, 1, c_nearChokePoint);
}

// 종족은 런타임에 정한다. 로비에서 무작위를 고르면 빌드 시점에 알 수 없다.
void v2_ProductionOne (int player, int percent) {
    string raceName = PlayerRace(player);

    if (raceName == "Terr") {
        v2_StockProduction(player, "Barracks", percent);
        v2_StockProduction(player, "Factory", percent);
        v2_StockProduction(player, "Starport", percent);
        return;
    }
    if (raceName == "Prot") {
        v2_StockProduction(player, "Gateway", percent);
        v2_StockProduction(player, "RoboticsFacility", percent);
        v2_StockProduction(player, "Stargate", percent);
        return;
    }
    v2_StockProduction(player, "Hatchery", percent);
}

bool v2_production_Func (bool testConds, bool runActions) {
    if (!runActions) { return true; }
${cases.join("\n")}
    return true;
}

void v2_InitializeProduction () {
    gt_v2_production = TriggerCreate("v2_production_Func");
    TriggerAddEventTimePeriodic(gt_v2_production, ${fixedLit(production.period || 15)}, c_timeGame);
}
`);
  inits.push("    v2_InitializeProduction();");
}

if (army.enabled && players.length > 0) {
  const scale = fixedLit(army.scale || 2);
  const cases = players.map(
    (p) => `    AISetStockArmyDefaultScale(${p.runtime}, ${scale});   // P${p.slot} ${p.race}`
  );
  blocks.push(`
trigger gt_v2_armyscale;

// 병력 보조: 밀레 AI 가 원하는 병력 목표에 배율만 건다. 유닛 종류도 조합
// 비율도 우리가 고르지 않는다. 네이티브 주석이 "doesn't change current army"라
// 이미 잡힌 목표에는 소급이 안 될 수 있어 주기적으로 다시 건다.
bool v2_armyscale_Func (bool testConds, bool runActions) {
    if (!runActions) { return true; }
${cases.join("\n")}
    return true;
}

void v2_InitializeArmyScale () {
    gt_v2_armyscale = TriggerCreate("v2_armyscale_Func");
    TriggerAddEventTimePeriodic(gt_v2_armyscale, ${fixedLit(army.period || 10)}, c_timeGame);
}
`);
  inits.push("    v2_InitializeArmyScale();");
}

// 캠페인 유닛 훈련. 인덱스는 **우리가 소유한** tools/campaign_data/roster/
// AbilData.xml 의 InfoArray 이름에서 그대로 나온다 (TrainN → 커맨드 N-1,
// ResearchN → N-1). 벤더 레이어 재유도가 필요한 V1 §87 표와 달리 근거가 저장소
// 안에 있고 30줄짜리 파일이므로, 인덱스를 바꿀 일이 있으면 그 파일과 **같이**
// 바꾼다. 한쪽만 바꾸면 조용한 무동작이 된다.
//
// 비용은 잔고 하한 판정에만 쓴다. 실제 차감은 엔진이 하고, 로스터 CUnit 은
// 캠페인 원본을 부모로 삼아 진짜 비용을 갖고 있다(애버레이션만 명시 200/75).
const CAMPAIGN_TRAIN = {
  Terr: [
    // 골리앗: FactoryTrain Train20. 무기고가 있어야 버튼 요구 조건이 풀린다.
    { unit: "SC2TeamGoliath", producer: "Factory", prereq: "Armory",
      abil: "FactoryTrain", index: 19, minerals: 150, gas: 50 },
    // 프레데터: FactoryTrain Train21. 요구 조건이 없는 유닛이라 공장 자체가
    // 조건이다 — 카드가 연결됐는지 보는 대조군이기도 하다.
    { unit: "SC2TeamPredator", producer: "Factory", prereq: "Factory",
      abil: "FactoryTrain", index: 20, minerals: 100, gas: 100 },
    // 의무병: BarracksTrain Train20. 기술실이 붙은 병영이 필요하다.
    { unit: "SC2TeamMedic", producer: "Barracks", prereq: "BarracksTechLab",
      abil: "BarracksTrain", index: 19, minerals: 75, gas: 50 },
  ],
  Zerg: [
    // 토라스크: LarvaTrain Train17. 궁극탑 필요.
    { unit: "HotSTorrasque", producer: "Larva", prereq: "UltraliskCavern",
      abil: "LarvaTrain", index: 16, minerals: 300, gas: 200 },
    // 애버레이션: LarvaTrain Train28. 감염구덩이 필요.
    { unit: "SC2TeamAberration", producer: "Larva", prereq: "InfestationPit",
      abil: "LarvaTrain", index: 27, minerals: 200, gas: 75 },
  ],
};

const campaign = plan.campaign || {};
if (campaign.enabled && players.length > 0) {
  const trainCall = (entry) => {
    const larva = entry.producer === "Larva";
    // 라바는 3개를 남긴다. 전부 쓰면 밀레 AI 의 드론·대군주 생산이 굶는다
    // (V1 §87 이 같은 이유로 쓰는 값). 건물은 남길 이유가 없다.
    const leaveIdle = larva ? 3 : 0;
    // 건물은 현재 작업 뒤에 1개까지만 예약한다(대기열 2). 라바는 명령이 없는
    // 것만 쓴다. 어느 쪽도 밀레 AI 가 걸어둔 명령을 **교체하지 않는다** —
    // 항상 c_orderQueueAddToEnd 다.
    const maxQueue = larva ? 1 : 2;
    // 틱당 상한. 라바는 희소하고 토라스크는 보급 6이라 1기, 공장·병영은 2기.
    const maxIssue = larva ? 1 : 2;
    return `        v2_TrainCampaign(player, "${entry.producer}", "${entry.prereq}", ` +
      `"${entry.abil}", ${entry.index}, ${entry.minerals}, ${entry.gas}, ` +
      `${leaveIdle}, ${maxQueue}, ${maxIssue});   // ${entry.unit}`;
  };
  const cases = players.map(
    (p) => `    v2_CampaignOne(${p.runtime});   // P${p.slot} ${p.race}`
  );
  blocks.push(`
trigger gt_v2_campaign;

// 캠페인 유닛 해금을 이미 건 플레이어. 런타임 ID 1~15 를 쓴다.
bool[16] gv_v2_campaignUnlocked;

// 캠페인 유닛을 테크트리에서 허용한다. 플레이어당 한 번만 돈다.
//
// **왜 런타임에 하는가.** V1 은 이걸 빌드 시점에 설정된 종족으로 깔았다.
// 그런데 V2 런처의 기본 설정은 여덟 슬롯이 전부 Random 이라 빌드 시점에는
// 종족을 알 수 없고, 그러면 한 줄도 안 깔린다. 궁극탑을 지어도 토라스크
// 훈련 명령이 조용히 무효가 되는 것이다 — CLAUDE.md 가 반복해서 경고하는
// 실패 양상이다("미충족 조건은 오류가 아니라 무동작"). 런타임 종족으로
// 판정해야 Random 슬롯이 제 종족의 캠페인 유닛을 받는다.
//
// 토라스크는 HotS 에서 울트라리스크 **진화**라 유닛 허용만으로는 부족하고
// 업그레이드 레벨까지 있어야 한다. AddLevel 은 누적되므로 한 번만 건다.
void v2_UnlockCampaign (int player, string raceName) {
    if (gv_v2_campaignUnlocked[player]) {
        return;
    }
    gv_v2_campaignUnlocked[player] = true;
    if (raceName == "Terr") {
        TechTreeUnitAllow(player, "SC2TeamGoliath", true);
        TechTreeUnitAllow(player, "SC2TeamPredator", true);
        TechTreeUnitAllow(player, "SC2TeamMedic", true);
        return;
    }
    if (raceName == "Zerg") {
        TechTreeUnitAllow(player, "SC2TeamAberration", true);
        TechTreeUnitAllow(player, "HotSTorrasque", true);
        TechTreeUpgradeAddLevel(player, "HotSTorrasque", 1);
    }
}

// 캠페인 유닛 생산.
//
// **왜 훈련 명령인가 (V1 은 구매였다).** V1 은 UnitCreate 로 유닛을 그 자리에
// 만들어 냈다. 그 구현이 §91.11 에서 측정된 사고의 원인이다 — 구매는 보급을
// 우회해서, 보급고 3개(공급량 54)짜리 슬롯이 인구 700 에 병력 266기를 굴렸고
// 그중 250기가 골리앗·프레데터였다. 사용자가 본 "테란 400 vs 프로토스 60~80"이
// 종족 밸런스가 아니라 한쪽만 보급 규칙을 우회한 결과였다.
//
// 로스터는 진짜 CAbilTrain 슬롯을 갖고 있으므로(FactoryTrain Train20/21 등)
// 그냥 훈련 명령을 내리면 된다. 그러면 비용·보급·선행조건·건설시간·알 낳는
// 시간을 **전부 엔진이** 처리한다. 위 우회는 구조적으로 불가능해지고, §89.14
// ("직접 생산도 아니고 — 롤백하라") 의 치환 문제도 해당 없다.
//
// **왜 이게 보조인가 (§104).** 밀레 AI 는 모르는 유닛 ID 를 자기 생산 대기열에
// 절대 넣지 않는다. 그래서 이 명령은 전부 순수한 빈칸 채우기이고, 밀레 AI 의
// 판단을 빼앗지 않는다. 대기열은 교체하지 않고 뒤에만 붙이며, 잔고 하한으로
// 밀레 AI 의 저축을 남긴다.
int v2_TrainCampaign (
    int player,
    string producerType,
    string prereqType,
    string abilLink,
    int commandIndex,
    int mineralCost,
    int gasCost,
    int leaveIdle,
    int maxQueue,
    int maxIssue
) {
    unitgroup producers;
    unit currentUnit;
    int unitIndex;
    int remaining;
    int issued = 0;
    order trainOrder;

    // 선행 건물이 없으면 UnitGroup 을 만들지도 않는다. 대부분의 틱이 여기서
    // 끝나므로 스캔 비용이 실질적으로 0이다(§95 의 교훈).
    if (AITechCount(player, prereqType, c_techCountCompleteOnly) < 1) {
        return 0;
    }
    trainOrder = Order(AbilityCommand(abilLink, commandIndex));
    producers = UnitGroup(producerType, player, RegionEntireMap(), UnitFilter(0, 0, 0, 0), 0);
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
        if (issued >= maxIssue) {
            break;
        }
        remaining -= 1;
        if (!UnitIsAlive(currentUnit)) {
            continue;
        }
        if (UnitOrderCount(currentUnit) >= maxQueue) {
            continue;
        }
        // 잔고 하한(V1 §87 훈련 디스패처와 같은 값). 이걸 남겨야 밀레 AI 가
        // 기술실·확장·일꾼에 쓸 저축을 한다 — §61 에서 하한 없는 구매가
        // 15초마다 은행을 먼저 걷어가 슬롯 하나를 영구 빈곤에 빠뜨렸다.
        // 가스가 필요 없는 유닛은 가스 하한을 보지 않는다(현재 표는 전부 가스를
        // 쓰지만 표가 늘어날 수 있다).
        if (PlayerGetPropertyInt(player, c_playerPropMinerals) < mineralCost + 500 ||
            (gasCost > 0 &&
             PlayerGetPropertyInt(player, c_playerPropVespene) < gasCost + 400)) {
            break;
        }
        // 건설 중인 건물, 보급 부족, 요구 조건 미충족은 전부 여기서 걸린다.
        if (!UnitOrderIsValid(currentUnit, trainOrder)) {
            continue;
        }
        UnitIssueOrder(currentUnit, trainOrder, c_orderQueueAddToEnd);
        issued += 1;
    }
    return issued;
}

// 랩터 진화(저글링 모델·이동속도 업그레이드). 유닛이 아니라 업그레이드라
// 산란못에 실제 연구 명령을 낸다 — SpawningPoolResearch Research10 → 커맨드 9.
// V1 은 TechTreeUpgradeAddLevel 로 그냥 부여했지만 그건 연구 시간도 비용도
// 건너뛴다. 여기서는 엔진이 다 검사한다.
void v2_ResearchRaptor (int player) {
    unitgroup pools;
    unit currentUnit;
    int unitIndex;
    order researchOrder;

    if (TechTreeUpgradeCount(player, "SC2TeamRaptorEvolution", c_techCountQueuedOrBetter) >= 1) {
        return;
    }
    // 버튼 요구 조건이 HaveLair 다. 군락으로 변태하면 대군락은 사라지므로
    // 둘 다 본다(V1 §69 와 같은 이유).
    if (AITechCount(player, "Lair", c_techCountCompleteOnly) < 1 &&
        AITechCount(player, "Hive", c_techCountCompleteOnly) < 1) {
        return;
    }
    // 연구 하한은 §91 연구 규칙과 같다(비용 100/100 + 광물 150 / 가스 100).
    // 훈련 하한보다 낮은 이유도 같다 — 연구는 판당 한 번뿐이라 은행을 못 비운다.
    if (PlayerGetPropertyInt(player, c_playerPropMinerals) < 250 ||
        PlayerGetPropertyInt(player, c_playerPropVespene) < 200) {
        return;
    }
    researchOrder = Order(AbilityCommand("SpawningPoolResearch", 9));
    pools = UnitGroup("SpawningPool", player, RegionEntireMap(), UnitFilter(0, 0, 0, 0), 0);
    unitIndex = UnitGroupCount(pools, c_unitCountAlive);
    for (;; unitIndex -= 1) {
        currentUnit = UnitGroupUnitFromEnd(pools, unitIndex);
        if (currentUnit == null) {
            break;
        }
        if (UnitIsAlive(currentUnit) && UnitOrderCount(currentUnit) == 0 &&
            UnitOrderIsValid(currentUnit, researchOrder)) {
            UnitIssueOrder(currentUnit, researchOrder, c_orderQueueAddToEnd);
            return;
        }
    }
}

// 종족은 런타임에 본다. 로비에서 무작위를 고르면 빌드 시점에 알 수 없다.
// 프로토스에는 캠페인 로스터 유닛이 없다 — 프로토스 콘텐츠는 유닛 추가가
// 아니라 **진영 교체**(아이어/네라짐/정화자/탈다림)이고, 그건 맵 카탈로그
// 패치라 트리거가 할 일이 없다.
void v2_CampaignOne (int player) {
    string raceName = PlayerRace(player);

    v2_UnlockCampaign(player, raceName);
    if (raceName == "Terr") {
${CAMPAIGN_TRAIN.Terr.map(trainCall).join("\n")}
        return;
    }
    if (raceName == "Zerg") {
${CAMPAIGN_TRAIN.Zerg.map(trainCall).join("\n")}
        v2_ResearchRaptor(player);
        return;
    }
}

bool v2_campaign_Func (bool testConds, bool runActions) {
    if (!runActions) { return true; }
${cases.join("\n")}
    return true;
}

void v2_InitializeCampaign () {
    gt_v2_campaign = TriggerCreate("v2_campaign_Func");
    TriggerAddEventTimePeriodic(gt_v2_campaign, ${fixedLit(campaign.period || 15)}, c_timeGame);
}
`);
  inits.push("    v2_InitializeCampaign();");
}

if (plan.hold_wild && plan.hold_wild.enabled) {
  const release = Number(plan.hold_wild.release_seconds ?? 540);
  blocks.push(`
trigger gt_v2_wildhold;

// 0 = 아직 안 잡음, 1 = 잡은 상태, 2 = 해제 완료(더 볼 일 없음)
int gv_v2_wildHoldPhase = 0;

// 우리가 잡은 유닛에만 남기는 표식. 해제할 때 이 표식이 있는 것만 푼다.
// AIIsScriptControlled 만 보고 풀면 나중에 다른 기능이 스크립트 제어를 쓸 때
// 남의 유닛까지 풀어버린다. V2 맵에는 V1 코드가 없어 인덱스 충돌은 없다.
const int c_v2WildHoldMark = 40;

// 선배치된 야생 저그(P15) 전투 유닛의 제어권을 밀레 AI 에게서 뺏는다.
//
// 명령은 내리지 않는다. AISetUnitScriptControlled 하나면 밀레 AI 의 출격 편성에서
// 빠지고, 유닛은 제자리에서 자기방어만 한다. 범용 stop 능력 id 가 벤더 소스에
// 없어서 잘못된 abilcmd 를 쓰면 **조용히 무시**되므로(맵 규칙) 명령을 생략했다.
//
// 잡는 것은 **한 번만** 돈다. 선배치분만 묶고, 이후 밀레 AI 가 생산하는 유닛은
// 처음부터 자율이다. 전체 맵 UnitGroup 스캔은 잡을 때 1회 + 풀 때 1회, 총 2회다
// — §95 의 주기적 스캔 부하와는 성격이 다르다.
//
// 실측(8분, 옵저버): 고정 ON 이면 선배치 122기 중 4기만 움직였고, OFF 면 1분
// 만에 86기가 출격했다.
bool v2_wildhold_Func (bool testConds, bool runActions) {
    unitgroup wildUnits;
    unit currentUnit;
    string unitType;
    int unitIndex;

    if (!runActions) { return true; }
    if (gv_v2_wildHoldPhase == 2) { return true; }

    if (gv_v2_wildHoldPhase == 0) {
        gv_v2_wildHoldPhase = 1;
        wildUnits = UnitGroup(null, 15, RegionEntireMap(), UnitFilter(0, 0, 0, 0), 0);
        unitIndex = UnitGroupCount(wildUnits, c_unitCountAlive);
        for (;; unitIndex -= 1) {
            currentUnit = UnitGroupUnitFromEnd(wildUnits, unitIndex);
            if (currentUnit == null) {
                break;
            }
            unitType = UnitGetType(currentUnit);
            // 건물과 일꾼·보급·유충은 남긴다. 경제까지 얼리면 P15 가 아무것도
            // 못 한다. 실측에서 드론 20기는 전부 정상 채취 중이었다.
            if (!UnitTypeTestAttribute(unitType, c_unitAttributeStructure) &&
                unitType != "Drone" && unitType != "Larva" && unitType != "Egg" &&
                unitType != "Overlord" && unitType != "OverlordTransport" &&
                unitType != "Overseer") {
                UnitSetCustomValue(currentUnit, c_v2WildHoldMark, 1.0);
                AISetUnitScriptControlled(currentUnit, true);
            }
        }
        return true;
    }

    if (AIGetTime() < ${release.toFixed(1)}) { return true; }

    // 해제: 표식이 남은 생존 유닛만 밀레 AI 에게 돌려준다.
    gv_v2_wildHoldPhase = 2;
    wildUnits = UnitGroup(null, 15, RegionEntireMap(), UnitFilter(0, 0, 0, 0), 0);
    unitIndex = UnitGroupCount(wildUnits, c_unitCountAlive);
    for (;; unitIndex -= 1) {
        currentUnit = UnitGroupUnitFromEnd(wildUnits, unitIndex);
        if (currentUnit == null) {
            break;
        }
        if (UnitGetCustomValue(currentUnit, c_v2WildHoldMark) == 1.0) {
            AISetUnitScriptControlled(currentUnit, false);
        }
    }
    return true;
}

void v2_InitializeWildHold () {
    gt_v2_wildhold = TriggerCreate("v2_wildhold_Func");
    // 선배치 유닛이 다 생성된 뒤여야 하므로 맵 초기화 직후가 아니라 조금 뒤에
    // 잡는다. 잡은 뒤에는 해제 시각까지 정수 비교 한 번으로 즉시 반환한다.
    TriggerAddEventTimePeriodic(gt_v2_wildhold, 2.0, c_timeGame);
}
`);
  inits.push("    v2_InitializeWildHold();");
}

if (blocks.length === 0) {
  console.log("V2 보조: 켜진 항목이 없어 주입하지 않았습니다 (순수 밀레 AI).");
  process.exit(0);
}

const archive = Archive.open(mapPath);
try {
  let script = archive.readFileAsString("MapScript.galaxy", "utf8");
  const meleeInit = script.match(/MeleeInitAI\s*\(\s*\)\s*;/);
  if (!meleeInit) {
    fail("MeleeInitAI 호출이 없습니다 — melee_only 로 구운 맵이 맞는지 확인하세요.");
  }
  if (!script.includes("// SC2TEAM_CUSTOM_END")) {
    fail("SC2TEAM 커스텀 블록이 없습니다.");
  }
  // 같은 맵을 두 번 패치하면 트리거가 중복 선언돼 컴파일이 죽는다. 빌더가 항상
  // 새로 굽지만, 안전장치로 막는다.
  if (
    script.includes("v2_InitializeExpand") ||
    script.includes("v2_InitializeArmyScale") ||
    script.includes("v2_InitializeProduction") ||
    script.includes("v2_InitializeCampaign") ||
    script.includes("v2_InitializeWildHold")
  ) {
    fail("이미 V2 보조가 주입된 맵입니다. 맵을 다시 구우세요.");
  }
  // 선언은 커스텀 블록 자리에, 호출은 MeleeInitAI 뒤에 — Galaxy 는 선언 후
  // 사용이라 이 순서를 지켜야 한다.
  script = script.replace("// SC2TEAM_CUSTOM_END", `${blocks.join("")}\n// SC2TEAM_CUSTOM_END`);
  script = script.replace(meleeInit[0], `${meleeInit[0]}\n${inits.join("\n")}`);
  archive.addString("MapScript.galaxy", script, { encoding: "utf8" });
  archive.compact();
} finally {
  archive.close();
}

const what = [];
if (expansion.enabled) what.push(`확장 보조(상한 ${expansion.cap}, ${expansion.period}초)`);
if (army.enabled) what.push(`병력 보조(${army.scale}배, ${army.period}초)`);
if (production.enabled) what.push(`생산건물 보조(${production.scale}배, ${production.period}초)`);
if (campaign.enabled) {
  const units = [...CAMPAIGN_TRAIN.Terr, ...CAMPAIGN_TRAIN.Zerg].length;
  what.push(`캠페인 유닛 생산(${units}종 + 랩터 진화, ${campaign.period}초)`);
}
if (plan.hold_wild && plan.hold_wild.enabled) {
  const release = Number(plan.hold_wild.release_seconds ?? 540);
  what.push(`야생 저그 선배치 병력 고정(${(release / 60).toFixed(0)}분에 해제)`);
}
console.log(`V2 보조 주입: ${what.join(" + ")}`);
if (players.length > 0) {
  console.log(`  대상 ${players.length}명: ${players.map((p) => `P${p.slot}(런타임 ${p.runtime})`).join(", ")}`);
}
