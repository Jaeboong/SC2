# Campaign units and Protoss factions

## Scope

This guide is the current source of truth for the campaign roster and Protoss faction gameplay. The historical investigation and original pick list remain in `docs/reference/campaign-units-handoff.md`.

The implementation deliberately keeps the standard Terran, Zerg, and Protoss races. Liberty Campaign is loaded before Void/VoidMulti as the asset provider for the Terran roster models, while the exact native actor/model and Torrasque gameplay records needed at runtime are embedded as map-level snippets. Custom races and full campaign initialization are not used because they destabilize melee starts and do not have Blizzard melee AI plans.

Do not add Swarm Story Campaign. It pulls in `Campaigns/Swarm.SC2Campaign`, which redefines `FactoryTrain` `Train20` to Hellion and steals the slot the Goliath purchase uses, leaving `SC2TeamGoliath` with `ability_id` 0 and making the launcher refuse to start. The Zerg roster models resolve from the base install without it.

## Current roster

| Race | Feature | Integration |
| --- | --- | --- |
| Zerg | Torrasque | Native `HotSTorrasque` body, Kaiser Blades actor, corpse/chrysalis morph chain, and ten-second retail revival. Strategy purchase after Ultralisk Cavern. |
| Zerg | Aberration | New `SC2TeamAberration` larva product, parented from melee `Ultralisk`; Galaxy strategy purchase for selected builds. Campaign `InfestedAbomination` is a worse fit (Speed 2 against the 2.95 this roster wants). Hotkey `B`. |
| Zerg | Raptor | `SC2TeamRaptorEvolution` after Lair/Hive tech for ling builds. Hotkey `R`. |
| Terran | Goliath | New `SC2TeamGoliath`, parented from campaign `Goliath`; Factory plus Armory requirement. Hotkey `G`. |
| Terran | Predator | New `SC2TeamPredator`, parented from campaign `Predator`; Factory requirement. Hotkey `P`. |
| Terran | Medic | New `SC2TeamMedic`, parented from campaign `Medic`; Barracks plus a Barracks Tech Lab; uses the campaign heal autocast. Hotkey `C`. |
| Protoss | Standard/Aiur/Nerazim/Purifier/Taldarim | One global faction preset shared by every Protoss player, retaining standard melee IDs for AI compatibility. |

## Data layout

```text
tools/campaign_data/torrasque/   exact native Torrasque unit, actor, morph, cocoon, and revival records
tools/campaign_data/native_roster/        native Liberty actor/model parents
tools/campaign_data/native_swarm_roster/  native Raptor model parent
tools/campaign_data/roster/      added units, train buttons, Raptor upgrade
tools/campaign_data/protoss/     shared models and per-faction unit/ability/effect/actor overrides
```

`mergeCampaignCatalog()` in `tools/build/archive.cjs` inserts each snippet inside feature markers. Rebuilds replace their own marked block and never copy an entire Blizzard catalog.

## Why added units use strategy purchases

SC2 exposes valid production ability IDs for the four added units, but Blizzard's melee AI ignores unknown unit IDs even when `AISetStock()` requests them. A retained 1,500-second test produced none through stock AI alone.

The Galaxy production loop therefore performs a constrained purchase:

1. Calculate the build's desired count, including expansion scaling.
2. Require the completed producer and prerequisite structure.
3. Require actual minerals, gas, and available supply.
4. Deduct the real costs.
5. Create one unit beside the producer.
6. Consume the selected Larva for Torrasque/Aberration, or store a shared per-producer cooldown equal to the build time for Terran additions.

This does not grant free units and does not replace Blizzard's worker, supply, construction, upgrade, or ordinary-unit logic. Do not replace it with a dynamic `AbilityCommand` during map initialization: that experiment aborted the map-init trigger and removed all normal starting units.

Raptor follows the same accounting: after a Spawning Pool plus Lair/Hive and 100 minerals/100 gas, the runtime deducts the cost and adds the upgrade level. Existing and future Zerglings are upgraded while Zergling-to-Baneling morph compatibility remains intact.

