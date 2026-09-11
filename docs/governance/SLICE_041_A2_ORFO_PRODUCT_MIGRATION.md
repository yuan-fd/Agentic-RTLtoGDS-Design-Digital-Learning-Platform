# Slice 041: A2-ORFO product-route migration

## Boundary

This slice changes only the supported L2 product route:

```text
before: L1 -> ORFS-Agent optimizer/controller -> ORFS execution
after:  L1 -> A2-ORFO optimizer/controller -> ORFS-Agent 12-D executor
                                      -> Runtime -> protected evaluator
```

ORFS-Agent is retained as the complete 12-D variable-clock candidate executor.
Its completed 78-run campaign remains historical evidence and is neither
deleted nor relabelled. No local optimizer is added and no A2 research logic
is reimplemented.

## Product protocol

The pinned A2 launcher declares `TOTAL_ITERS=6` and `PARALLEL_RUNS=25`.
Iteration one contains 25 perturbed candidates plus the upstream default row;
the following five measured iterations contain 25 candidates each. The
product controller therefore freezes:

```text
26 bootstrap measurements + 5 * 25 feedback measurements = 151 EDA runs
```

The upstream launcher has no independent confirmation phase, so this protocol
uses zero confirmations. That does not remove any of the 151 native-sized
measurements. The generic ORFS execution-domain validator now permits a
non-negative confirmation count while requiring every actual execution count
to remain positive.

Acceptance found and removed one obsolete smoke-only restriction: A2 policy
tasks and the controller allowed at most 16 suggestions even though the pinned
launcher requires 25. The shared bounded ceiling is now 64. Tests explicitly
freeze the product value at 25 so this cannot silently regress.

## Authority and lifecycle

- `DEFAULT_PRODUCT_SURFACE` authorizes only `a2-orfo` with
  `optimizer.l2.a2-orfo-feedback` for the L2 product role.
- Workbench escalation creates a durable `a2-orfo-campaign-v1` controller and
  submits no optimizer or EDA work.
- Configuration binds the A2 and ORFS-Agent domains, commits, objective set,
  seeds, protected input receipts and complete budget.
- HTTP always invokes `l2_advance(..., execute=False)`.
- `apps/l1_workbench/a2_campaign_worker.py` is the sole product composition
  that advances with `execute=True`; stable TaskSpec IDs and Runtime's
  idempotent submission provide restart safety.
- Candidate failures remain observations and are returned to A2-ORFO. Only
  protected-evaluator artifact-backed metrics are measured QoR.

## Changed files

- `packages/contracts/src/openroad_platform_contracts/product_surface.py`
- `packages/execution/src/openroad_platform_execution/a2_orfo_plugin.py`
- `packages/execution/src/openroad_platform_execution/orfs_agent_domain.py`
- `packages/scheduler/src/openroad_platform_scheduler/a2_orfo_campaign.py`
- `apps/l1_workbench/service.py`
- `apps/l1_workbench/server.py`
- `apps/l1_workbench/a2_campaign_worker.py`
- `apps/l1_workbench/l2_campaign_evidence.py`
- focused product, campaign, domain, handoff and worker tests
- `scripts/run_a2_orfo_product_migration_acceptance.py`
- this record and the Workbench/status documentation

## Tests and bounded acceptance

Focused migration tests: `39 passed`.

Canonical acceptance:

```text
var/evidence/a2-orfo-product-migration-20260905-r3/summary.json
SHA-256 86aefcc9c9b7f08199e080d6c4f1da70e7eed6c5052a97d7e49cfc991d656b3c
```

It reopens the durable configured checkpoint, proves the 151-run budget,
shared 12-D domain, variable `CLK`, exclusive product role, and API/worker
execution split. It submits no campaign measurement. The real native
A2-ORFO -> Runtime ORFS -> protected evaluator -> A2 feedback loop remains
proven by:

```text
var/evidence/a2-orfo-single-feedback-20260905-r4/summary.json
SHA-256 c11638e49bf345987afda2f7159856a67cb4b1f962ceb6a8520d95f6ff7f55aa
```

The retained `r1` and `r2` migration directories are failed debugging
attempts: `r1` exposed the zero-confirmation compatibility defect and `r2`
exposed an acceptance-script attribute error. Neither may be cited as accepted
evidence.

## Protected and unrelated behavior

No RTL, PDK, SDC, evaluator, objective baseline, upstream checkout, source
lock, or historical experiment was modified. No AgenticPD route was touched.
The 151-run campaign was not started.

## Rollback

Restore the prior L2 product rule and Workbench controller composition, remove
the A2 worker and new product-shape tests, and revert the two bounded validation
changes. Preserve every Runtime/checkpoint/evidence record, including failed
acceptance attempts, as historical evidence.
