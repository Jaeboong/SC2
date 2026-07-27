# System overview (V1 — 비활성)

> **이 문서는 V1 런처(`start_custom_ai.cmd`)의 구조다. 현재 플레이에 쓰이지 않는다.**
> 현재 시스템은 V3다 → [`../../v3/docs/architecture.md`](../../v3/docs/architecture.md)
>
> 아래에서 **살아 있는 부분**은 플레이어 매핑(Participant → 런타임 P1)과 맵 빌더 계층뿐이고,
> V3도 그대로 쓴다 → [`../rules/map-layer.md`](../rules/map-layer.md)
>
> **죽은 부분:** Python 전략 컨트롤러, 비콘 커맨드 브릿지, MapScript AI 트리거.
> 그 규율은 [`../history/v1-ai-rules.md`](../history/v1-ai-rules.md)에 보존돼 있다.

## Purpose

This project provides a local StarCraft II team-game experience with one human and up to thirteen AI players. It works around the official API's multiplayer-agent restriction by keeping exactly one external API Participant and representing every AI as an in-game Computer player.

## Components

### Launcher and live controller

`app/play_custom_ai.py` owns the Tkinter GUI, persists user slot settings, builds the runtime map, starts SC2, joins the game, polls observations once per second, and shuts down the connection and process.

The live game is created with `realtime=True`. Controller observations use `disable_fog=True` so both teams can detect ally damage and threats. This affects only the API observation; it does not reveal the map in the human game UI unless `full_vision` is explicitly enabled in the generated map.

### Configuration and player mapping

`sc2team/custom_config.py` defines fourteen logical location slots. A slot can be `human`, `custom_ai`, or `empty`, and exactly one human is required.

Logical slots describe map locations and GUI identity. They are not SC2 runtime player IDs. SC2 promotes the sole Participant to runtime P1 and then assigns Computer players consecutively. `sc2team/custom_runtime.py` therefore orders players as:

```text
(human,) + active custom AI slots in logical order
```

All runtime commands must call `runtime_player_id(config, logical_slot)`. Never assume logical P8 is runtime P8.

### Runtime map builder

`sc2team/custom_runtime.py::build_runtime_map` writes
`runtime/custom_ai_active.json` for launcher builds and invokes
`tools/build_custom_runtime_map.cjs`. Verification callers override the active
config output with a probe-specific JSON path so release state is preserved.

That entry point is orchestration only; the build steps live in
`tools/build/*.cjs` with the P15 wildlife Galaxy in `tools/galaxy/`. See the
module map in `docs/modify/runtime-map.md`.

The Node builder copies the fixed-team base map to a temporary location, opens the MPQ archive, and updates:

- Active MapInfo player records and fixed start points.
- Team alliances and hostile relationships.
- Localized map name and description.
- Galaxy runtime initialization.
- The invisible human-owned command carrier.
- Per-build air restrictions and ground stock hints.
- Adaptive production-building and expansion logic.
- Optional human full vision.
- Partial race supply-ceiling overrides.

It runs structural assertions before closing and copying the result to `runtime/maps/`.

P15 is conditional rather than permanently neutral-hostile. With wild Zerg enabled it
is promoted to a lobby Computer and receives both Blizzard melee AI and its dedicated
map-side controller; with the option disabled it remains neutral-hostile and uses only
the harvest-only controller. See `docs/modify/runtime-map.md`.

### Blizzard melee AI

Every custom AI slot is currently a Blizzard `VeryHard` Computer player. The general API build category is derived from the selected ground strategy (`Rush`, `Timing`, `Power`, or `Macro`). Blizzard AI remains responsible for:

- Worker creation and mining.
- Supply providers.
- Construction execution.
- Unit production execution.
- Upgrades.
- Local movement and micro when units are not temporarily script-controlled.

The generated Galaxy layer constrains and supplements those decisions; it does not replace the economy AI with a full Python bot.

### Python strategy controller

`sc2team/strategy_controller.py` handles high-level behaviors that Blizzard's team AI does poorly:

- Attack only after sufficient ground combat power has accumulated.
- Scale required combat power with completed relevant production buildings.
- Detect real enemy damage to any ally on either team.
- Choose the nearest eligible same-team AI helper.
- Dispatch a limited support force.

It sends orders through one invisible Marine owned by runtime P1. The carrier is visible in raw API data but its model is invisible and it uses no supply.

### Galaxy command bridge

The Python controller cannot issue ordinary `RequestAction` commands for Computer-owned units. It instead moves the human-owned carrier to encoded coordinates. Generated Galaxy unit-order events decode those coordinates and issue normal orders for the target Computer player.

Two command families currently exist:

- Ground attack: integer coordinate encoding using `X = 100 + opcode`, `Y = 100 + runtime player ID`.
- Ally support: destination is carried directly while the helper runtime ID is encoded in the hundredths of X.

Galaxy marks selected units script-controlled for the order window and releases them after 20 seconds so Blizzard AI can resume control. The control window is deliberately shorter than the Python re-dispatch cooldown (45s) — when the two were equal, the next dispatch refreshed control before it ever expired and units never returned to the melee AI (§105.5, audit finding A1); `verify()` fails the build if the inequality is broken again. The whole unit-control module ships only when the `unit_control` launcher flag is on (default off).

## Data flow

```text
GUI SlotConfig
  -> validation
  -> Participant-first runtime ordering
  -> active JSON
  -> runtime SC2Map generation
  -> SC2 create_game + join_game
  -> raw observations
  -> StrategyController decision
  -> carrier movement command
  -> Galaxy order event
  -> Computer-owned ground units
  -> timed release back to Blizzard AI
```

## Map lineage

The original cached map is `maps/source/europe-melee-2-original.SC2Map`. Historical builders produced the stable fixed-team base map:

```text
maps/generated/europe-melee-2-7v7-rich-50000-fixed-teams.SC2Map
```

The current launcher always derives a per-run map from that base. Runtime maps are generated artifacts, not editable sources.

## Versioning

The current version is duplicated intentionally in user-visible locations:

- `app/play_custom_ai.py::APP_VERSION`.
- `MAP_NAME_KO` and `MAP_NAME_EN` in the CJS builder.
- Runtime output filename.
- Handoff and current documentation.

Update all of them together when behavior warrants a version change.

Current stable version: **v1.25.0**. The remaining performance investigation is §101:
pure 6v6 melee AI without custom periodic Galaxy or post-join observations is smooth,
so the next control must isolate custom Galaxy from raw-observation generation.
