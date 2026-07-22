// MPQ 아카이브 패처: 지역화 문자열·핫키·캠페인 카탈로그 병합·프로토스
// 파벌·보급 상한·적대 장식 소유권.
//
// 게임은 의존성 목록을 DocumentInfo가 아니라 DocumentHeader에서 읽는다.
// 둘 다 패치하지 않으면 의존성이 조용히 무시된다(§50 실측).

const fs = require("node:fs");
const path = require("node:path");

const { fail, CAMPAIGN_DATA_DIR } = require("./util.cjs");
const {
  HOTKEY_PROFILE_SUFFIXES,
  ROSTER_HOTKEYS,
  MAP_NAME_KO,
  MAP_NAME_EN,
  CAMPAIGN_ASSET_DEPENDENCIES,
} = require("./tables.cjs");

function setLocalizedLines(content, replacements) {
  const newline = content.includes("\r\n") ? "\r\n" : "\n";
  const lines = content.split(/\r?\n/);
  const pending = new Map(Object.entries(replacements));
  const updated = lines.map((line) => {
    const separator = line.indexOf("=");
    if (separator < 0) return line;
    const rawKey = line.slice(0, separator);
    const key = rawKey.replace(/^\uFEFF/, "");
    if (!pending.has(key)) return line;
    const prefix = rawKey.startsWith("\uFEFF") ? "\uFEFF" : "";
    const value = pending.get(key);
    pending.delete(key);
    return `${prefix}${key}=${value}`;
  });
  for (const [key, value] of pending) updated.push(`${key}=${value}`);
  return updated.join(newline);
}

function patchCampaignAssetDependencies(archive) {
  const name = "DocumentInfo";
  let content = archive.readFileAsString(name, "utf8");
  if (!/<Dependencies>/i.test(content)) {
    content = content.replace(/<\/DocInfo>/i, "    <Dependencies>\n    </Dependencies>\n</DocInfo>");
  }
  for (const dependency of CAMPAIGN_ASSET_DEPENDENCIES) {
    const filePart = dependency.slice(dependency.indexOf("file:"));
    const prior = new RegExp(
      `\\s*<Value>[^<]*${filePart.replace(/[.*+?^${}()|[\\]\\]/g, "\\$&")}<\\/Value>`,
      "ig",
    );
    content = content.replace(prior, "");
  }
  const lines = CAMPAIGN_ASSET_DEPENDENCIES
    .map((dependency) => `        <Value>${dependency}</Value>`)
    .join("\n");
  content = content.replace(/<Dependencies>/i, `<Dependencies>\n${lines}`);
  archive.addString(name, content, { encoding: "utf8" });
}

// DocumentInfo is the editor-facing list. The running game reads DocumentHeader,
// so patching only DocumentInfo silently does nothing: that is why the campaign
// dependencies added in v1.10.3 never actually loaded and campaign models kept
// rendering as gray placeholder spheres.
//
// Layout after the H2CS magic and version fields:
//   uint32 dependencyCount
//   dependencyCount x NUL-terminated UTF-8 strings, back to back
// The remaining bytes after the last string are map attributes and are preserved.
function patchDocumentHeaderDependencies(archive) {
  const name = "DocumentHeader";
  if (!archive.hasFile(name)) fail("Map has no DocumentHeader");
  const buffer = archive.readFile(name);
  if (buffer.subarray(0, 4).toString("latin1") !== "H2CS") {
    fail("DocumentHeader has an unexpected magic");
  }

  const marker = Buffer.from("bnet:", "utf8");
  const first = buffer.indexOf(marker);
  if (first < 4) fail("DocumentHeader has no dependency strings");
  const countOffset = first - 4;
  const count = buffer.readUInt32LE(countOffset);
  if (count < 1 || count > 64) {
    fail(`DocumentHeader dependency count looks wrong: ${count}`);
  }

  const existing = [];
  let cursor = first;
  for (let index = 0; index < count; index += 1) {
    const end = buffer.indexOf(0x00, cursor);
    if (end < 0) fail("DocumentHeader dependency string is unterminated");
    existing.push(buffer.subarray(cursor, end).toString("utf8"));
    cursor = end + 1;
  }

  // Campaign archives must load before Void/VoidMulti, matching the order the
  // editor writes and the order the existing DocumentInfo patch already uses.
  const merged = [...CAMPAIGN_ASSET_DEPENDENCIES];
  for (const dependency of existing) {
    if (!merged.includes(dependency)) merged.push(dependency);
  }

  const head = buffer.subarray(0, countOffset);
  const tail = buffer.subarray(cursor);
  const countBuffer = Buffer.alloc(4);
  countBuffer.writeUInt32LE(merged.length, 0);
  const strings = Buffer.concat(
    merged.map((dependency) => Buffer.concat([
      Buffer.from(dependency, "utf8"),
      Buffer.from([0x00]),
    ])),
  );
  archive.addBuffer(name, Buffer.concat([head, countBuffer, strings, tail]));
}

