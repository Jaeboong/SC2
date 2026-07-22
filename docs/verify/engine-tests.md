# SC2 engine tests

## Why engine tests are required

SC2 map data has inheritance and initialization behavior that cannot be validated reliably by inspecting XML or Galaxy text alone. Past regressions included missing starts, duplicated starts, workers running toward old locations, bad rally targets, and API socket disconnects despite structurally valid files.

## Accelerated strategy runtime probe

Script:

```text
verification/verify_strategy_runtime.py
```

Behavior:

- Reads `runtime/custom_ai_settings.json`.
- Requires at least one Terran custom AI.
- Builds `runtime/maps/strategy-runtime-probe.SC2Map` with the production strategy bridge.
- Launches SC2 on API port `14112`.
- Creates the game with `realtime=False`.
- Joins as the sole human Participant.
- Advances the engine explicitly with `connection.step(...)`.
- Debug-creates one Marauder for the target Terran AI.
- Sends a ground attack and verifies meaningful movement.
- Advances to game loop 2332, about 104 seconds of game time.
- Accepts either a production structure or a second town hall as proof that the built-in economy is active at the early checkpoint.

Expected final marker:

```text
STRATEGY_RUNTIME_TEST=PASS
```

This is the project's retained fast-forward test. It is a smoke test, not proof of the full expansion sequence or supply ceiling.

## Campaign-unit and Torrasque probes

All three scripts construct deterministic configs and clean up their own SC2 process.

```powershell
.\.venv\Scripts\python.exe -u .\verification\verify_campaign_dependency.py
.\.venv\Scripts\python.exe -u .\verification\verify_torrasque_pilot.py
.\.venv\Scripts\python.exe -u .\verification\verify_torrasque_ai_production.py
```

- `verification/verify_campaign_dependency.py` (port 14113) checks normal town hall and eight-worker starts for Terran, Protoss, and Zerg after catalog injection.
- `verification/verify_torrasque_pilot.py` (port 14114) creates native `HotSTorrasque`, applies real fatal damage, and checks the retail corpse/chrysalis transition, ten-second revival, full life, and stable six food used.
- `verification/verify_torrasque_ai_production.py` (port 14115) is a long stepped test. It waits up to 1,500 game seconds for Blizzard's Zerg economy AI to reach Hive/Ultralisk Cavern and for the strategy purchase layer to charge and produce native `HotSTorrasque` from a Larva.

Expected markers are `CAMPAIGN_DEPENDENCY_NORMAL_START=PASS`, `TORRASQUE_REVIVE=PASS`, `TORRASQUE_SUPPLY_STABILITY=PASS`, and `TORRASQUE_AI_PRODUCTION=PASS`.

For manual renderer inspection, `verification/verify_campaign_visuals.py` opens a five-minute probe and places Goliath, Predator, Medic, Aberration, native Torrasque, and a baseline Zergling beside the human start. It is specifically intended to catch gray-sphere missing-model placeholders, blank portraits, and broken animation inheritance that raw API observations cannot see.

## Isolated Galaxy bridge probe

Script:

```text
verification/verify_strategy_bridge.py
```

Behavior:

- Reads the saved settings and selects the first enemy AI.
- Builds `runtime/maps/bridge-probe.SC2Map` in isolated bridge-probe mode.
- Launches SC2 on API port `14111`.
- Uses `realtime=True` and several real sleeps so initial collision separation can finish.
- Finds the command carrier.
- Sends the bridge's worker-order test opcode.
- Compares pre-command baseline motion with post-command movement.

Expected final marker:

```text
GALAXY_AI_WORKER_ORDER_TEST=PASS
```

This test intentionally pauses/removes the normal production-AI layer. It proves command delivery, not gameplay economy.

## Existing historical evidence without retained runners

The following checks passed during development and are recorded in `docs/latest_status.md`, but their exact probe runners were not retained:

- Normal start plus exact 800 maximum supply (the ceiling moved 600 -> 800 in v1.16.0; this check has not been rerun since).
- First expansion after reaching 400 minerals but before production completion, followed by 5-Factory and 7-Factory expansion gates.
- Nine-minute ground composition and combat-air exclusion.
- Adaptive expansion through multiple production tiers.
- Human and AI ally-support dispatch, half-force selection, and release after 50 seconds.

Historical `.SC2Map` probe artifacts under `runtime/maps/` are useful for forensic comparison only. They are not executable test definitions.

## Designing a new deterministic probe

A good engine probe should:

1. Construct its own `CustomLauncherConfig` in code instead of reading mutable user settings.
2. Use the smallest player count that exercises the rule.
3. Generate a uniquely named probe map under `runtime/maps/`.
4. Use a dedicated API port and always clean up in `finally`.
5. Prefer `realtime=False` and explicit stepping for long economic tests.
6. Observe raw state with fog disabled only for assertions.
7. Print loop-numbered evidence and one stable `NAME=PASS` marker.
8. Fail with a precise assertion explaining actual counts.
9. Restore or avoid overwriting user settings/active configuration.

For long tests, sample at meaningful loop intervals rather than stepping one loop at a time. SC2 runs much faster in stepped non-real-time mode, but construction/AI decisions still require observation at checkpoints.

## Cleanup and failure handling

Both retained probes call `quit`, close the WebSocket, and stop the launched process in `finally`. If a test is interrupted outside normal cleanup, inspect:

```powershell
Get-Process SC2,SC2_x64,SC2Editor,SC2Switcher -ErrorAction SilentlyContinue
```

Do not indiscriminately kill SC2 Editor when it may contain unsaved work. Fixed-port connection failures often indicate a stale SC2 process rather than a code regression.
