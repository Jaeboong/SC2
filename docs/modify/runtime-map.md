# Modifying the runtime map

## Scope

Use this guide for changes to slots, starts, alliances, MapInfo, Galaxy triggers, production restrictions, economy rules, unit catalog overrides, map naming, full vision, or supply.

## Source and generated artifacts

The production input is:

```text
maps/generated/europe-melee-2-7v7-rich-50000-fixed-teams.SC2Map
```

The main generated output is:

```text
runtime/maps/europe-melee-custom-ai-v1.25.0.SC2Map
```

`build_runtime_map()` writes `runtime/custom_ai_active.json` by default for a
real launcher build. Verification callers must pass `active_config_file=` with
a probe-specific `.json` path; otherwise a successful probe can leave the
release active configuration describing the last test fixture.

Do not hand-edit the runtime output. Changes disappear on the next launch. Modify the builder (see the module map below), the Python configuration/mapping layer, or—only when the common geometry/resource base itself must change—the fixed-team source-map build pipeline.

## Builder modules

`tools/build_custom_runtime_map.cjs` is the CLI entry and orchestration order only.
The work lives in `tools/build/*.cjs`, with the largest interpolation-free Galaxy
block in `tools/galaxy/`. Pick the file by what you are changing:

| Changing | File |
| --- | --- |
| Unit ratios, stock, research ladders, infrastructure, hotkeys | `build/tables.cjs` |
| Production/stock/purchase/research/addon Galaxy | `build/production.cjs` |
| Bridge, economy/expansion, home defense, P15, script assembly | `build/runtime.cjs` |
| Localization, hotkeys, catalog merges, supply, decorations | `build/archive.cjs` |
| Start points, slot compaction, config validation | `build/mapinfo.cjs` |
| Build-time assertions | `build/verify.cjs` |
| P15 wild-Zerg Galaxy source (§72-80) | `galaxy/hostile_wild_ai.galaxy` |

The full layout table and the rules that go with it (no `${}` in `.galaxy` files,
CRLF normalization, declaration order, no `__dirname` in `build/`) are in
`CLAUDE.md`. The regression oracle for any builder change is a **byte-identical
rebuild** of the offline tier's seven fixtures.

## Builder flow

The entry point performs these operations:

1. Validate the JSON slot configuration and exactly one human.
2. Build active runtime ordering with the human first.
3. Copy the base map to a temporary archive.
4. Patch MapInfo active players and fixed start points.
5. Inject or replace the delimited `SC2TEAM_CUSTOM` Galaxy block.
6. Patch localized strings.
7. Remove dangerous shadowing race data if present.
8. Add partial `CRace` `FoodCeiling=800` records to existing `UnitData.xml` (raised from 600 in v1.16.0 by user directive).
9. Merge surgical campaign roster and selected Protoss-faction catalogs.
10. Run embedded structural verification.
11. Copy the verified archive to the requested output path.

The custom Galaxy block is replaced using markers. Keep generated functions inside that block so repeated builds remain idempotent.

## P15 wild-Zerg toggle

P15 is outside the configurable P1-P14 launcher locations, but its runtime role depends
on `wild_zerg` (§90–§93).

When enabled, the builder promotes P15 from neutral-hostile to a real lobby Computer,
moves an unused start point onto the user-selected alpha nest, and appends a Zerg
`GamePlayerSetup`. Blizzard melee AI supplies the player-level economy/tech state that
neutral-hostile P15 lacked. The map also initializes `hostile_wild_ai.galaxy` for
nest-local production, construction, rally, defense, expansion, and post-truce raids.
P15 combat supply is capped at 400, Overlord production stops at 448 supply made, and
economy nests target eight Drones. Army units must train from real Larvae; the removed
`UnitCreate` substitute is verify-banned.

When disabled, the builder does not promote P15, does not assign its start point, and
omits its `GamePlayerSetup`. P15 remains neutral-hostile and the active controller is
`hostile_wild_idle.galaxy`, whose only order family is `DroneHarvest`. Merely omitting
the active Galaxy controller is insufficient if P15 remains promoted, because Blizzard
melee AI would continue running it. The launcher checkbox, MapInfo patch, player setup,
and Galaxy template must therefore always change together.

