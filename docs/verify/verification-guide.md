# Verification guide

## Principles

Use the smallest tier that can disprove the change, then run every higher tier required by its risk. A generated map passing text/structure assertions does not prove SC2 engine behavior. A probe-map filename does not prove that its test was rerun.

Run commands from the project root in PowerShell.

## Tier 0: preconditions

Check the environment:

```powershell
Test-Path .\.venv\Scripts\python.exe
Test-Path .\tools\node_modules\@jamiephan\stormlib
Test-Path '.\maps\generated\europe-melee-2-7v7-rich-50000-fixed-teams.SC2Map'
```

Before engine tests, close SC2 and SC2 Editor or verify that no stale process owns the fixed API ports:

```powershell
Get-Process SC2,SC2_x64,SC2Editor,SC2Switcher -ErrorAction SilentlyContinue
```

Do not kill an editor containing unsaved user work without confirmation.

## Tier 1: offline tests

Configuration and strategy tests:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Worker-supply proxy tests:

```powershell
.\.venv\Scripts\python.exe -m unittest -v tests\test_worker_supply_proxy.py
```

Syntax checks:

`node --check` reads **one** file and silently ignores any further arguments, so
the builder entry point and every `tools/build/*.cjs` module need their own
invocation. `verify_all.py` loops over them for this reason; a single call with a
file list passes even when a module is broken.

```powershell
Get-ChildItem .\tools\build_custom_runtime_map.cjs, .\tools\build\*.cjs |
  ForEach-Object { node --check $_.FullName }
.\.venv\Scripts\python.exe -m py_compile `
  .\app\play_custom_ai.py `
  .\verification\verify_strategy_runtime.py `
  .\verification\verify_strategy_bridge.py `
  .\verification\verify_campaign_dependency.py `
  .\verification\verify_torrasque_pilot.py `
  .\verification\verify_torrasque_ai_production.py `
  .\verification\verify_campaign_roster.py `
  .\verification\verify_campaign_ai_production.py `
  .\verification\verify_campaign_combat.py `
  .\verification\verify_protoss_factions.py `
  .\verification\verify_release_map.py `
  .\sc2team\custom_runtime.py `
  .\sc2team\strategy_controller.py