function patchLocalization(archive, protossFaction = "Standard") {
  const values = {
    koKR: {
      "DocInfo/Name": MAP_NAME_KO,
      "DocInfo/DescShort": "14슬롯 로컬 전략 AI 대전",
      "DocInfo/DescLong": "런처에서 선택한 사람 및 커스텀 AI 슬롯으로 실행되는 로컬 전용 맵입니다.",
      "Unit/Name/SC2TeamTorrasque": "토라스크",
      "Unit/Name/SC2TeamTorrasqueChrysalis": "토라스크 고치",
      "Unit/Name/SC2TeamAberration": "변종",
      "Unit/Name/SC2TeamGoliath": "골리앗",
      "Unit/Name/SC2TeamPredator": "프레데터",
      "Unit/Name/SC2TeamMedic": "의무병",
      "Upgrade/Name/SC2TeamRaptorEvolution": "랩터 진화",
      "Button/Name/SC2TeamGoliath": "골리앗 훈련",
      "Button/Tooltip/SC2TeamGoliath": "지상과 공중을 모두 공격하는 보행 병기입니다.<n/><n/><c val=\"ffff8a\">공중 공격 시 중장갑에 추가 피해를 입힙니다.</c>",
      "Button/Name/SC2TeamPredator": "프레데터 훈련",
      "Button/Tooltip/SC2TeamPredator": "빠른 근접 기계 유닛입니다. 공격 시 주변 지상 적에게도 피해를 입힙니다.<n/><n/><c val=\"ffff8a\">지상 유닛만 공격할 수 있습니다.</c>",
      "Button/Name/SC2TeamMedic": "의무병 훈련",
      "Button/Tooltip/SC2TeamMedic": "생체 유닛의 생명력을 회복시키는 지원 유닛입니다.<n/><n/><c val=\"ffff8a\">공격할 수 없습니다.</c>",
      "Button/Name/SC2TeamAberration": "변종 생성",
      "Button/Tooltip/SC2TeamAberration": "중장갑에 강한 근접 저그 유닛입니다.<n/><n/><c val=\"ffff8a\">지상 유닛만 공격할 수 있습니다.</c>",
      "Button/Name/SC2TeamRaptorEvolution": "랩터 진화",
      "Button/Tooltip/SC2TeamRaptorEvolution": "저글링이 랩터로 진화합니다.",
      "Button/Name/HotSTorrasque": "토라스크 생성",
      "Button/Tooltip/HotSTorrasque": "거대 근접 저그 유닛입니다. 죽으면 고치에서 부활합니다.<n/><n/><c val=\"ffff8a\">지상 유닛만 공격할 수 있습니다.</c>",
    },
    enUS: {
      "DocInfo/Name": MAP_NAME_EN,
      "DocInfo/DescShort": "Fourteen-slot local strategy AI match",
      "DocInfo/DescLong": "A local-only map configured by the launcher for human and custom AI slots.",
      "Unit/Name/SC2TeamTorrasque": "Torrasque",
      "Unit/Name/SC2TeamTorrasqueChrysalis": "Torrasque Cocoon",
      "Unit/Name/SC2TeamAberration": "Aberration",
      "Unit/Name/SC2TeamGoliath": "Goliath",
      "Unit/Name/SC2TeamPredator": "Predator",
      "Unit/Name/SC2TeamMedic": "Medic",
      "Upgrade/Name/SC2TeamRaptorEvolution": "Raptor Evolution",
      "Button/Name/SC2TeamGoliath": "Train Goliath",
      "Button/Tooltip/SC2TeamGoliath": "Walker that engages ground and air targets.<n/><n/><c val=\"ffff8a\">Deals bonus damage to armored air units.</c>",
      "Button/Name/SC2TeamPredator": "Train Predator",
      "Button/Tooltip/SC2TeamPredator": "Fast melee mech. Each strike also damages nearby ground enemies.<n/><n/><c val=\"ffff8a\">Can only attack ground units.</c>",
      "Button/Name/SC2TeamMedic": "Train Medic",
      "Button/Tooltip/SC2TeamMedic": "Support unit that restores the life of biological units.<n/><n/><c val=\"ffff8a\">Cannot attack.</c>",
      "Button/Name/SC2TeamAberration": "Spawn Aberration",
      "Button/Tooltip/SC2TeamAberration": "Durable melee zerg unit, strong against armored targets.<n/><n/><c val=\"ffff8a\">Can only attack ground units.</c>",
      "Button/Name/SC2TeamRaptorEvolution": "Raptor Evolution",
      "Button/Tooltip/SC2TeamRaptorEvolution": "Evolves Zerglings into Raptors.",
      "Button/Name/HotSTorrasque": "Spawn Torrasque",
      "Button/Tooltip/HotSTorrasque": "Massive melee zerg unit. Revives from a chrysalis when killed.<n/><n/><c val=\"ffff8a\">Can only attack ground units.</c>",
    },
  };
  if (protossFaction === "Aiur") {
    Object.assign(values.koKR, {
      "Unit/Name/Stalker": "용기병",
      "Unit/NamePlural/Stalker": "용기병",
      "Button/Name/Stalker": "용기병 소환",
      "Button/Tooltip/Stalker": "아이어 진영<n/>원거리 공격 보행 병기입니다. 생명력과 공격력이 강화되어 있습니다.<n/><n/><c val=\"ffff8a\">지상 및 공중 유닛을 공격할 수 있습니다.</c>",
    });
    Object.assign(values.enUS, {
      "Unit/Name/Stalker": "Dragoon",
      "Unit/NamePlural/Stalker": "Dragoons",
      "Button/Name/Stalker": "Warp In Dragoon",
      "Button/Tooltip/Stalker": "Aiur Faction<n/>Ranged assault strider. Has enhanced life and attack damage.<n/><n/><c val=\"ffff8a\">Can attack ground and air units.</c>",
    });
  }
  for (const [locale, replacements] of Object.entries(values)) {
    const name = `${locale}.SC2Data\\LocalizedData\\GameStrings.txt`;
    const content = archive.hasFile(name) ? archive.readFileAsString(name, "utf8") : "";
    archive.addString(name, setLocalizedLines(content, replacements), { encoding: "utf8" });
  }
}

