# 아카이브: V1 MapScript AI 계층 규율 (§60–§104)

**이 계층은 현재 플레이에 쓰이지 않는다.** 사용자는 V3(`start_custom_ai_v3.cmd`)만
플레이한다. V1 런처(`start_custom_ai.cmd`)의 AI 계층 — MapScript 주기 트리거로 돌던
생산·연구·공급·확장·전투·구매 시스템 — 전체가 여기 보존된다.

V1을 되살리려면 이 문서가 출발점이다. **V3 작업에는 적용되지 않는다.**

살아 있는 것과 죽은 것:

| 계층 | 상태 |
| --- | --- |
| 맵·MapInfo·슬롯·팀·보급·캠페인 데이터 빌더 | **살아 있음** — V3가 `melee_only=True`로 그대로 씀. [`../rules/map-layer.md`](../rules/map-layer.md) |
| P15 승격(MapInfo control·StartLoc·player_setups) | **살아 있음** — V3 공용. [`../../v3/docs/wild-zerg.md`](../../v3/docs/wild-zerg.md) |
| MapScript AI 트리거(아래 전부) | **죽음** — `melee_only=True`가 끈다 |
| `tools/galaxy/hostile_wild_ai.galaxy` / `hostile_wild_idle.galaxy` | **죽음** — V3는 단발 부트스트랩으로 대체 |
| `sc2team/strategy_controller.py` 및 비콘 브릿지 | **죽음** — V3에 외부 컨트롤러 없음 |

아래 내용은 원문 그대로 보존한다. 각 항목은 실제로 깨뜨려서 배운 것이며, 다시 만든다면
같은 함정이 그대로 있다.

---

## 생산 스티어링

- Never cap or freeze army production (user directive, §68): `AISetStock` army targets are
  the ratio tables × `STOCK_SQUEEZE_MULTIPLIER` (unreachable on purpose, so the melee AI
  produces to the supply ceiling), and the old `saveForExpansion` production freeze must
  stay removed — `verify()` fails the build if the identifier reappears. Attack-timing
  stock sidecar stays at 1× (readiness is clamped by `MAX_ATTACK_POWER` anyway).

- **The production trigger processes one player per fire, not all of them** (§95).
  `sc2team_ProductionSteering_Func` used to run every custom AI's economy/production/
  purchase/research in a single 15s call — 1,121 full-map `UnitGroup` creations per fire on
  the release 12-AI config, 365 of them unconditional, all synchronous on the SC2 simulation
  thread. That is the user-reported periodic freeze (measured worst stall 1,637 ms). Each
  player now has its own `sc2team_SteerP<N>()` and the trigger period is
  `12 / <player count>` so one full cycle is always 12 game seconds regardless of slot
  count — a fixed 1s period would make a 2-player game run each player 7.5× more often than
  before and silently change production and research rates. Each turn begins with
  `sc2team_RefreshCounts(player)`, one pass that tallies every type into
  `gv_sc2team_CountAll`/`CountDone`; the five public `sc2team_Count*` helpers and
  `sc2team_EconomyWorkerTarget` read those arrays. **Every accessor must keep its `*Live`
  full-scan fallback** for an unready cache or a type missing from the build-time table — a
  silent 0 there is the §83/§91.10 failure mode, and `verify()` counts the fallback paths
  per accessor because a guard that only checked "the string appears somewhere" missed
  deleting one of the two. Galaxy needs declaration before use, so
  `sc2team_TryBuildTerranAddon` and `sc2team_EconomyWorkerTarget` sit after the cache
  accessors.

- Army production is driven by the §87 direct-train dispatcher, not by `AISetStock` alone:
  `AISetStock` requests stay (harmless, occasionally honored) but the guaranteed path is
  direct `UnitIssueOrder` train/warp/morph commands on completed producers every 15s tick —
  the same measured conclusion as §62 addons, §71 infrastructure, and §63 research. Rules
  the dispatcher must keep: `c_orderQueueAddToEnd` only (never replace a melee AI queue),
  per-producer queue cap (2 buildings / 1 larva), the same bank floors as
  purchases/research (skip the gas floor for gas-free units), reserve one addon-capable
  producer per type per tick (or §82 addon orders starve forever — they need an idle
  producer), leave 3 larvae unspent for melee-Zerg Drone/Overlord production, and never
  target the human slot. Command indexes live in `DIRECT_TRAIN_BY_UNIT`. `verify()` binds
  every per-player call to the table. `random_ground` slots with a fixed race use
  `RANDOM_TRAIN_BY_RACE` (their per-build table is empty — without this they get zero
  dispatcher lines) and random_ground Terran joins the §82 bio/factory addon plans; the
  human-slot train ban carries the same `observer_mode` exemption as the §63 research ban.
  The per-tick spend order must stay **train → purchase → research**: all three share the
  same bank floors, so order is priority, and putting the uncapped multi-buy purchases first
  drains gas to the *purchase* floor every tick, permanently starving any standard unit with
  a higher gas floor — measured as five mech/thor slots producing zero SiegeTanks/Thors
  while only the purchase-free bio_tank slot built tanks.