```

The preferred deterministic command is:

```powershell
.\.venv\Scripts\python.exe .\verification\verify_all.py --tier offline
```

The current expected harness result is 11 PASS checks: unit tests, worker-supply tests, syntax, and seven structural map fixtures including all four non-standard Protoss factions.

### Byte-identity oracle for builder refactors

The seven fixture builds are byte-deterministic (verified: two consecutive runs
produce identical map files and archive members). A change that is meant to be
behavior-preserving — moving code between `tools/build/*.cjs` modules, extracting
Galaxy into `tools/galaxy/*.galaxy` — must therefore leave every output byte
unchanged. Hash the fixture maps before and after and compare.

Delete `runtime/maps/verify-all-*` before rebuilding. A failed build leaves the
previous maps in place, and comparing those reports a false match — this happened
during the §84 split and briefly hid a real breakage.

## Tier 2: builder structural verification

Every call to `build_runtime_map(..., strategy_bridge=True)` invokes the CJS builder, which fails the build if structural invariants are missing. It checks, among other things:

- Consecutive active runtime players and fixed start mapping.
- Exactly three partial 800-supply race overrides.
- Absence of map-level `RaceData.xml`.
- Absence of runtime `c_playerPropSuppliesLimit` mutation.
- Melee AI and production-rule initialization in production mode.
- Combat/support air caps.
- Preferred infrastructure and scaling production markers.
- Adaptive economy markers.
- Full-vision trigger when enabled.
- Command bridge and ally-support control-release markers.

Running `verification/verify_strategy_runtime.py` performs this build before launching SC2. A normal GUI launch also regenerates and structurally verifies the production map.

## Tier 3: short SC2 engine probes

Isolated bridge probe:

```powershell
.\.venv\Scripts\python.exe -u .\verification\verify_strategy_bridge.py
```

Accelerated strategy/economy smoke test:

```powershell
.\.venv\Scripts\python.exe -u .\verification\verify_strategy_runtime.py
```

Read `engine-tests.md` before running them. These scripts generate maps, launch SC2, use fixed ports, and depend on the current user settings.

The one-command short tier passes a checked-in fixture through a disposable
`SC2TEAM_SETTINGS_FILE` path; it never overwrites the user's saved JSON. It also
waits for SC2 singleton resources between probes to prevent an intermittent
second-client startup race:

```powershell
.\.venv\Scripts\python.exe .\verification\verify_all.py --tier short-engine
```

All retained probe builders pass a probe-specific `active_config_file`, so
offline and engine verification also preserve
`runtime/custom_ai_active.json` for the last real launcher/release build.

## Tier 4: targeted/long engine verification

Required for changes to:

- Starting units, race data, supply, or mode dependencies.
- Expansion ordering or resource throttling.
- Unit composition caps and long-running production.
- Repeated attack/support cycles and script-control release.
- Large 7v7 performance or slot combinations.

The current repository does not have retained, deterministic runners for every Tier 4 assertion. Recreate the controlled scenario, record the exact configuration, game-loop checkpoints, observations, and PASS condition, then preserve it as a script when practical.

The broad field probe is `verification/measure_field_state.py` (observer mode, §66;
default 20 game-minutes; SC2 must be closed). It measures early termination, per-slot
peaks (army/workers/halls/production/addons), **per-slot per-unit-type new production
via tag accumulation** (§87 — counts total units ever produced, deaths included, so
"P3 built 0 SiegeTank" is directly readable), and the P15 wild-Zerg baseline/peak/new
split (§85.6 — always capture the t=0 preplaced baseline; peak values alone
misread preplaced content as production). Redirect output to a file — piping through
`tail` loses the early samples (§85 lesson).

Campaign-unit changes currently have retained targeted runners:

```powershell
.\.venv\Scripts\python.exe -u .\verification\verify_campaign_dependency.py
.\.venv\Scripts\python.exe -u .\verification\verify_torrasque_pilot.py
.\.venv\Scripts\python.exe -u .\verification\verify_torrasque_ai_production.py
.\.venv\Scripts\python.exe -u .\verification\verify_campaign_roster.py
.\.venv\Scripts\python.exe -u .\verification\verify_campaign_ai_production.py
.\.venv\Scripts\python.exe -u .\verification\verify_campaign_combat.py
.\.venv\Scripts\python.exe -u .\verification\verify_protoss_factions.py
.\.venv\Scripts\python.exe -u .\verification\verify_campaign_render.py
.\.venv\Scripts\python.exe -u .\verification\verify_melee_approach.py
.\.venv\Scripts\python.exe -u .\verification\verify_test_launcher.py
```

`verification/verify_test_launcher.py` covers `start_custom_ai_test.cmd`: opening
grant, instant structures, unit production speedup, and that repeated
`all_resources` grants stack — infinite resources depend entirely on that last
point, because one grant is a fixed 5000/5000 rather than an unlimited state. It
imports the launcher's constants instead of copying them. Note that
`debug_create_units` spawns units free of charge, so it cannot be used to drain a
bank and "prove" a refill.

`verification/verify_campaign_render.py` writes real frames to `runtime/render/` and
includes Blizzard's own unit as a control, which separates "the asset cannot load"
from "our wiring is wrong". Its `changed_px` number is a sanity signal, not the
check: **open the PNGs.** A gray sphere passes every catalog, create, and combat
probe in this file.

`verification/verify_melee_approach.py` measures where a melee roster unit comes to
rest against a building and compares it to campaign Predator. Its 0.1 tolerance is
set from a measurement, not chosen for comfort: the v1.10.5 roster drifted 0.241 and
must fail. Every subject runs at one shared spot, because subjects spread across
different spots measure the terrain — an unpathable spot fails whatever is put there.

**Sound has no automated check.** The builder validates every roster sound id against
Blizzard's real `CSound` catalogs under `vendor/`, but the API exposes no audio, and a
wrong sound id is silent rather than fatal. Audible playback requires a human.

`verification/verify_campaign_ai_production.py` is a stepped 2v2-style long probe. It must observe Aberration, Goliath, Predator, Medic, and a Raptor-upgraded Zergling. `verification/verify_campaign_combat.py` confirms attacks, Goliath anti-air, and Medic autocast. `verification/verify_protoss_factions.py` launches four short games, checks normal starts and original ability availability, and retains direct effect checks only where the retail ability already autocasts or has a deterministic point command. Manual caster skills are not required to be used by Blizzard AI.

`verification/verify_torrasque_ai_production.py` must observe a genuinely AI-produced ID 109
unit. A Hive without an Ultralisk Cavern is a failed prerequisite path, not a
Torrasque catalog failure; inspect both counts before diagnosing it.

After regenerating the versioned release map, run its saved-configuration smoke:

```powershell
.\.venv\Scripts\python.exe .\verification\verify_all.py --tier release-engine
```

This opens `europe-melee-custom-ai-v1.25.0.SC2Map`, asserts the human is runtime
P1, and checks one starting town hall plus eight workers for every non-random
active player. It does not rebuild the release map; rebuild first.

## Tier 5: user-path smoke test

Launch:

```powershell
.\start_custom_ai.cmd
```

Confirm that the GUI loads saved settings, the runtime map builds, the human appears at the chosen logical location, every configured race is correct, normal units are selectable, and the launcher can stop the game without leaving SC2 processes.

## Change-to-tier matrix

| Change | Minimum required tier |
| --- | --- |
| Labels or non-behavioral GUI text | Tier 1 plus GUI open |
| Slot validation or runtime mapping | Tiers 1-3 |
| Strategy thresholds/selection | Tiers 1 and 3; Tier 4 for repeated combat |
| Bridge encoding or Galaxy orders | Tiers 1-3 |
| MapInfo, starts, teams, race data, dependencies | Tiers 1-4 |
| Production, air caps, expansion logic | Tiers 1-4 |
| Supply ceiling | Tiers 1-4 with explicit normal-start and cap assertions |
| Release/version change | Tiers 1-3 and Tier 5; applicable Tier 4 cases |

## Reporting

Record:

- Exact command or scenario.
- Settings/fixture used.
- SC2 version.
- Whether the test was real-time or stepped non-real-time.
- Key observed counts/loops.
- PASS marker.
- Any expected shutdown traceback or cleanup behavior.

Update `HANDOFF.md` only with current verified truth. Append full evidence and failed attempts to `docs/latest_status.md`.