// A CButton carries no hotkey and no tooltip of its own: Blizzard's CButton for
// the Marine is an icon and nothing else. The command card resolves the rest by
// string-key convention, Button/Hotkey/<id> out of GameHotkeys.txt and
// Button/Name|Tooltip/<id> out of GameStrings.txt, so a roster button with no
// string is exactly what the player saw -- an icon with no letter and no text.
//
// The suffixes are SC2's alternate hotkey profiles. A player on Grid or Classic
// reads the suffixed key and ignores the bare one, so every profile is written;
// omitting them makes the hotkey work only on the default profile.
function patchHotkeys(archive) {
  const replacements = {};
  for (const [button, key] of Object.entries(ROSTER_HOTKEYS)) {
    for (const suffix of HOTKEY_PROFILE_SUFFIXES) {
      replacements[`Button/Hotkey/${button}${suffix}`] = key;
    }
  }
  for (const locale of ["koKR", "enUS"]) {
    const name = `${locale}.SC2Data\\LocalizedData\\GameHotkeys.txt`;
    const content = archive.hasFile(name) ? archive.readFileAsString(name, "utf8") : "";
    archive.addString(name, setLocalizedLines(content, replacements), { encoding: "utf8" });
  }
}

function mergeCampaignCatalog(archive, sourceFile, feature = "TORRASQUE") {
  const markerName = path.basename(sourceFile, ".xml");
  const targetName = `Base.SC2Data\\GameData\\${path.basename(sourceFile)}`;
  const source = fs.readFileSync(sourceFile, "utf8");
  const match = source.match(/<Catalog>([\s\S]*)<\/Catalog>/i);
  if (!match) fail(`Campaign catalog snippet has no Catalog root: ${sourceFile}`);

  let target = archive.hasFile(targetName)
    ? archive.readFileAsString(targetName, "utf8")
    : `<?xml version="1.0" encoding="utf-8"?>\n<Catalog>\n</Catalog>\n`;
  const begin = `<!-- SC2TEAM_${feature}_${markerName}_BEGIN -->`;
  const end = `<!-- SC2TEAM_${feature}_${markerName}_END -->`;
  const oldBlock = new RegExp(
    `\\s*${begin.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}` +
    `[\\s\\S]*?${end.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`,
    "g",
  );
  target = target.replace(oldBlock, "");
  if (!/<\/Catalog>/i.test(target)) {
    fail(`Target campaign catalog has no Catalog root: ${targetName}`);
  }
  const block = `${begin}\n${match[1].trim()}\n${end}`;
  target = target.replace(/<\/Catalog>/i, `${block}\n</Catalog>`);
  archive.addString(targetName, target, { encoding: "utf8" });
}

