# Documentation index

The documentation is split by purpose so a new maintainer does not have to infer current behavior from the chronological work log.

## Authority order

When documents disagree, use this order:

1. Executable source and tests.
2. Root `HANDOFF.md` for the current supported state.
3. The area document linked below.
4. `README.md` for general user-facing information.
5. `docs/latest_status.md` for the active §58+ work log; `docs/history/` for older evidence.

`latest_status.md` keeps the current-state summary followed by the continuous §58+ work log. Sections 1-57 are archived per version under `docs/history/` with their original section numbers, so "§n" references from other documents and code comments resolve there. Historical sections intentionally preserve failed attempts and superseded claims; the most recent relevant section wins, but current code remains authoritative.

## Area documents

| Area | Document | Use it when |
| --- | --- | --- |
| Architecture | [`architecture/system-overview.md`](architecture/system-overview.md) | Tracing player mapping, processes, or command flow |
| Runtime map changes | [`modify/runtime-map.md`](modify/runtime-map.md) | Editing MapInfo, Galaxy, unit data, starts, supply, production, or expansion |
| Campaign roster/factions | [`modify/campaign-units.md`](modify/campaign-units.md) | Adding or balancing campaign units and Protoss faction presets |
| Strategy changes | [`modify/strategy-controller.md`](modify/strategy-controller.md) | Changing attack readiness, support response, observations, or bridge encoding |
| Verification | [`verify/verification-guide.md`](verify/verification-guide.md) | Choosing and running the correct test tier |
| Engine probes | [`verify/engine-tests.md`](verify/engine-tests.md) | Understanding accelerated SC2 tests and their limitations |
| Operations | [`operations/local-runbook.md`](operations/local-runbook.md) | Installing, launching, stopping, or troubleshooting locally |
| Decisions and constraints | [`decisions/known-constraints.md`](decisions/known-constraints.md) | Avoiding previously disproved designs and engine regressions |

## Documentation maintenance

- Keep `CLAUDE.md` short and pointer-oriented.
- Keep `HANDOFF.md` current-state oriented; remove stale claims when behavior changes.
- Add durable design and procedure details to the relevant area document.
- Append meaningful experiments and engine evidence to `latest_status.md` rather than rewriting its history. When a new version starts, move the previous version's sections to a `docs/history/` archive (keep section numbers) and rewrite the `latest_status.md` head summary.
- When releasing a new version, update the Python app version, CJS localized map names, output filename references, handoff, and current user documentation together.
