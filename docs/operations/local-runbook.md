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

## Settings and generated state

`runtime/custom_ai_settings.json` is user-owned mutable configuration. Preserve it unless a requested reset is explicit.

`runtime/custom_ai_active.json` is generated for the current build and may include internal flags such as `strategy_bridge` or `bridge_probe`.

`runtime/maps/` contains generated production and historical probe maps. They can be regenerated or replaced by tests. Do not use them as source files.

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

### Strategy carrier cannot be found

The controller requires exactly one raw-observable Marine carrier before ordinary Marines exist. Inspect generated bridge initialization and Actor-only invisibility. Do not set the unit hidden in a way that removes it from raw observations, and do not make it raw-command unselectable.

## Publishing

Battle.net publishing is an SC2 Editor/account operation and is separate from the local API launcher. The current strategy controller is a local Python process; publishing the map alone does not deploy that controller to other players.
