# LLM Teaching Platform audit — 2026-09-13

## Current score

**8.2 / 10 (implementation readiness)**

The score measures verified platform behavior, not planned features. It remains reduced for missing browser end-to-end evidence, incomplete MCP image/session projection, and missing fresh multi-user load evidence.

## Verified

- Three user entrances: Labs, EDA Console, Learn with Ibex.
- Ibex teaching steps, command checking, report explanation, and controlled experiment planning.
- Real Ibex ORFS baseline and controlled place-density comparison with recorded QoR evidence.
- RTLScout-v2 path with independent verification oracle, Runtime-backed candidate, lint and simulation evidence.
- Bounded RTLScout → mutation → ORFS → GDS promotion for `nangate45/and2`, with final GDS/ODB/DEF/netlist, area, timing, power and zero-DRC evidence.
- OpenROAD-MCP 1.1.0 stdio probe, bounded read-only query adapter, HTTP status/query/history endpoints.
- MCP query history is user-scoped, persisted in SQLite, capped at 20 records, and expires after one hour.
- Runtime and durable DSE worker startup, heartbeats, aggregate worker health, and standard startup script.
- Full regression suite: 864 passed, 1 deselected (2026-09-13, 425.36s).
- Standard startup now serializes shared SQLite initialization; a 32-process live constructor smoke and scheduler regression passed (`6649e49`).
- MCP upgrade-plan/upgrade-run ownership and explicit-confirmation regression: 2 tests passed; teaching/dashboard/API regression subset: 27 tests passed. The confirmed web upgrade route reuses Runtime and keeps MCP observations separate from formal evidence.
- Bounded HTTP concurrency smoke accepted 8 simultaneous teaching users, with 8 isolated sessions and 8 observed runs (`scripts/run_teaching_http_concurrency_smoke.py`).
- Authenticated Playwright browser reached the teaching command-check endpoint and received an accepted guided Ibex action.

## Partial or pending

- Checkpoint 3 still needs a fresh browser proof of Ibex baseline, parameter comparison, and project/evolution replay.
- MCP image/report projection and long-lived interactive sessions remain unimplemented; the confirmed upgrade action is intentionally limited to the fixed Ibex reference design.
- P12 v2 bounded `and2` acceptance is complete through ORFS/GDS; broader designs and provider-dependent revisions remain outside this bounded proof.
- Fresh 5–10 user load evidence is represented by the bounded 8-user smoke; sustained production load and browser-level load remain unmeasured.
- Interactive authenticated browser certification is pending because this host has no usable headless browser; static rendering and authenticated API evidence are archived separately and are not counted as full page replay.
- Final legacy cleanup and release management remain outside the current teaching-focused scope.

## Evidence boundaries

MCP output is exploration data. RuntimeStore artifacts and metrics remain the only formal experiment evidence. Predictions, historical records, and live queries are not merged into Runtime evidence without a verified promotion path.
