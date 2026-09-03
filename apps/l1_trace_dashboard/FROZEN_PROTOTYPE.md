# Frozen trace viewer prototype

Status: **LEGACY / TRACE_VIEWER_PROTOTYPE** as of 2026-09-03.

This directory is retained because it provides bounded, read-only playback of
an integrity-checked durable L1 trace. It is not the L1 product Workbench and
must not become one by incremental feature additions.

It intentionally has no:

- user natural-language submission or clarification endpoint;
- Session, Goal, Plan, Runtime Run, campaign, or recovery authority;
- execution, cancellation, policy decision, evaluator, or plugin path;
- live event ownership; or
- hidden-CoT, provider transcript, raw workspace, or secret display.

The product successor is a separately-created `apps/l1_workbench/`, after a
durable L1 session service and Runtime-backed event stream have been admitted.
The successor may read a presentation projection but cannot infer or declare
authoritative state. Preserve this prototype and its historical evidence; do
not delete or silently relabel it as the operational dashboard.

Rollback of the P1 classification slice: revert this marker and the matching
governance inventory/doc wording only. No Runtime, evaluator, plugin, API, or
historical Web behavior is changed by this slice.
