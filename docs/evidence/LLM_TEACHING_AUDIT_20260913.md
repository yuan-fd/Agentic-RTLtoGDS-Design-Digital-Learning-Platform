# LLM Teaching Platform audit — 2026-09-13

## Current score

**7.4 / 10 (implementation readiness)**

The score measures verified platform behavior, not planned features. It is deliberately reduced for missing browser end-to-end evidence, incomplete MCP image/session projection, and the unresolved provider-dependent P12 promotion.

## Verified

- Three user entrances: Labs, EDA Console, Learn with Ibex.
- Ibex teaching steps, command checking, report explanation, and controlled experiment planning.
- Real Ibex ORFS baseline and controlled place-density comparison with recorded QoR evidence.
- RTLScout-v2 path with independent verification oracle, Runtime-backed candidate, lint and simulation evidence.
- OpenROAD-MCP 1.1.0 stdio probe, bounded read-only query adapter, HTTP status/query/history endpoints.
- MCP query history is user-scoped, persisted in SQLite, capped at 20 records, and expires after one hour.
- Runtime and durable DSE worker startup, heartbeats, aggregate worker health, and standard startup script.
- Full regression suite: 858 passed, 1 deselected.

## Partial or pending

- Checkpoint 3 still needs a fresh browser proof of Ibex baseline, parameter comparison, and project/evolution replay.
- MCP interactive sessions and report-image projection are not implemented; only short-lived read-only queries are supported.
- MCP exploration has no confirmed upgrade-to-Runtime action in the web console.
- P12 v2 reaches RTLScout, lint, and simulation, but mutation quality currently stops the minimal AND example before ORFS/GDS. A later retry also hit an external Codex provider error.
- Fresh 5–10 user load evidence is not recorded.
- Final legacy cleanup and release management remain outside the current teaching-focused scope.

## Evidence boundaries

MCP output is exploration data. RuntimeStore artifacts and metrics remain the only formal experiment evidence. Predictions, historical records, and live queries are not merged into Runtime evidence without a verified promotion path.