- Cyclone is `FactoryTrain` command index 7 (InfoArray `Train8`), 150/100, supply 3, with
  the Mag-Field Accelerator (`CycloneLockOnDamageUpgrade`) at `FactoryTechLabResearch`
  index 9. It is in the three mech builds and random_ground Terran, deliberately not in
  `bio_tank` (2–3 Factories there would make it compete with Siege Tanks). Engine-verified
  against a Siege Tank/Thor control: a wrong train index is a silent no-op.

## 인프라 재건과 AIBuild

- Infrastructure/tech structures are rebuilt by explicit `AIBuild` reorders whenever their
  count drops below target (§71): `AISetStock` alone is nondeterministically ignored by the
  melee AI (Ultralisk Cavern precedent; live-game evidence: P3 rebuilt, P4 never did).
  `random_ground` slots with a fixed race use `RANDOM_INFRA_BY_RACE`.

- An unmet-prerequisite `AIBuild` is NOT a silent no-op: issued every tick before the melee
  plan has built that structure once, it permanently stalls the player's build manager —
  measured in §83 (every slot with an invalid opening order produced zero workers/army/
  expansions for 20 game-minutes; the v1.15.1 control was healthy). Every rebuild order
  therefore needs the per-player `gv_sc2team_InfraSeen` latch (structure completed once) AND
  an any-of `REBUILD_PREREQUISITE` gate listing every morph state of the prerequisite
  (SupplyDepot/SupplyDepotLowered, Hatchery/Lair/Hive, Gateway/WarpGate, CC/Orbital/PF).
  `SAFE_OPENING_AIBUILD` (Engineering Bay, Armory — §81) may skip the latch but never the
  gate. Never reintroduce an ungated or latch-free `AIBuild`.

