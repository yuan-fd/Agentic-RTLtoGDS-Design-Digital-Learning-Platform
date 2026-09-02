# P2 real ORFS bounded smoke

Status: passed (bounded integration smoke; not a QoR superiority claim)
Date: 2026-09-02

Provenance status: the earlier working-tree smoke below is historical only.
Commit-level acceptance is the clean-worktree rerun recorded in the next
section.

## Commit-level clean rerun

- platform commit: `b1cfffa69476c4f4c108caf9c73b2dc62718c011`;
- worktree: detached clean worktree at that exact commit (`git status
  --porcelain` empty before execution);
- output: `/tmp/openroad-platform-p2-clean-smoke.TwlV4o`;
- elapsed time: 237.268 seconds; `accepted=true`; terminal status `succeeded`;
- summary SHA-256:
  `f95ec22199ee6ae52c3c8574cc46283991ce2558a6224645468258dfd5944494`;
- all six ORFS stages succeeded; 19 artifact records were hash-verified;
- shared toolchain before/after snapshot was equal;
- focused clean-worktree regression after the run:
  `tests/test_orfs_intake_gate.py`, `tests/test_orfs_plugin.py`, and
  `tests/test_orfs_runner.py`: 15 passed.

## Runtime and toolchain

- ORFS root: `/share/home/yuanwenjie/OpenROAD-flow-scripts` at `51ad1231a`;
- OpenROAD: `tools/install/OpenROAD/bin/openroad`, version
  `26Q1-1961-g63ed2e0fe5`;
- Yosys: `tools/install/yosys/bin/yosys`, version `0.63`;
- server-managed environment: `/share/home/wangza/opt/openroad/scripts/env-gcc12.sh`
  then `openroad_env.sh` (GCC 12 and OpenROAD dependency tree);
- input: `tests/fixtures/p2_mux_2to1.v`, platform `nangate45`, finish target.

## Invocation and result

`scripts/run_p2_acceptance.py` completed a Runtime-owned Attempt in
`/tmp/openroad-platform-p2-real.Qj0eZC` in 331.366 seconds. Its summary has
SHA-256 `38f774c948389ed47c8bed0928b7d8c5729aacccb08e62b59c3334796cb77aea`.

- terminal Runtime status: `succeeded`;
- stages synth, floorplan, place, cts, route, and finish succeeded;
- `implementation_valid=true`, `gds_complete=true`, `synthesizable=true`;
- `functionally_verified=false`: this smoke makes no functional-correctness
  or comparative QoR claim;
- 22 artifact records were hash-verified;
- Runtime SQLite snapshot SHA-256:
  `d12921cc9c6f39bb4cedfee637d33410e0518e1c486d9e4aae38d9b18e00e0a1`;
- the before/after shared-toolchain snapshot was equal.

## Boundary statement

The flow ran from the Runtime Attempt-local flow copy. Raw logs and generated
artifacts remain in the listed Attempt workspace. The smoke demonstrates
bounded integration only; protected evaluator facts remain separate from any
optimizer claim.

## Rollback

Revert the P2 evidence/managed-toolchain commits. This does not delete the
external `/tmp` evidence while it remains on the host.
