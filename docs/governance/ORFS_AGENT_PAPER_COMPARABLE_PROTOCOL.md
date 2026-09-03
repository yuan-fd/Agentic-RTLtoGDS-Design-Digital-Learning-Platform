# ORFS-Agent paper-comparable L2 protocol

Status: **frozen protocol implementation; no PPA-performance claim yet**  
Scope: the admitted pinned ORFS-Agent source at commit
`730f1fa11f9c17c0aaac332412af2b2538f42e9b`.

## Why this protocol exists

The earlier admission campaign ran a repeated fixed baseline and then asked
the upstream GP/EI workbench for a candidate.  It correctly proved the
adapter/Runtime/evaluator path, but it was not a valid optimiser study: three
measurements at one parameter coordinate tell a Gaussian Process about noise,
not about the design space.  That campaign remains immutable admission
evidence and is explicitly not a performance result.

This protocol makes that category error impossible in the new product path.
It separates a **control group** (baseline repetitions) from the **initial
training set** (many different parameter vectors).

## Alignment with the upstream project

| Upstream evidence | Platform implementation | Deliberate boundary |
| --- | --- | --- |
| `README.md`: `TOTAL_ITERS=6`, `PARALLEL_RUNS=50` | 50 initial warm-up runs, then up to five GP/EI batches of 50, for 300 screening executions plus confirmation | The platform uses Runtime workspaces and protected evaluation rather than upstream SSH/Makefile mutation. |
| `optimize.py:OptimizationWorkflow.generate_initial_parameters` | deterministic, seed-recorded independent initial samples over every live shared knob | Clock, pin-layer adjustment, upper-layer adjustment, and hierarchy synthesis remain frozen because changing timing targets/constraints is outside the fair platform PPA contract. |
| `run_sequential.sh:generate_initial_parameters` | initial evidence is materialized before any GP/EI call | The shell script itself is not executed: it deletes/copies files and edits flow configurations, which violates Runtime ownership and the protected-input rule. |
| `analyst_agent_workbench.py` `scikit-optimize` GP + EI | the unchanged pinned workbench selects numeric candidates | Platform code never substitutes a local GP, EI, random optimiser, or candidate generator. |

Exact numerical equivalence with the paper is **not** claimed unless a new
campaign also freezes its listed ORFS commit, designs (AES/IBEX/JPEG),
technology (ASAP7/Sky130HD), objective, resource/time budget, and LLM policy.
GCD/nangate45 is useful platform evidence, not a substitution for those
paper conditions.

## Frozen state machine

```text
baseline_running
  -> warmup_running
  -> optimizer_pending
  -> optimizer_running
  -> candidate_running
  -> optimizer_pending (next round)
  -> confirmation_running (only after fixed budget and screened winner)
  -> completed
```

`baseline_running` executes the same frozen configuration three times with
three stated seeds.  Its median is the comparison control and its variation is
reported.  Only one baseline coordinate can enter the GP data.

`warmup_running` executes 50 frozen, parameter-distinct recipes once each.
They are sampled deterministically from the upstream initializer's independent
per-parameter pattern, constrained to the reviewed eight-knob common domain.
All terminal outcomes are preserved.  At least 12 **different feasible**
coordinates are required before `optimizer_pending`; otherwise the campaign
fails honestly instead of making an uninformed GP proposal.

Each GP/EI batch contains 50 suggestions.  Each suggestion is first screened
once under the same screening seed.  This matches the information-collection
role of a large parallel campaign.  The screened incumbent is then rerun three
times with independent frozen confirmation seeds.  A PPA improvement is only
accepted when all confirmation runs are feasible and their median beats the
baseline median by the preregistered threshold.

## Guardrails

- The protocol fingerprint includes warm-up recipes, all seed policies, batch
  size, total candidate budget, confirmation policy, frozen constraints and
  upstream plugin identity.  Reusing an experiment key with any difference is
  rejected.
- The target-domain preflight and the formal campaign both use the same
  receipt-recorded 7200-second per-stage limit (and 14400-second flow limit).
  This makes a preflight feasibility admission meaningful:
  a point cannot be rejected later merely because the campaign silently uses
  a stricter resource limit.
- Duplicate warm-up vectors are rejected before execution.
- Failed warm-ups and failed candidates remain in terminal evidence.  The
  upstream GP receives only measured feasible rows, as its native workbench
  expects; the dashboard/provenance still shows every failure.
- Each GP/EI round receives a deterministic but different optimiser seed
  (`base seed + round`).
- `LB_ADDON` retains four decimal places.  The earlier admission-only smoke
  quantized it to 0.01, which would alter ORFS-Agent's documented AES/ASAP7
  anchor of `0.3913`; that historical receipt remains truthful for its own
  run, but is not the current formal-protocol transport.
- The SKY130HD lower UTIL bound is 20 because that is ORFS-Agent's documented
  AES anchor.  The previous platform-only lower bound of 25 was incompatible
  with the admitted upstream protocol and is not used for this comparison.
- `TaskSpec` requests `native_agent` directly.  It cannot accidentally invoke
  only the dataset bridge while being described as GP/EI.
- The final report must include baseline distribution, feasibility rate,
  per-round history, all budgets, best screened point, final confirmation
  distribution, and an equal-budget random/Sobol control.  No best-single-run
  claim is permitted.

## Target-design execution envelope

The one-factor AES preflight is intentionally conservative: it proves only
the particular values that were repeatedly feasible with all other knobs held
at the frozen anchor.  If that verified discrete product cannot supply the
official 301 unique screening coordinates, the later campaign must not pretend
that it has a 301-point *feasibility* domain.

The versioned `target_execution_envelope_external_l2_v3` protocol instead
stores two separate facts: `verified_values` from the preflight, and explicit
finite `execution_values` that Runtime may send to the protected evaluator.
An execution value is legal under typed parameter rules, but is not a QoR or
feasibility claim.  Every infeasible screen remains in the evidence.  The
same envelope digest is frozen into both optimizer arms; it may not be widened
after one arm starts.

## What has and has not been verified

The state machine and its boundary conditions have focused automated tests:

```text
tests/test_external_l2_service.py
tests/test_orfs_agent_plugin.py
tests/test_l2_external_admission.py
tests/test_package_architecture_boundaries.py
```

They verify that repeated baselines do not become duplicated GP coordinates,
50 recipes are deterministic/distinct, malformed warm-up sets are rejected,
and the screened winner must enter independent confirmation before a campaign
can report completion.

They do not prove PPA superiority.  That requires a newly started frozen
campaign with the official-comparable benchmark manifest and equal-budget
control arms.  The old three-baseline/one-candidate admission run must never
be relabeled as such a study.