function patchNativeTorrasque(archive) {
  const directory = path.join(CAMPAIGN_DATA_DIR, "torrasque");
  for (const name of [
    "AbilData.xml",
    "ActorData.xml",
    "BehaviorData.xml",
    "ButtonData.xml",
    "EffectData.xml",
    "ModelData.xml",
    "RequirementData.xml",
    "RequirementNodeData.xml",
    "UnitData.xml",
    "UpgradeData.xml",
    "ValidatorData.xml",
  ]) {
    mergeCampaignCatalog(archive, path.join(directory, name), "NATIVE_TORRASQUE");
  }
}

function patchNativeCampaignRosterParents(archive) {
  const directory = path.join(CAMPAIGN_DATA_DIR, "native_roster");
  for (const name of ["ActorData.xml", "ModelData.xml"]) {
    mergeCampaignCatalog(
      archive,
      path.join(directory, name),
      "NATIVE_CAMPAIGN_ROSTER",
    );
  }
  mergeCampaignCatalog(
    archive,
    path.join(CAMPAIGN_DATA_DIR, "native_swarm_roster", "ModelData.xml"),
    "NATIVE_SWARM_ROSTER",
  );
}

function patchCampaignRoster(archive) {
  const directory = path.join(CAMPAIGN_DATA_DIR, "roster");
  for (const name of [
    "AbilData.xml",
    "UpgradeData.xml",
    "ButtonData.xml",
    "UnitData.xml",
    "EffectData.xml",
    "WeaponData.xml",
    "ActorData.xml",
    "ModelData.xml",
    "AttachMethodData.xml",
  ]) {
    mergeCampaignCatalog(archive, path.join(directory, name), "CAMPAIGN_ROSTER");
  }
}

