# Local runbook

## Supported environment

The current workspace was developed and verified on:

- Windows.
- StarCraft II `5.0.16.97425` installed under `C:\Program Files (x86)\StarCraft II`.
- Python 3.14 in a project-local virtual environment.
- Node.js with the StormLib package installed under `tools/node_modules`.

The Python package versions are pinned in `requirements.txt`, notably `protobuf==3.20.3` for compatibility with the generated SC2 protocol package.

## Bootstrap

If the local environment is missing:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Push-Location tools
npm install
Pop-Location
```

The source and generated SC2 maps and any vendor bot packages are separate local assets. Verify their presence rather than assuming dependency installation recreates them.

## Normal launch

Double-click or run:

```powershell
.\start_custom_ai.cmd
```

The batch file starts `app/play_custom_ai.py` with `pythonw.exe`. The GUI saves configuration to `runtime/custom_ai_settings.json` and regenerates the versioned runtime map on every game launch.

The expected flow is:

1. Configure P1-P14 slots.
2. Keep exactly one human.
3. Select each AI race and ground build.
4. Start the test/game.
5. Wait for the status message confirming logical location and runtime player mapping.
6. Use the GUI's test-stop or launcher-exit path for orderly shutdown.

## SC2 process requirements

`sc2team/process.py` discovers the newest installed `SC2_x64.exe`. The working directory must be the StarCraft II `Support64` directory. Using the version executable directory as the working directory caused SC2 to exit immediately with code zero during early testing.

Normal launcher port: `14100`.

Probe ports:

- Isolated bridge: `14111`.
- Accelerated strategy runtime: `14112`.

V3 launcher port: `14180`. Live observe bridge (HTTP, read-only): `14181`.

The SC2 API port accepts exactly one client. While the launcher holds it, a second
process completes the TCP connection but never finishes the WebSocket handshake, so
`Sc2Connection.open` times out. Measured 2026-07-26; the existing connection was not
disturbed, so a stray attach attempt cannot kill a live game. This is why live
observation is served by a sidecar inside the launcher rather than by attaching.

## Settings and generated state

`runtime/custom_ai_settings.json` is user-owned mutable configuration. Preserve it unless a requested reset is explicit.

`runtime/custom_ai_active.json` is generated for the current build and may include internal flags such as `strategy_bridge` or `bridge_probe`.

`runtime/maps/` contains generated production and historical probe maps. They can be regenerated or replaced by tests. Do not use them as source files.

## Live observe bridge

A read-only HTTP channel into the game the user is playing right now. It exists for
symptoms that raw observations cannot show on their own — most of all the unit whose
panel goes blank and which then refuses to attack. The user sees it; this is how an
agent gets numbers from the same moment.

Turn it on with the launcher checkbox **라이브 관측 브리지**. Default is off, and with
it off the launch path is byte-for-byte what it was before. The optional second
checkbox **명령카드 계측** adds `feature_layer` to the join options, which is the only
way `ui_data` and `abilities` — the actual selection panel and command card — get
populated. It applies to the launcher only; every probe keeps the raw-only default in
`sc2team/protocol.py`.

The bridge never talks to SC2. `run_v3_game`'s polling loop already pulled a full
observation every second and threw it away; the bridge serves that snapshot, so
queries add no observation load to a realtime game and there is no code path that
could issue an action. Non-GET methods are rejected with 405. Nothing is sent
anywhere: the server binds `127.0.0.1` and only answers requests that arrive. An
idle bridge does no work at all.

### Cost of 명령카드 계측

Measured 2026-07-26 on the 14-slot observer game, 120-sample rolling windows of the
launcher's own observation round-trip, startup spike aged out:

| feature_layer | units | mean | max |
| --- | --- | --- | --- |
| off | 1357 | 38.11 ms | 64.24 ms |
| off | 1552 | 45.33 ms | 104.77 ms |
| on (32×32) | 1389 | 41.18 ms | 70.54 ms |

Round-trip tracks unit count at roughly 0.037 ms per unit, which puts the expected
off-cost at 1389 units near 39.3 ms. The measured on-cost is 41.2 ms, so
`feature_layer` at 32×32 adds about **2 ms, roughly 5%**, against a 1-second polling
interval. That is not a reason to drop `ui_data`/`abilities`; keep the option.

`has_feature_layer_data: true` confirms the spatial interface actually attached. In
observer mode `ui_data` comes back as `{}` and `abilities_available` is `0` — an
observer has no selection, so these only carry content for a human participant.

### Answering "check it now"

The user selects the misbehaving units in the game with a drag box, then:

```bash
curl -s http://127.0.0.1:14181/selected    # every raw field of what they selected
curl -s http://127.0.0.1:14181/compare     # only the fields that differ from healthy units of the same type
```

`/compare` is the diagnosis. It groups the selection by `unit_type`, finds unselected
units of that same type and owner, and prints only the fields whose value sets differ.
Fields that differ between two healthy units by nature — `tag`, `pos`, `facing`,
`is_on_screen`, `is_selected`, and `orders` — are excluded so they cannot bury the
signal; `orders` comes back separately as an ability-id summary because "cannot
attack" shows up there. The reference set is capped at 120 units per group to keep a
comparison from stalling the game loop, and the response says so when it truncates.

**An empty `differences` is itself the answer.** It means the units are identical in
the simulation layer, so the symptom lives in the client actor/UI layer, and the next
place to look is `ui_data`/`abilities` (the 명령카드 계측 checkbox) or render.

Two supporting endpoints:

```bash
curl -s http://127.0.0.1:14181/health      # game loop, clock, unit total, observation latency
curl -s http://127.0.0.1:14181/snapshot    # unit counts per owner, supply, resources
```

`snapshot_age_seconds` on every response is how stale the reading is; it tracks the
1-second polling interval. In observer mode `viewing_player` is all zeros because an
observer has no `player_common` — use `units_by_owner` instead.

## Shutdown

The launcher closes the API connection and stops the SC2 process in a `finally` block. If the window was terminated abnormally, inspect remaining processes:

```powershell
Get-Process SC2,SC2_x64,SC2Editor,SC2Switcher -ErrorAction SilentlyContinue
```

Only stop processes known to belong to the test. Preserve an editor session with unsaved user map changes.

## Common failures

### SC2 opens and closes immediately

Confirm process discovery selected a valid version and that the launch working directory is `Support64`.

### API connection or port failure

Check for stale SC2 processes on the fixed port. Close existing test games before retrying.

### Human selected Pn but joined runtime P1

This is expected engine behavior. Runtime P1 is the Participant; the generated map maps runtime P1 to logical Pn's fixed start. An error is only present if the human appears at the wrong map location.

### AI race/team appears mixed

Inspect Participant-first runtime ordering and generated MapInfo/attributes. Do not index configuration by logical player number after empty slots are compacted.

### Workers run toward the center or rally points are wrong

This indicates random initialization followed by unit teleporting. The stable design fixes MapInfo start points before `MeleeInitUnits`; do not restore post-initialization teleport logic.

### Starts disappear after a supply/data change

Look for map-level `RaceData.xml` or `c_playerPropSuppliesLimit`. Both are forbidden. Verify normal starting units in the actual engine, not only archive contents.

### Live observe bridge does not answer

Confirm the launcher checkbox was on for this game; the bridge starts after the join
and stops in the same `finally` block that closes the connection, so it only exists
while a game is running. If the port was already taken the launcher says so in its
status line and plays on without the bridge — that is deliberate, a diagnostic must
never block the game. `/selected` returning 503 means no observation has been
published yet.

### /selected reports zero units while units are clearly selected

`is_selected` reflects the selection of the client that joined the API connection.
It is populated for the human participant. An observer-mode game has no participant
selection, so use observer mode only for testing the endpoints, not for the actual
diagnosis.

### Strategy carrier cannot be found

The controller requires exactly one raw-observable Marine carrier before ordinary Marines exist. Inspect generated bridge initialization and Actor-only invisibility. Do not set the unit hidden in a way that removes it from raw observations, and do not make it raw-command unselectable.

## Publishing

Battle.net publishing is an SC2 Editor/account operation and is separate from the local API launcher. The current strategy controller is a local Python process; publishing the map alone does not deploy that controller to other players.