Torrasque intentionally uses the retail `HotSTorrasque` ID instead of repainting
standard `Ultralisk`. Blizzard's stock AI does not train that campaign ID, so
the constrained strategy purchase charges 300 minerals, 200 gas, and six
supply, consumes one Larva, and requires a completed Ultralisk Cavern. Repeated
`AISetStock` requests do not guarantee that the melee plan will ever build that
Cavern; for `ultra_ling_bane` only, the production loop therefore issues a
normal `AIBuild` request for one Cavern after Hive completion. It never creates
the structure or bypasses cost, placement, or tech requirements.

The former custom one-health `Ultralisk` watcher and invulnerability behavior
were removed. Fatal damage now executes the native `TorrasqueCorpse` ability,
morphs through `TorrasqueCorpse` and `TorrasqueChrysalis`, and returns to
`HotSTorrasque` after ten seconds. The retail actor listens to the real
`KaiserBlades` weapon event, so attack animation and damage use the same chain.

## Runtime numeric IDs

Do not hard-code generated custom unit IDs in Python. `app/play_custom_ai.py` resolves them from `ResponseData` and registers combat weights by name:

- `SC2TeamAberration`: 3
- `SC2TeamGoliath`: 2
- `SC2TeamPredator`: 3
- `HotSTorrasque`: 6

Medic is intentionally excluded from attack readiness because it is support rather than ground damage.
When the Galaxy bridge orders a ground army, Medics receive a move order to the
same destination. They have no attack ability, so issuing the normal attack
order would leave them at home despite valid heal autocast.

The combat bodies use campaign-aligned core stats and dedicated map-level weapons: Aberration 20 damage plus 20 versus Armored, Goliath 18 ground and paired 16-plus-Armored anti-air damage, and Predator 15 direct plus a short 20-damage retribution splash. They do not inherit Thor/Ultralisk/Hellbat weapon values.

## Protoss faction semantics

`CustomLauncherConfig.protoss_faction` is `Standard`, `Aiur`, `Nerazim`, `Purifier`, or `Taldarim`. Old JSON presets default to `Standard`. The choice is global: every Protoss player in that game uses the same catalog overrides.

Standard melee unit IDs are intentionally retained so Blizzard AI continues to train, count, and control the units. The gameplay layer is currently:

| Preset | Retail skill integration |
| --- | --- |
| Aiur | Stalker ID is retained only for melee-AI compatibility. Its body, mover, turret, missile mover, weapon/action actors, walk timing, portrait, wireframe, sounds, and localized name become the retail Dragoon set; it has no Blink. Zealot gains the retail Whirlwind ability with its original autocast behavior. |
| Nerazim | Zealot gains the retail Shadow Charge/Stun autocast chain. Stalker uses `BlinkShieldRestore`. Immortal gains the original manual Shadow Cannon. Standard Archon gains the original manual Dark Archon Mind Control and Confusion abilities. |
| Purifier | Stalker uses the Instigator's original `BlinkMultiple`. Zealot uses the original Reconstruction corpse/rebuild morph chain. Standard Sentry gains the Energizer's original Chrono Beam and Phasing/Mobile Mode abilities. |
| Taldarim | Stalker uses the original `BlinkSlayer`/`PhaseBlinkDamage` chain. Zealot gains the retail Frenzied Overload autocast. Standard Sentry gains Havoc Target Lock and the red Force Field; standard High Templar gains Ascendant Mind Blast, Psionic Orb, and Sacrifice. |

Ability mechanics and original manual/autocast flags are preserved. The project does not force manual campaign abilities to autocast and does not replace their effects with AI-friendly approximations. If Blizzard melee AI does not use a manual ability, that is accepted behavior. The only deliberate compatibility adaptations are attaching the retail records to retained standard melee unit IDs and clearing campaign/commander progression requirements that would otherwise keep the selected skill unavailable.