function patchProtossFaction(archive, faction) {
  if (faction === "Standard") return;
  const directory = path.join(CAMPAIGN_DATA_DIR, "protoss");
  mergeCampaignCatalog(
    archive,
    path.join(directory, "ModelData.xml"),
    "PROTOSS_FACTION",
  );
  const factionDirectory = path.join(directory, faction.toLowerCase());
  for (const name of [
    "AbilData.xml",
    "BehaviorData.xml",
    "ButtonData.xml",
    "EffectData.xml",
    "ValidatorData.xml",
    "TargetSortData.xml",
    "SoundData.xml",
    "MoverData.xml",
    "TurretData.xml",
    "WeaponData.xml",
    "UnitData.xml",
    "ActorData.xml",
    // §67: 교체 무기용 멜레 공격 업그레이드 참조(없으면 공업이 헛돈다).
    "UpgradeData.xml",
  ]) {
    const source = path.join(factionDirectory, name);
    if (fs.existsSync(source)) {
      mergeCampaignCatalog(archive, source, "PROTOSS_FACTION");
    }
  }
}

function patchSupplyCeiling(archive) {
  const shadowingName = "Base.SC2Data\\GameData\\RaceData.xml";
  const unitDataName = "Base.SC2Data\\GameData\\UnitData.xml";
  // A map-level RaceData.xml shadows the dependency file and removes standard
  // starting units. The map's existing UnitData.xml is already loaded safely;
  // Catalog files may contain mixed object types, so merge CRace overrides
  // there without introducing a shadowing RaceData/GameData file.
  if (archive.hasFile(shadowingName)) archive.removeFile(shadowingName);
  let content = archive.readFileAsString(unitDataName, "utf8");
  for (const raceId of ["Terr", "Prot", "Zerg"]) {
    const prior = new RegExp(
      `\\s*<CRace\\b[^>]*\\bid=["']${raceId}["'][^>]*>[\\s\\S]*?<\\/CRace>`,
      "ig"
    );
    content = content.replace(prior, "");
  }
  // §68: 인구 한도 600 → 800 (사용자 지시 — "인구 800까지 쥐어 짜내야 해").
  const overrides = ["Terr", "Prot", "Zerg"]
    .map((raceId) => `    <CRace id="${raceId}"><FoodCeiling value="800"/></CRace>`)
    .join("\n");
  if (!/<\/Catalog>/i.test(content)) fail("UnitData.xml has no Catalog root");
  content = content.replace(/<\/Catalog>/i, `${overrides}\n</Catalog>`);
  archive.addString(unitDataName, content, { encoding: "utf8" });
}

// 원본 맵에는 감염 저그 장식·경비 유닛(부화장 10, 드론 12, 감염 테란 10 등
// ObjectUnit 44개)이 실수로 "플레이어 14" 소유로 선배치되어 있다. 12인 이하
// 게임에서는 14번 엔진 플레이어가 없어 무소속으로 방치되지만, 슬롯 14를
// 활성화하면 그 슬롯의 AI가 통째로 상속받아 경제와 목표 재고가 왜곡된다.
// 의도된 소유자는 적대 장식 전용 15번(같은 계열 경비 캠프 159개가 이미 15번
// 소유)이므로 빌드할 때마다 15번으로 옮긴다. 같은 원본에는 Player 7 소유
// Overlord 두 기도 있으며, 런타임 슬롯 압축 시 논리 P8에 상속되어 프로토스
// 시작 상태를 오염시킨다. 이 두 기 역시 적대 장식으로 15번에 둔다.
function patchHostileDecorations(archive) {
  const content = archive.readFileAsString("Objects", "utf8");
  let movedP14 = 0;
  let movedP7Overlords = 0;
  const p14Patched = content.replace(
    /(<ObjectUnit\b[^>]*\bPlayer=")14(")/g,
    (_match, head, tail) => {
      movedP14 += 1;
      return `${head}15${tail}`;
    }
  );
  const patched = p14Patched.replace(
    /(<ObjectUnit\b(?=[^>]*\bUnitType="Overlord")[^>]*\bPlayer=")7(")/g,
    (_match, head, tail) => {
      movedP7Overlords += 1;
      return `${head}15${tail}`;
    }
  );
  if (movedP14 > 0 || movedP7Overlords > 0) {
    archive.addString("Objects", patched, { encoding: "utf8" });
  }
  return { movedP14, movedP7Overlords };
}

