# L1→L2 gate acceptance (real ORFS evidence)

Date: 2026-09-03
Script: `scripts/run_l1_l2_gate_acceptance.py`
Evidence: `docs/evidence/l1_l2_gate_smoke-20260903/`
Status: accepted — real-ORFS L2 authorization gate, not an ORFS-Agent search
run and not a QoR/PPA improvement claim.

## Boundary

This slice proves the L1→L2 handoff boundary end to end at the authorization
stage:

```text
natural-language mux Goal -> typed clarification -> frozen Goal IR
-> Runtime ORFS baseline (real) -> Policy-approved place_density proposal
-> Runtime ORFS candidate (real) -> M1 comparison
-> durable escalate reflection -> L2_HANDOFF_AUTHORIZED trace event
-> typed L2HandoffAuthorization + frozen OptimizationRequest
```

It does not submit ORFS-Agent search work: the direct-submission path was
retired (`ba88043`) and execution belongs to the durable external campaign
controller, exactly like the product L2 path. No optimizer ran and no QoR
improvement is claimed.

## Command

```bash
PYTHONPATH=packages/contracts/src:packages/scheduler/src:packages/execution/src:. \
  .tools/venvs/orfs-agent/bin/python scripts/run_l1_l2_gate_acceptance.py \
  --output-root /tmp/openroad-l1-l2-gate-20260903
```

Terminal result: exit code 0; the summary reports `accepted: true`.

## Audited result

- Session `l1-session-50067332278b46c9b367d45ec2928faa`; frozen Goal
  `goal-50067332278b46c9b367d45ec2928faa`.
- Real Runtime observations: baseline run `26b841202015482791f5915d9d86a7c9`,
  candidate run `f168a3a2308444f8beb7351752519311` (both succeeded; the two
  runs consumed the frozen EDA budget from 3 to 1).
- M1 decision: `stop` (comparison only; no measured improvement invented).
- Durable event sequence ends
  `reflection_recorded(escalate) -> l2_handoff_authorized`.
- `L2HandoffAuthorization`: `l2-auth-4e4754c0e13b08cd46b0e1e0` binding the L1
  trace, goal, terminal state, baseline/candidate run ids and artifact
  evidence.
- Frozen `OptimizationRequest`: `l2-request-f1e5672e58bf4a74a02a60a0fbd05360`
  (`orfs-agent / optimizer.l2.propose`), with source-lock and shared-domain
  SHA-256 evidence pointers and a 2-run EDA budget.

Summary: `l1_l2_gate_acceptance_summary.json`; durable sqlite sources
(`trace.sqlite`, `runtime.sqlite`, `loop.sqlite`, `sessions.sqlite`,
`workbench.sqlite`, `l2_handoff.sqlite`, `l2_campaign.sqlite`) and their
SHA-256 manifest are in `docs/evidence/l1_l2_gate_smoke-20260903/`.

## Rollback

Revert the acceptance-script/document commit. Runtime, evaluator, upstream
ORFS-Agent algorithm, benchmark RTL, SDC, PDK, and toolchain were not
modified.
