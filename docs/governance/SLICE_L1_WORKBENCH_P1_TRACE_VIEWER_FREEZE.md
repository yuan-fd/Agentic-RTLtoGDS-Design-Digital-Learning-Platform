# L1 Workbench P1: trace viewer freeze

## Intended architectural change

Classify `apps/l1_trace_dashboard/` as a retained, read-only
`TRACE_VIEWER_PROTOTYPE`; reserve the operational L1 product boundary for a
new, separately-created `apps/l1_workbench/`.

## Before and after dependency edge

Before, the standalone viewer could be misread as the future L1 dashboard.
After, its boundary is explicit: it only reads an integrity-checked SQLite
trace projection, and it is forbidden from becoming the user/session/Runtime
front door. No executable dependency edge changes in this slice.

## Changed files

- `apps/l1_trace_dashboard/FROZEN_PROTOTYPE.md`
- `docs/governance/LEGACY_CLEANUP_INVENTORY.md`
- `docs/governance/L1_S7_TRACE_DASHBOARD.md`
- this record

## Acceptance and rollback

The viewer remains runnable against a bounded trace and has no write endpoint.
No Runtime, protected evaluator, external plugin, API, or `apps/web` file is
changed. Rollback is a precise reversion of the four files listed above; no
historical code or evidence is deleted.