// §90.9: 야생 저그에 섞여 있던 프로토스 선배치 유닛을 제거한다(사용자 지시
// "P15한테 있는 프로토스 유닛 다 제거해줘. 불멸자가 남아있는 것 같던데").
//
// 원본 맵의 P14/P15 장식에 프로토스 유닛이 섞여 있었다. §90 으로 P15 가 실제
// 저그 로비 플레이어가 된 뒤로는 종족이 맞지 않는 유닛이 더 눈에 띈다.
// 벤더 UnitData 의 `<Race value="Prot"/>` 로 분류해 확정한 목록이며,
// ScourgeMP·DefilerMP·ChangelingZergling 은 저그이므로 남긴다.
//
// P14 는 patchHostileDecorations 가 P15 로 옮기므로 두 소유자를 모두 지운다.
const WILD_ZERG_FOREIGN_UNITS = [
  "Zealot", "Stalker", "Immortal", "Sentry", "AdeptPhaseShift",
];

function patchWildZergForeignUnits(archive) {
  const content = archive.readFileAsString("Objects", "utf8");
  const removed = {};
  const patched = content.replace(/<ObjectUnit\b[^>]*\/>\s*/g, (tag) => {
    const player = /\bPlayer="(\d+)"/.exec(tag);
    const type = /\bUnitType="([^"]+)"/.exec(tag);
    if (!player || !type) return tag;
    if (player[1] !== "14" && player[1] !== "15") return tag;
    if (!WILD_ZERG_FOREIGN_UNITS.includes(type[1])) return tag;
    removed[type[1]] = (removed[type[1]] ?? 0) + 1;
    return "";
  });
  const total = Object.values(removed).reduce((sum, n) => sum + n, 0);
  if (total > 0) {
    archive.addString("Objects", patched, { encoding: "utf8" });
  }
  return { removed, total };
}

// §90: 야생 저그(맵 플레이어 15)에게 1시 본진 자리의 시작 지점을 준다.
//
// 맵에는 StartLoc 이 20개 정의돼 있는데 MapInfo 는 14개만 참조한다. 남는 것
// 하나를 알파 둥지(P15 가 소유한 유일한 Lair = 1시 본진) 좌표로 옮겨서 쓴다.
// 새 ObjectPoint 를 만들지 않으므로 Objects 구조를 건드릴 위험이 없다.
//
// 시작 지점이 없으면(startPoint 0) 승격만으로는 부족하다: 실측에서 밀레 AI가
// 드론·대군주는 뽑았지만 산란못을 끝내 짓지 않아 병력이 0이었다.
// §90.12: 사용자가 배치한 시작 위치를 존중한다.
//
// 처음에는 "P15 의 유일한 Lair" 를 핵심 기지로 가정하고 여분 StartLoc 을 무조건
// 그 좌표로 옮겼다. 그런데 그 Lair 는 3시(242.5, 120.5)에 있고 사용자가 생각하는
// 핵심 기지는 1시(237.5, 240.5)다. 빌더가 사용자의 에디터 편집을 매번 덮어써서
// 밀레 AI 가 3시 해처리를 본진으로 삼았고, 오버로드와 드론이 전부 그쪽으로
// 몰렸다(사용자 실관측 "오버로드를 자꾸 3시에 있는 기지로 던지는 현상").
//
// 규칙: 여분 StartLoc 중 **이미 P15 타운홀 위에 있는 것**을 먼저 쓴다(사용자가
// 의도적으로 올려둔 것이다). 그런 것이 없을 때만 Lair 좌표로 옮긴다(기준 맵을
// 새로 받았을 때의 안전망). 밀레 AI 는 시작 위치에서 가장 가까운 타운홀을
// 본진으로 삼으므로, 시작 위치는 반드시 타운홀 **곁**에 있어야 한다.
//
// 반경은 5.0 이었는데 실측에서 너무 빡빡했다(2026-07-22). 사용자가 1시에 둔
// StartLoc (237.5,240.5) 에서 가장 가까운 P15 해처리 (235.5,232.5) 까지가
// **8.25** 라 사용자 배치가 탈락했고, 폴백이 그 점을 3시 Lair (242.5,120.5) 로
// 옮겼다 — §90.12 가 고치려던 바로 그 증상이 반경 때문에 그대로 재현됐다.
// 그 StartLoc 은 확장 후보 id 52 (238.5,241.5) 에서 1.41 밖에 안 떨어져 있어
// 배치 자체는 정확했다. 기지 하나의 자원 반경이 이보다 넓으므로 10.0 으로 넓힌다.
//
// verify.cjs 가 같은 상수를 import 해서 검사한다. 두 곳에 숫자를 따로 두면
// 조용히 어긋난다.
const WILD_START_ON_HALL_RADIUS = 10.0;