- Adding a structure to `SAFE_OPENING_AIBUILD` waives the "completed once" latch, which
  makes it a **turn-zero** order — so its `REBUILD_PREREQUISITE` must be a structure that
  appears *after* the opening, not one that always exists. §91 added Forge with prerequisite
  `Nexus` and measured the result: at six minutes every Protoss slot had a Forge, **no
  Cybernetics Core, and zero army** (control: no Forge, a Cybernetics Core, 4–14 army). The
  prerequisite is now `CyberneticsCore` (and Evolution Chamber's is `SpawningPool`).

## 테란 애드온

- Terran addons are attached structures, so `AIBuild` cannot create them and `AISetStock`
  can be ignored. §82 directly orders only completed, idle, placement-valid producers with
  their native `*AddOns` ability, at most once per player per 15-second tick. Bio receives
  one Barracks Tech Lab then reactors; tank/mech factories receive Tech Labs; enabled
  support air receives one Starport Tech Lab. Never replace a busy production queue to add
  an addon.

## 연구

- AI weapon/armor **and tech** upgrades come from the §63/§69 research trigger: direct
  `UnitIssueOrder` research orders on idle research structures, one per player per 15s tick,
  with `TechTreeUpgradeCount` queued-or-better dedup, a previous-level gate, an optional
  `prerequisiteStructure` gate (§69: empty = ignore, "Lair" also satisfied by Hive — needed
  because the function returns true even on an engine-rejected unmet-requirement order and
  would otherwise starve later ladder entries), and the same bank reserve as purchases
  (minerals ≥ cost + 500, gas ≥ cost + 400). The Protoss faction is threaded to the ladder
  so Aiur drops Blink but keeps Charge. The melee AI does not research here on its own, and
  `AISetStock` requests are not a substitute (§62 addon precedent). Never emit research
  lines for the human slot without the `research_probe` flag; `verify()` enforces both.

- The research trigger's bank reserve is deliberately **smaller** than the purchase/train
  reserve (§91: minerals ≥ cost + 150, gas ≥ cost + 100). It must not be raised back to the
  purchase floor: the per-tick spend order is train → purchase → research, the train
  dispatcher drains the bank to *its* floor (Marauder gas 25 + 400 = 425), and the old
  research floor was higher (100 + 400 = 500), so research could never fire — measured as
  five custom_ai Terran slots at 0–1 upgrade levels after 16 game-minutes while a pure
  melee-AI control slot was equal or better. The §61 bank-drain that motivated the large
  reserve was caused by *uncapped multi-buy purchases*; research is hard-capped at one per
  player per tick, so it cannot reproduce it.

- Terran research ladders put tech upgrades (Stimpack/Combat Shield/Concussive, Infernal
  Pre-igniter, Mag-Field Accelerator) **before** the weapon/armour ladder (§91). The ladder
  issues one research per player-tick and weapon/armour levels are serialised by their
  previous-level gate, so tech placed behind twelve weapon/armour entries is never even
  attempted. A ladder entry whose research structure does not exist returns false and falls
  through, so a missing Tech Lab costs nothing.

## 캠페인 유닛 구매

- New campaign unit IDs are purchased by Galaxy because Blizzard melee AI ignores unknown
  IDs. Preserve real resource/supply/tech checks and producer cooldowns.

- A campaign purchase's `customValue` is a unit storage slot index stamped on the
  *producing structure*, so it must be unique per unit type, never per producer type. Two
  entries sharing an index share one cooldown on every structure they have in common and
  silently throttle each other; Goliath and Predator both shipped as 21. Slots 26, 30 (§70
  mission hold), and 31 (script-control release) are taken.
  `verifyPurchaseCooldownSlots()` enforces this.

- Campaign purchases must keep the bank reserve (minerals ≥ cost + 500, gas ≥ cost + 400,
  rechecked after **every** buy — §87 made purchases multi-buy) and the lowest-ratio-first
  bank claim. Without the reserve the 15s purchase tick skims the bank before the melee AI
  can save for tech labs, Armory, workers, or expansions, and a slot that loses the early
  worker race locks into permanent poverty (§61: P5 bought 49 Predators and built nothing
  else for 16 minutes). The old one-purchase-per-tick cap and the §62 cross-pool gate are
  deleted (§87, user directive — the cap forced 4 units/min regardless of Factory count):
  `verify()` fails the build if `meleeWorstRatio` reappears. Larva purchases keep a per-tick
  `maxCount` (purchases consume the larva, so an uncapped tick would erase the larva pool
  and starve Drones/Overlords); `verify()` enforces that marker too.

## 보급 지원

- **Supply headroom is `c_playerPropSuppliesMade` minus `c_playerPropSuppliesUsed`, never
  `c_playerPropSuppliesLimit`** (§91.10). `SuppliesLimit` is the *ceiling* the cap may rise
  to — on this map the CRace `FoodCeiling` of 800 — not the supply your structures currently
  provide. The original §88 gate read `limit < 800 && limit - used < 24`, which made both
  terms permanently false, so **supply support never executed once between §88 and §91**: no
  proactive Pylon, no proactive Supply Depot, no Orbital `SupplyDrop`. Blizzard's own test
  is `SuppliesUsed > SuppliesMade` (`starcoop/LibCOMU.galaxy:12962`). The `made < ceiling`
  term stays — that is the real "stop spamming at max supply" guard. The same swap was in
  **three** places with two opposite symptoms (§91.11): the §88 gate and the P15 Overlord
  gate were permanently *closed* by it, while the campaign-purchase affordability check
  (`used + cost > limit`) was permanently *open* — that one let purchased units ignore
  supply entirely, measured as a `mech_macro` slot running **266 army at 700 supply off
  three Supply Depots**. The user-reported "Terran 400 vs Protoss 60–80" was that bypass,
  not race balance. In non-comment code `c_playerPropSuppliesLimit` may be read **exactly
  once** — the `made < ceiling` guard — and `verify()` counts the occurrences.

- Supply support (§88): the melee AI's depot/pylon construction cannot keep up with the §87
  dispatcher, so custom_ai Terran slots get a proactive `AIBuild` SupplyDepot plus an Orbital
  Command `SupplyDrop` calldown (ability `SupplyDrop`, Execute index 0, energy 50, permanent
  +8 — cast once per un-buffed completed depot, at most one per player-tick), and Protoss
  slots get a proactive `AIBuild` Pylon. The block-detection gate (`sc2team_SupplyBlocked`:
  used ≥ 32, limit < 800, headroom < 24) must stay: without the used≥32 floor the orders
  interfere with the opening (§83 risk), and without the limit<800 ceiling they spam at max
  supply. Supply orders keep the §83 completed-once gate, an in-flight cap of 2, run
  **before** the train dispatcher (a supply-blocked tick voids every train order), and never
  target the human slot.

- **Never take a shared resource the melee AI needs.** Orbital Command energy is the worked
  example: our Supply Drop consumed every 50 the moment it regenerated, so the melee AI could
  never afford Scanner Sweep or a MULE. The rule is "spend only above 100", i.e. leave its
  half untouched.

## 확장

- Expansion attempts that fail the 90s check blacklist their target area (4 most recent per
  player, 300s, radius 15) so the next cycle picks a different free mineral cluster; a null
  candidate sets the 180s backoff instead of looping. Both exist because the nearest-free-
  cluster picker otherwise retries one doomed spot forever (§68, user-observed worker trains).

- **Expanding requires raising the town-hall produce cap, not just allowing the unit** (§96).
  Two independent lines blocked every expansion from §68 until §96: the branch's
  `TechTreeUnitAllow(..., true)` was overwritten three lines later by the unconditional
  `TechTreeUnitAllow(..., canExpand)` (false unless all town halls are dead, or rich Zerg),
  and `townHallCap` was set to `sc2team_CountAllProduction(player, <hall>)` — the count you
  already have, so "one more" was never permitted, dropping to 0 once a Command Center
  morphed to an Orbital or a Hatchery to a Lair. Measured: 13 slots stuck at one base for a
  whole 8-minute run; after the fix every slot passed two bases and four reached three.
  Grant expansion by setting `canExpand = true` **and**
  `townHallCap = townHallTypeCount + 1` inside the branch, and call `TechTreeUnitAllow`
  exactly once. `verify()` fails the build if a branch calls `TechTreeUnitAllow(..., true)`
  directly or if the `+ 1` cap raise disappears. The 5-base ceiling (`expandBlocked`) is the
  intended limit.

- **The expansion allowance must be applied before the direct build order** (§98).
  `sc2team_TryBuildExpansionAt` picks its worker with `UnitOrderIsValid`, which resolves
  *immediately*, so emitting `TechTreeUnitAllow`/`TechTreeSetProduceCap` after it means the
  check always sees the previous tick's "town hall forbidden" state: the direct build never
  fires, while `townHallCap + 1` still opens and the melee AI spends it beside its own main.
  That is the measured cause of the user-reported "expansion is weak but a second and third
  Nexus keep appearing at the main" — 10 new town halls with 7 on-candidate before the fix,
  31–37 with 30–35 on-candidate after. The identical ordering was harmless in the pre-§97
  `AIExpand` path because that is an *asynchronous* request, so a marker-presence check
  cannot catch this regression; `verify()` compares the two positions inside each slot's
  steer function. Expansion is also two-stage: the builder gets a move order with the cap
  **closed**, and the allowance opens only once it is within 6 of the target
  (`sc2team_TryStageExpansionWorker` → `sc2team_ExpansionBuilderAtTarget`), because the
  window otherwise equals the walk and this map's expansions run 56–204 away. Never raise
  `townHallCap` during the move stage, never gate the move stage's cancel on
  `UnitOrderCount > 0` (arriving *is* zero orders — that inverted test cut expansions
  37→12), and stamp the staged worker with cv22 as well as cv20 or
  `sc2team_ReleaseEconomyHarvestWorkers` never returns script control. The duplicate block
  tests Voronoi attribution **first** and only then a 10.0 crowding radius; 14.0 permanently
  closed candidate 34, a legitimate separate base 13.15 from P12's start hall. A residual
  1–2 melee-AI town halls per game remain by user decision.

## 유닛 제어 / 방어 지원 (`unit_control` 플래그, 기본 off)

- Units on a defense/support mission (unit custom value 30 = hold-until time, §70) must stay
  skipped by the opcode 10/11 attack broadcasts; without that skip the 45s attack cadence
  overwrites every support march and defense order (`c_orderQueueReplace` on the whole ground
  army), which is exactly the user-observed "nobody ever helps". The support dispatcher must
  never reintroduce the blanket "damaged this tick" helper exclusion — in a late-game 7v7
  that excludes everyone; only helpers whose own town hall is being hit are excluded, and two
  helpers go per critical threat.

- The map-side home-defense trigger (`gt_sc2team_HomeDefense`, §70) registers only for real-
  game bridges (`strategy_bridge && !bridge_probe`), never commands the human slot, and bakes
  team membership as build-time literals (`sc2team_PlayerTeam`). `verify()` enforces all three.

- The Galaxy control window (20s) is deliberately shorter than the Python re-dispatch
  cooldown (45s) — when the two were equal, the next dispatch refreshed control before it
  ever expired and units never returned to the melee AI (§105.5, audit finding A1);
  `verify()` fails the build if the inequality is broken again.

- The Python controller cannot issue ordinary `RequestAction` commands for Computer-owned
  units. It moves a human-owned invisible carrier to encoded coordinates; generated Galaxy
  unit-order events decode them. Ground attack: `X = 100 + opcode`, `Y = 100 + runtime
  player ID`. Ally support: destination carried directly, helper runtime ID in the
  hundredths of X.

## V1 P15 야생 저그 (§88–§93)

**V3는 이 컨트롤러를 쓰지 않는다.** 구조적 승격(§90/§93)만 공용이며 그쪽은
[`../../v3/docs/wild-zerg.md`](../../v3/docs/wild-zerg.md)에 있다.

- §88: (1) `sc2team_HostileWildTrainLarva` stamps larva custom value **28** with the tick
  time and skips already-stamped larvae — the Overlord/worker/army blocks otherwise overwrite
  each other's same-tick `c_orderQueueReplace` orders on the same larvae, which was the
  measured cause of "0 new Overlords in 20 minutes" (custom value 27 remains the raid return
  time). (2) Destroyed nests are rebuilt: anchor positions are remembered (initial 16 + later
  expansions, dedup radius 20), and a missing anchor gets the nearest Drone sent to rebuild a
  Hatchery — alpha (1 o'clock) first, one attempt in flight, 180s deadline then retry.
  (3) The alpha nest evolves like a melee AI: InfestationPit (ZergBuild 8) → Hive
  (`UpgradeToHive` 0) → UltraliskCavern (ZergBuild 7) → Ultralisk training (LarvaTrain 6).

- §89 (user directive: "remove every army cap, produce like crazy; only the 7-minute
  **attack** ban stays"): army composition caps (`desiredRoaches`/`desiredHydras`) and the
  roach/hydra unlock timers are **deleted**. Unit mix comes from a tick-rotation selector
  (hydra/roach/zergling every 3 ticks, alpha trains Ultralisks every other tick once a cavern
  exists), with every remaining larva ordered each tick. Development is decoupled from the
  420 s attack truce: expansion moved out of the `active` gate to its own 240 s gate, local
  macro hatcheries are for **every** economy nest (2 tight anchors radius 14, alpha 5, from
  120 s, placement validated over 5 candidate offsets 7-13 — an unvalidated point silently
  drops the order), tech-building timers are 60/120/180 s, alpha tech chain 240 s, worker
  top-up capped at 2/tick, overlord cap 8/tick with threshold 32, alpha spines 6, two
  concurrent rebuild slots picking the missing site **closest to a surviving nest** (distant
  rebuild marches die crossing 12 AI armies; builder stamped cv29).

- §89.6 order hygiene: never re-issue harvest to a drone that already has an order — the old
  code drove every nearby drone onto the single nearest mineral patch every tick (user-
  observed clumping) and cancelled any drone walking to a build site. Only idle drones are
  assigned, spread across patches by index. Construction orders stamp the builder with custom
  value 29 for 45 s and the nest issues no new construction until it expires. Watch trigger
  cost: P15 runs every 10 s over every nest, and a Galaxy trigger that exceeds its operation
  budget aborts mid-run, silently taking the whole nest-management loop with it — no full-map
  scan inside a per-nest or per-unit loop.

- §89.9 truce integrity: defensive response uses attack-move, which chases acquired targets,
  so a fleeing scout worker will lead the garrison to an enemy main. Every defensive order
  must stamp a return time on custom value 27 (15 s during the truce, 30 s after), and
  `sc2team_HostileWildLeashStrays` must keep running before 420 s to send home any combat
  unit not stamped as home this tick (custom value 24, written by `HomeCount`).

- Worker training must stay **before** the army block and **outside** any else-if chain with
  it: unbounded army training in a chain never reaches the worker branch, and a nest that
  loses its miners eventually cannot produce army either.

- P15 keeps a per-tick bank top-up (minerals and gas). The reason is not that the one-time
  50,000 grant fails — it works, measured — but that uncapped production spends over 10,000
  minerals a minute.

- §93: `wild_zerg=false` gives the map `hostile_wild_idle.galaxy`, whose only order is
  `DroneHarvest` on drones that have no order. `verify()` fails the build if any of
  `HOSTILE_WILD_IDLE_BANNED` (TrainLarva/BuildEconomy/TryExpand/TryRaid/`LarvaTrain`/
  `ZergBuild`/`TechTree*Allow(15,`/`PlayerModifyPropertyInt(15,`) is still in
  `MapScript.galaxy`. Never add a `TechTree*Allow` call to the idle controller.