Do not wire the Aiur Dragoon to Stalker Blink: its Blink slot is deliberately removed. Do not rename pure faction abilities to standard melee IDs merely to influence AI behavior. `BlinkShieldRestore`, `BlinkMultiple`, `BlinkSlayer`, and `PhaseBlinkDamage` retain their retail IDs and data chains.

### Faction model scale is not optional (§115, 2026-07-27)

A campaign asset is authored at a different native size than its melee counterpart, so Blizzard's own `CModel` records scale it down: Zealot Aiur/Nerazim `0.9`, Purifier Stalker `0.69`, Immortal Nerazim/Taldarim `0.75`, Colossus Taldarim `0.75` (Purifier Zealot and the Tal'darim Zealot/Stalker carry no scale, i.e. `1.0`). The `SC2Team*Model` records shipped without those values, so those units rendered oversized.

The visible symptom was reported for the Immortal barrier. The barrier is **not** part of the unit model: it is a separate `ModelAddition` actor, `ImmortalOverload` → `Assets\Effects\Protoss\ImmortalShield\ImmortalShield.m3`, created on `Behavior.ImmortalOverload.On` and sized for the retail Immortal body. An oversized faction body therefore wears a too-small standard shell. `verify.cjs` now asserts each scale so this cannot silently regress.

**No faction variant of the barrier shell exists in Blizzard data.** The campaign faction Immortals (`ImmortalShakuras`, `ImmortalTaldarim`, `ImmortalAiur`) have no barrier ability at all — their actors carry no `Behavior.ImmortalBarrierBase` events — and no `SkinData` replacement anywhere touches `ImmortalShield`/`ImmortalOverload`. Restoring the body scale is the fit correction; do not go looking for a Nerazim barrier asset.

### Swapped units carry their faction's full visual set (§115)

Replacing only `<Model>` on a standard actor leaves the death model, warp-in effect, portrait, wireframes, and unit icon as the standard Protoss ones. Each swapped unit now links its faction set, sourced from the matching campaign actor (`ZealotAiur`, `ZealotShakuras`, `ImmortalShakuras`, `ZealotPurifier`, `StalkerPurifier`, `ImmortalTaldarim`, `ColossusTaldarim`) and, for the Tal'darim Zealot/Stalker which have no campaign actor, from the `TaldarimSkin` replacement table.

Two deliberate omissions when porting those records: campaign `Lighting` ids (portrait lighting) and campaign-only `LowQualityModel` ids are dropped, because a link to an id absent from the melee catalog is a data-load hazard. Where the campaign itself reuses a standard visual — the Aiur Zealot death, the Nerazim Stalker's entire set, the Purifier Stalker warp-in — the standard one is kept on purpose.

## Why a roster unit renders as a gray sphere

Three separate defects all produce the same gray placeholder sphere, and none of
them are visible to the catalog, debug-create, or combat probes: the unit exists,
spawns, and deals correct damage while showing a sphere. Only
`verification/verify_campaign_render.py` or a real look catches them.

**The actor must parent from a `Generic*` base actor, never from a concrete unit
actor.** A `CActorUnit` creates itself on `UnitBirth.##unitName##`, and that token
is resolved once, where the actor is declared. Inheriting from the `Predator` actor
bakes in `UnitBirth.Predator`, so the actor never binds to our unit and nothing
renders. Blizzard's own `SpartanCompany` (a Goliath variant) parents from
`GenericUnitBase` for this reason. Each roster actor therefore restates the parent
unit's presentation fields rather than inheriting them. This defect affected every
custom roster unit from their introduction until v1.10.5.

**The campaign dependency must reach `DocumentHeader`.** The running game reads its
dependency list from `DocumentHeader`, not `DocumentInfo`. Patching only
`DocumentInfo` silently loads nothing, so campaign assets are absent. See
`docs/modify/runtime-map.md`.