function patchWildZergStart(archive, usedStartPoints) {
  const content = archive.readFileAsString("Objects", "utf8");
  const halls = [];
  for (const match of content.matchAll(/<ObjectUnit\b[^>]*\/>/g)) {
    const tag = match[0];
    if (!/\bPlayer="1[45]"/.test(tag)) continue;
    if (!/\bUnitType="(?:Hatchery|Lair|Hive)"/.test(tag)) continue;
    const [x, y] = /\bPosition="([^"]+)"/.exec(tag)[1].split(",").map(Number);
    halls.push({ x, y, lair: /\bUnitType="Lair"/.test(tag) });
  }
  if (halls.length === 0) fail("Wild Zerg has no town hall in Objects");

  const spares = [...content.matchAll(/<ObjectPoint\b[^>]*\bType="StartLoc"[^>]*\/>/g)]
    .map((match) => match[0])
    .filter((tag) => !usedStartPoints.has(Number(/\bId="(\d+)"/.exec(tag)[1])));
  if (spares.length === 0) fail("No spare StartLoc available for the Wild Zerg slot");

  const distanceToHall = (tag) => {
    const [x, y] = /\bPosition="([^"]+)"/.exec(tag)[1].split(",").map(Number);
    return Math.min(...halls.map((h) => Math.hypot(x - h.x, y - h.y)));
  };

  // 문서 순서상 첫 번째가 아니라 **가장 가까운** 것을 고른다. find 를 쓰면
  // Objects 안의 등장 순서가 결과를 바꾸는데, 그건 사용자 편집과 무관한 값이다.
  let placed = null;
  let placedDistance = Infinity;
  for (const tag of spares) {
    const distance = distanceToHall(tag);
    if (distance <= WILD_START_ON_HALL_RADIUS && distance < placedDistance) {
      placed = tag;
      placedDistance = distance;
    }
  }
  if (placed) {
    return {
      startPoint: Number(/\bId="(\d+)"/.exec(placed)[1]),
      position: /\bPosition="([^"]+)"/.exec(placed)[1],
      moved: false,
    };
  }

  const lair = halls.find((h) => h.lair) ?? halls[0];
  const position = `${lair.x},${lair.y},0`;
  const spare = spares[0];
  const relocated = spare.replace(/\bPosition="[^"]+"/, `Position="${position}"`);
  archive.addString("Objects", content.replace(spare, relocated), {
    encoding: "utf8",
  });
  return {
    startPoint: Number(/\bId="(\d+)"/.exec(spare)[1]),
    position,
    moved: true,
  };
}

module.exports = {
  setLocalizedLines,
  patchWildZergStart,
  WILD_START_ON_HALL_RADIUS,
  patchWildZergForeignUnits,
  WILD_ZERG_FOREIGN_UNITS,
  patchCampaignAssetDependencies,
  patchDocumentHeaderDependencies,
  patchLocalization,
  patchHotkeys,
  mergeCampaignCatalog,
  patchNativeTorrasque,
  patchNativeCampaignRosterParents,
  patchCampaignRoster,
  patchProtossFaction,
  patchSupplyCeiling,
  patchHostileDecorations,
};
