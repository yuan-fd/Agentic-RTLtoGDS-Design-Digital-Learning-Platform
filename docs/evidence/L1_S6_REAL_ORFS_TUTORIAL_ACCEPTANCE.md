# L1 S6 real ORFS tutorial acceptance

## Migration slice

- Boundary: a reproducible, managed L1 tutorial that exercises the existing
  admitted ORFS/OpenROAD Runtime adapter.  It does not change ORFS, OpenROAD,
  RTL, SDC, the PDK, evaluator, or an optimizer.
- Changed files: `scripts/run_l1_tutorial_acceptance.py`.
- Before/after edge: the previous automated tests proved the individual L1
  services.  This script composes the same durable Session, Goal finalizer,
  Policy, typed tools, Runtime, receipts, DesignState reducer, and planner in
  one fresh state root.  It adds no API-to-plugin shortcut.

## Command and bounded smoke

Run on 2026-09-03:

```bash
PYTHONPATH=packages/contracts/src:packages/scheduler/src:packages/execution/src:. \
  .tools/venvs/orfs-agent/bin/python scripts/run_l1_tutorial_acceptance.py \
  --output-root /tmp/openroad-l1-tutorial-acceptance-20260903
```

Terminal status: `0`.

The output root was empty before the run.  Its durable source evidence is:

- `/tmp/openroad-l1-tutorial-acceptance-20260903/runtime.sqlite` — Runtime
  runs, attempts, exit status, registered artifacts and hashes;
- `/tmp/openroad-l1-tutorial-acceptance-20260903/trace.sqlite` — append-only
  L1 trace; and
- `/tmp/openroad-l1-tutorial-acceptance-20260903/l1_tutorial_acceptance_summary.json`
  — an assertion summary, not a replacement for either source database.

The managed `orfs` backend was started with frozen tutorial RTL
`tests/fixtures/p2_mux_2to1.v`, top `mux_2to1`, platform `nangate45`, and a
10 ns clock.  Runtime completed the real local ORFS/OpenROAD baseline and
one selected `route` stage.  This is an L1 integration smoke and must not be
reported as QoR improvement or an ORFS-Agent/L2 campaign.

## Audited result

The script asserted and observed this exact durable decision sequence:

```text
run_full_flow
→ query_timing
→ reflect_continue
→ run_route
→ query_drc
→ stop
```

The two EDA Runtime submissions consumed the frozen run budget from `3` to
`1`.  The final trace contains `goal_finalized`, typed `tool_called`,
`policy_decided`, `tool_receipt`, two `state_transition` events, and a durable
terminal `reflection_recorded`.  The stop reason is that this toolchain did
not expose canonical `drc_errors`; L1 therefore records the evidence and does
not falsely claim closure.

## Rollback

Revert the acceptance-script commit.  It has no runtime side effect outside a
caller-selected empty output directory and changes no protected component.