`patchHostileDecorations()` moves accidentally P14-owned infested-Zerg objects and the
two stray Player-7 Overlords to P15; `patchWildZergForeignUnits()` then removes the
Protoss units mixed into those decorations. The fixed-team base currently contains 165
P15 preplaced units across five nest anchors, not the older 190-unit/sixteen-nest layout
used by some §89–§92 measurements.

The §101 `melee_only` diagnostic is a separate third mode. It deliberately initializes
neither active nor idle P15 periodic Galaxy code and must never be confused with a
release build. `verify()` rejects custom periodic initialization in that diagnostic.

## Production and expansion model

Build-specific tables near the top of the builder define:

- Combat and support aircraft restrictions.
- Allowed ground combat units.
- Preferred unit stocks.
- Fixed technology/support structure caps.
- Scaling production structures per completed expansion.
- Prerequisites for scaling structures.
- Infrastructure gates for later expansions.
- Town-hall types by race.

The economy loop counts completed bases, all bases including construction, completed production buildings, and all production buildings. It requests prerequisite-safe structures one at a time.

The first expansion deliberately ignores production-building prerequisites, but it waits for the full town-hall mineral cost before dispatching a worker:

```text
completed bases == 1 and total bases == 1
  -> save the opening bank for expansion
  -> wait until current minerals >= 400
  -> allow and request the second town hall
```

Later expansions require `productionReady` and no town hall already under construction. When production is ready but minerals are below 400, preferred combat-unit production is temporarily throttled so the next expansion can be funded. Worker, supply, mining, and upgrade behavior remains with Blizzard AI.

## Supply ceiling rule

The only accepted implementation is a partial race override appended to the map's existing `Base.SC2Data/GameData/UnitData.xml`:

```xml
<CRace id="Terr"><FoodCeiling value="800"/></CRace>
<CRace id="Prot"><FoodCeiling value="800"/></CRace>
<CRace id="Zerg"><FoodCeiling value="800"/></CRace>
```

Never use either of these approaches:

- A map-level `Base.SC2Data/GameData/RaceData.xml`; it shadows dependency records and can remove normal starts.
- Runtime mutation of `c_playerPropSuppliesLimit`; engine testing showed missing starting units.

Copying full CRace records is also unsafe because inherited start arrays can merge and duplicate starting bases/workers.

## Start locations and player IDs

The human's logical location is independent from runtime P1. The builder patches each active runtime player record to the start point assigned to its logical slot. West logical slots are P1-P7; east logical slots are P8-P14.

Do not restore the earlier approach that called `MeleeInitUnits()` at a random location and teleported units afterward. It left worker orders and rally targets pointing toward the original central/random start. Fixed MapInfo start mapping must happen before melee initialization.

## Adding a new build

A new build normally requires synchronized changes in:

1. `GROUND_BUILDS` and defaults in `sc2team/custom_config.py`.
2. `AI_BUILD_BY_STRATEGY` in `sc2team/custom_runtime.py`.
3. Relevant builder tables for allowed units, preferred stock, infrastructure, scaling production, prerequisites, and expansion gate.
4. `PRODUCER_TYPES_BY_BUILD` in `sc2team/strategy_controller.py`.
5. Configuration and strategy-controller unit tests.
6. Runtime map structural verification expectations, if a new mechanism is introduced.
7. Engine verification with that race/build.

Do not expose a build label unless the runtime rules actually implement it.

## Required verification

Always run the offline tier in `docs/verify/verification-guide.md`. Run SC2 engine verification when changing Galaxy, MapInfo, unit/race data, starts, production, expansion, supply, or command-bridge code.

For supply or start changes, explicitly inspect normal starting units and the observed supply cap; the current retained smoke script does not prove both properties.

For economy changes, use a controlled one-human/one-AI fixture where possible and record base and production counts at game-loop checkpoints. Do not rely only on generated Galaxy text markers.
