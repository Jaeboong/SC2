# Known constraints and rejected approaches

This document records conclusions that should not be rediscovered by repeating expensive or unsafe experiments.

## Multiple external agents in team games

SC2 `5.0.16.97425` rejects `create_game` when multiple API Participants are used in a game larger than 1v1:

```text
Only 1v1 is supported when using multiple agents
```

Verified failures included two Participants plus two Computers. One Participant plus multiple Computers succeeds. Therefore the current team-game architecture must keep one external human Participant and implement AI teammates/opponents as in-game Computer players.

Changing ports, WebSocket topology, process count, maps, or PC performance does not remove this engine validation.

## Existing ProBots

Changeling, MicroMachine, Sharkbot, and similar ladder ProBots expect their own Participant connection and ordinary `RequestAction` control. They cannot be inserted as several independent players into the current team game without rewriting them around the custom map bridge.

The project contains historical 1v1 Changeling work, but the current launcher is the hybrid Computer-AI strategy system, not a multi-ProBot launcher.

## Post-initialization start teleporting

Moving starting units after `MeleeInitUnits()` appeared visually correct at loop zero but left built-in worker orders and town-hall rally targets aimed at the old random start, often near the center. The accepted design patches fixed player start points before melee initialization.

## Detailed built-in AI build forcing

The public API exposes only broad AI build categories. Earlier attempts to force internal detailed builds and technology restrictions caused missing starting units for several players. The stable system uses broad API categories plus explicit map-side ground composition and production guidance.

Do not claim that a GUI label maps to a hidden official detailed build unless the engine behavior is verified.

## Supply ceiling failures

Rejected implementations:

- Runtime `PlayerModifyPropertyInt(... c_playerPropSuppliesLimit ...)`: removed normal starts in engine testing.
- Map-level `RaceData.xml`: shadowed standard race catalog data and removed starts.
- Full CRace copies: inherited/merged starting arrays and duplicated starts.

Accepted implementation:

- Partial `CRace` `FoodCeiling=800` records in the map's existing `UnitData.xml`.

Any change in this area requires explicit engine assertions for both normal starting units and maximum supply.

## Command carrier visibility

The bridge needs a human-owned unit tag that accepts raw movement commands. Setting the carrier fully hidden removed it from raw observations. Making it unselectable in the wrong way caused raw commands to return `NotSupported`.

The accepted approach keeps the unit present and commandable, consumes no supply, makes it invulnerable, and hides only its Actor/model. It is returned to its origin after commands.

## RequestMapCommand

Although protocol support was explored, the necessary map metadata/registration was not established reliably. The accepted bridge uses ordinary raw movement of the command carrier plus generated Galaxy unit-order events.

## Worker supply zero and third-party bots

The current Computer AI works with zero-supply workers. Historical Changeling compatibility required a proxy that restored conventional worker/supply observations for the bot. That proxy is relevant to the old 1v1 ProBot path, not the current Computer-player strategy controller.

## Map publishing

Publishing the generated map does not package the local Python strategy controller. A Battle.net player running only the published map receives map-side Galaxy behavior and built-in AI behavior, not the external Python observation/decision loop, unless equivalent strategy is moved fully into the map.

## Campaign dependencies are asset providers, not runtime GameData imports

Direct API-launched melee maps can resolve model/texture assets from Liberty Campaign and Swarm Story Campaign dependencies while still omitting their unique unit, actor, ability, and morph records from `ResponseData`. Do not assume that adding a campaign dependency makes `HotSTorrasque`, Predator, Goliath, Medic, Aberration, or Raptor parent records available.

The accepted design loads campaign packages before Void/VoidMulti for assets and embeds the exact required retail XML records under `tools/campaign_data/`. Custom roster children are merged after their native actor/model parents. Torrasque embeds its complete native unit, actor, model, behavior, ability, effect, validator, requirement, and upgrade chain.

## Historical artifacts

Old versioned maps and probe maps are intentionally present for investigation. They may contain failed data layouts. Never select an implementation merely because a historical map appears to launch; regenerate from current source and run current verification.
