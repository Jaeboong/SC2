# Modifying the strategy controller

## Responsibility boundary

`sc2team/strategy_controller.py` is a high-level supplement to Blizzard's melee AI. It must not attempt to control workers, construction, resource spending, supply, upgrades, or every unit continuously. Those remain the built-in AI's responsibility.

The controller currently owns:

- Ground-army readiness measurement.
- Attack dispatch timing.
- Damage/threat tracking for both teams.
- Helper selection and support dispatch.
- Encoding commands for the Galaxy bridge.

## Observation model

The launcher asks for raw observations with fog disabled for controller logic. This is required for symmetric support behavior across both teams. The human UI retains normal fog unless the explicit `full_vision` map option is enabled.

Game time is derived from `game_loop / 22.4`.

The controller identifies a single invisible Marine owned by runtime P1 during initialization and caches its tag before ordinary Marines exist. If zero or multiple candidates are present, initialization fails intentionally.

## Attack readiness

Ground combat power uses a unit-type-to-supply table. It excludes flying units and assigns zero to workers, buildings, and unlisted support units.

Relevant completed production buildings are selected by the GUI build. The readiness threshold is:

```text
max(14, min(70, 8 + completed producers * 6))
```

An AI is not dispatched while it is already within its attack cooldown, is acting as a support helper, or is itself in the victim cooldown window. The normal strategy cooldown is 45 seconds.

When adding or removing playable units/builds, update both `GROUND_COMBAT_SUPPLY` and `PRODUCER_TYPES_BY_BUILD`, then add unit tests that show support aircraft do not inflate combat power.

## Ally support

The controller stores health-plus-shield snapshots by unit tag. A threat is accumulated only when:

- Health/shield decreased.
- An enemy unit is within radius 20 of the damaged unit.
- Damage observations remain within a four-second window.

A support request starts at 12 accumulated damage. The victim has a 30-second request cooldown. The chosen helper has a 45-second cooldown. Candidates must be custom AI players on the same team and not already busy as victim/helper.

The nearest eligible helper to the weighted damage location is selected. Galaxy sends half of its available ground force, capped at 30 units, and later releases script control.

This enemy-near check is important: it prevents Stim and unrelated health loss from triggering support.

## Bridge encoding

Normal attack commands call `command_target(opcode, runtime_player)`:

```text
X = 100 + opcode
Y = 100 + runtime player ID
```

Support commands must carry a real map destination. `support_target` encodes the helper runtime ID in the hundredths of the X coordinate and preserves Y.

The controller sends a raw Move ability (`ability_id=16`) for the carrier. The generated Galaxy unit-order event decodes the movement rather than using `RequestMapCommand`, whose required map metadata could not be made reliable in this project.

Never send the logical GUI slot as the runtime target. Always map it through `runtime_player_id`.

## Change checklist

1. State whether the behavior belongs in Python strategy, generated Galaxy execution, or Blizzard AI constraints.
2. Preserve the one-observation-per-second live loop unless profiling justifies a change.
3. Keep both teams symmetric unless the user explicitly requests an asymmetric rule.
4. Add pure unit tests for decision thresholds and mapping.
5. Run the isolated bridge probe for encoding/order changes.
6. Run the accelerated strategy runtime probe for dispatch or economy interaction changes.
7. Run a longer manual game for cooldown, control release, and repeated-combat changes.

## Known limitations

- Attack targets are generated from the first opposing start rather than scouting or strategic target evaluation.
- Combat power is a static type table, not an upgrade-, health-, range-, or matchup-aware model.
- The support destination encoding loses X fractional precision by design.
- Current engine probes depend on mutable user settings.
- Long integration cases documented in the history are not yet independent automated runners.