**Each roster `CModel` must state its own `.m3` path.** A `CModel` `parent` does not
inherit the `Model` asset path. Carry `RequiredAnims` explicitly for the same reason.
This one alone was never the cause of the reported sphere: v1.10.4 shipped it as a
fix without rendering anything, and the unit stayed a sphere.

The builder asserts the actor-parent, `unitName`, and model-path rules and fails the
build if any roster entry breaks them.

## Why a roster unit is mute

SC2 links a unit actor's voice **by actor id**. Actor `Predator` finds `CSound`
`Predator_What` with no XML at all, which is why Blizzard's own Predator, Marine and
Goliath actors declare no `SoundArray`. Roster actors are named `SC2Team*`, so the
engine looks for `SC2TeamPredator_What`, finds nothing, and plays silence.

The auto-link is not a guess. `core.sc2mod` ships a
`GenericUnitStandardNoAutoSoundLinks` sibling class for actors that must opt out, and
`GenericUnitSM` blanks each `SoundArray` entry to an empty string to silence story
units. You only blank what would otherwise be filled in.

Each roster actor therefore names Blizzard's existing `CSound` explicitly. No roster
sound is a new asset. **A wrong id is silent, not fatal**: the roster shipped
`UltraliskReady` for a sound really called `Ultralisk_Ready` and nothing complained,
so the Aberration was mute too. The builder now checks every roster sound id against
the catalogs under `vendor/` and fails the build on an unknown one.

Only name sounds from the base game or the Liberty campaign. The matching
`Aberration_*` voice set exists solely in Swarm Story — the dependency that steals
`FactoryTrain` `Train20` and breaks Goliath production.

Weapon fire and impact sounds come from `CActorAction`, whose `effectAttack` must name
the `CEffectDamage` **leaf** — never the weapon, never the `CEffectSet` wrapping it.
Blizzard's `PredatorAttack` hooks effect `Predator` (the damage) while the weapon
fires `RetributionFieldSet` (the set).

There is no automated check that a sound is audible; the API exposes no audio.

## Why a roster unit has no hotkey or tooltip

A `CButton` is an icon and nothing else — Blizzard's `CButton id="Marine"` carries no
hotkey and no tooltip either. Everything else resolves by string-key convention:

- `Button/Hotkey/<id>` in `<locale>.SC2Data\LocalizedData\GameHotkeys.txt`
- `Button/Name/<id>` and `Button/Tooltip/<id>` in `GameStrings.txt`

The builder had never written `GameHotkeys.txt`, so roster buttons were icons with no
letter and no text. Write every `_NRS`/`_SC1`/`_USD`/`_USDL` profile variant as well,
or the hotkey works only for players on the default profile.

## Why a roster `CUnit` parents from the campaign record

A roster `CUnit` parents from Blizzard's own campaign unit, never from a melee
lookalike. Until v1.10.6 `SC2TeamPredator` parented from `HellionTank`, which carries
`<AbilArray Link="MorphToHellion"/>` — that is where the Hellion transform button came
from. The melee parent also supplied radii and a `LifeArmorName` that did not match the
campaign model: declaring `Radius 0.5` on a model built for `0.625` made the Predator
stop 0.137 from a building wall of radius 1.812 and stand a third of its body inside it.

Delete any stat that equals the campaign original rather than restating it. Most of the
roster's declared life/speed/food/cost values were already identical to Blizzard's, so
only the name, the weapon swap, and genuine deviations remain.

## Safe modification checklist

1. Edit the smallest XML snippet under `tools/campaign_data/`.
2. Update preferred stocks, allowed units, purchase metadata, and structural assertions together.
3. Register any new combat unit by `ResponseData` name in `app/play_custom_ai.py`.
4. Add or update a deterministic fixture in `verification/verify_all.py`.
5. Run `verification/verify_all.py --tier offline`.
6. Run `verification/verify_campaign_render.py` for any actor, model, or dependency
   change, and actually open the PNGs under `runtime/render/`. Nothing else in the
   suite can tell a correct model from a gray sphere.
