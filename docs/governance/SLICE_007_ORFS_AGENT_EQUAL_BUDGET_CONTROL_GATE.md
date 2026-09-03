# Slice 007: ORFS-Agent equal-budget control gate

Status: design gate open; the replacement formal campaign has deliberately
not been started.

## Problem

`scripts/run_orfs_agent_paper_campaign.py` correctly freezes an ORFS-Agent
protocol with 50 initial observations and five 50-candidate upstream GP/EI
batches.  It records repeated baseline and confirmation measurements.
However, it does **not** execute a Random or Sobol arm with the same target
domain, screening budget, protected evaluator, and resource policy.

Therefore its eventual result could establish:

1. a native ORFS-Agent GP/EI → Runtime → protected-evaluator closed loop; and
2. an improvement or non-improvement relative to its baseline.

It could not establish that GP/EI is better than an equal-budget non-adaptive
search control.  The protocol document already requires that control, so
starting the campaign now would create incomplete evidence, not a valid
comparative study.

## Evidence

The only candidate producer in the runner is
`build_orfs_agent_native_task(...)`.  The runner has no declared control-arm
argument, no control receipt, and no aggregation of an equal-budget control.
Repository search finds Random/Sobol controls only in unrelated industrial
DSE and legacy v2 study paths; they cannot be silently reused because their
benchmark, search domain, protocol, and objective identity differ.

## Non-negotiable invariants

The future control arm must:

- consume 300 screening evaluations (50 initial plus 250 candidates), just
  like the ORFS-Agent arm;
- use the *same* preflight-derived, subtractive target domain and frozen
  anchor; it may not widen the domain;
- use the same RTL bundle hash, SDC bytes, toolchain lock, stage/flow timeouts,
  evaluator, screening seed policy, resource limit, objective, and failure
  accounting;
- retain every infeasible/failed trial as evidence;
- independently repeat its selected screened winner using the same three
  confirmation seeds; and
- produce a separate immutable receipt, then a paired aggregation report that
  labels any missing or non-comparable data instead of computing a claim.

The ORFS-Agent Adapter remains a thin bridge to the pinned upstream GP/EI.
The control must be a separate Scheduler-owned baseline capability, never a
fallback inside that Adapter.

The product workflow's three-round stagnation handoff remains valid for a
user-directed repair workflow.  It is explicitly disabled in this frozen
comparative protocol: early stopping one arm would make the stated 300-run
budget false and invalidate the comparison.

## Options

### A. Seeded uniform random control

Materialize 300 distinct legal vectors from the frozen admitted domain with a
recorded PRNG seed.  This is simple, transparent, and a valid non-adaptive
baseline.  It does not claim the low-discrepancy properties of Sobol.

### B. Scrambled Sobol control

Use the platform's existing tested Sobol encoder, constrained to exactly the
admitted discrete domain and recorded seed.  This gives more evenly spread
coverage but requires a narrow, target-domain projection adapter and an
explicit review that its encoding does not alter the ORFS-Agent domain.

### C. Both controls

Run Random and Sobol each at the full budget.  This is the strongest study but
doubles expensive ORFS executions and is not necessary to repair the present
missing-control defect.

## Recommendation

Implement one standalone, seeded-uniform Random control first as a separate
Scheduler campaign and aggregate it with the native GP/EI arm.  It is the
smallest protocol-complete change, has no optimizer logic in the API or
ORFS-Agent adapter, and has an unambiguous equal-budget interpretation.
Sobol can be admitted later as another plugin/control arm without changing
the ORFS-Agent result.

## Stop condition used

The previously queued replacement service was stopped before it created a new
experiment directory.  The old controller-loss batch and its remaining
natural child process are untouched historical evidence.  This prevents an
incomplete campaign from being misreported as a comparative acceptance.