7. Run `verification/verify_campaign_roster.py` for catalog/stat changes. A zero
   `ability_id` means a dependency stole the train slot; the launcher refuses to
   start in that state.
8. Run `verification/verify_melee_approach.py` for any radius, parent, or weapon
   change on a melee roster unit. Drift from Blizzard's campaign Predator is the
   check; the tolerance is set from a measured regression, so do not loosen it to
   make a build pass.
9. Run `verification/verify_torrasque_pilot.py` for the native fatal-damage morph/revival chain.
10. Run `verification/verify_torrasque_ai_production.py` for late-game AI production.
11. Run `verification/verify_campaign_ai_production.py` for the remaining additions and Raptor upgrade.
12. Run `verification/verify_protoss_factions.py` for faction data changes.
13. Run `verification/verify_all.py --tier short-engine` for Galaxy/bridge regression.
14. Ask a human to listen if you touched a sound. Nothing in this suite can hear.
15. Regenerate the versioned map and update handoff/status documents.

## Current verification evidence

SC2 `5.0.16.97425`, 2026-07-16:

```text
CAMPAIGN_ROSTER_CATALOG=PASS
CAMPAIGN_ROSTER_CREATE=PASS
CAMPAIGN_AI_PRODUCTION=PASS
CAMPAIGN_COMBAT=PASS
CAMPAIGN_COMBAT_HOTSTORRASQUE=PASS
TORRASQUE_REVIVE=PASS
TORRASQUE_SUPPLY_STABILITY=PASS
TORRASQUE_AI_PRODUCTION=PASS
PROTOSS_FACTION_AIUR=PASS
PROTOSS_AIUR_DRAGOON=PASS
PROTOSS_AIUR_DRAGOON_MOVE_ATTACK=PASS distance=4 damage=63
PROTOSS_AIUR_WHIRLWIND_AUTOCAST=PASS
PROTOSS_FACTION_NERAZIM=PASS
PROTOSS_NERAZIM_BLINK_RESTORE=PASS
PROTOSS_NERAZIM_SHADOW_CHARGE_AUTOCAST=PASS
PROTOSS_NERAZIM_PURE_MANUAL_ABILITIES=PASS shadow_cannon mind_control confusion
PROTOSS_FACTION_PURIFIER=PASS
PROTOSS_PURIFIER_MULTI_BLINK=PASS
PROTOSS_PURIFIER_PURE_ABILITIES=PASS reconstruction chrono_beam phasing_mode
PROTOSS_FACTION_TALDARIM=PASS
PROTOSS_TALDARIM_PURE_CASTER_ABILITIES=PASS target_lock force_field mind_blast psi_orb sacrifice
PROTOSS_TALDARIM_SLAYER_BLINK=PASS
PROTOSS_TALDARIM_FRENZIED_OVERLOAD_AUTOCAST=PASS
PROTOSS_FACTIONS=PASS
VERIFY_ALL[offline]=PASS (11 checks)
VERIFY_ALL[short-engine]=PASS (2 checks)
VERIFY_ALL[release-engine]=PASS (1 check)
```

The final long-probe rerun observed Raptor evolution by 300 game seconds,
Aberrations by 400 seconds, Medics by 500 seconds, Predators by 700 seconds,
and every required added-unit type by 800 seconds. Goliath was observed between
the 100-second reporting checkpoints and was destroyed before a printed row;
the PASS condition retains cumulative sightings.

The combat probe separately confirms ground damage for native Torrasque, Aberration, Goliath, and Predator, anti-air damage for Goliath, and automatic Medic healing from 10 to 45 life.

The v1.10.3 Torrasque production rerun reached Hive around 500 game seconds,
completed the explicitly requested Cavern around 1,000 seconds, and then
observed a charged, Larva-consuming native `HotSTorrasque` purchase. The revive
probe separately observed `TorrasqueCorpse` immediately after fatal damage and
the same unit tag restored to 500 life with six supply still consumed.
