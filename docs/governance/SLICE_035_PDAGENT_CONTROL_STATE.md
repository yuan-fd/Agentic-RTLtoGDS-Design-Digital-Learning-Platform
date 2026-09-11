# Slice 035: PDAGENT-inspired L1 control state

## Boundary

This slice adapts the public architecture in PDAGENT-BENCH
(`arXiv:2606.17253v6`) into typed, durable Planner/Analyzer/Debugger control
states. It does not copy or execute PDAGENT code, add a tool command surface,
change Runtime, implement an optimizer, or connect a benchmark dataset.

## External reference stop and resolution

**Problem.** The paper says the framework and benchmark "will" be released,
but the repository previously recorded as `Thinklab-SJTU/EDA-Agent` is not
publicly resolvable, GitHub search returns no PDAGENT-BENCH repository, and no
commit/license can be verified.

**Evidence.** The arXiv v6 paper and Atom metadata are public. The paper
defines Planner, Worker, Analyzer, Debugger and Optimizer roles; the success
and failure paths; `improving/stalled/diverging`; and micro/meso/macro recovery
budgets. Repository lookup returned `Repository not found` on 2026-09-05.

**Why the direct plan fails.** Without a repository, commit and license, the
external-project intake gate forbids vendoring, running, or registering its
implementation.

**Option A.** Wait for the authors' release, then perform a complete intake.

**Option B.** Cite the paper only and adapt its role topology to existing
platform contracts, with no code reuse or claims of behavioral equivalence.

**Recommendation.** Option B for this slice; Option A remains required before
any future executable PDAGENT integration. This preserves progress without
misrepresenting metadata as an admitted dependency.

## Architecture mapping

```text
PDAGENT Planner  -> typed L1 PlannerState hub
PDAGENT Worker   -> existing Policy + Runtime (never direct TCL/shell)
PDAGENT Analyzer -> deterministic StageAnalysis/DiagnosisReport
PDAGENT Debugger -> typed recovery proposal only
PDAGENT Optimizer-> external L2 boundary; no optimizer in L1
```

The fixed transitions are:

```text
planning -> awaiting_runtime -> analyzing
  -> reviewing -> next stage / completed
  -> debugging -> retry / typed-fix request / rollback / skip / escalate / stop
```

Retry consumes micro budget, typed-fix request consumes meso budget, and
rollback consumes macro budget. A Debugger cannot emit commands or directly
execute its proposal.

## Changed files

- `packages/contracts/src/openroad_platform_contracts/l1_control_state.py`
- `packages/contracts/src/openroad_platform_contracts/__init__.py`
- `packages/scheduler/src/openroad_platform_scheduler/l1_control_state_machine.py`
- `packages/scheduler/src/openroad_platform_scheduler/__init__.py`
- `tests/test_l1_control_state_machine.py`
- `scripts/run_l1_control_state_acceptance.py`
- this record

## Tests and real bounded acceptance

Focused tests cover durable lineage, the clean success path, the Debugger
path, budget consumption, budget exhaustion, mismatched recovery classes, and
typed escalation.

Canonical acceptance replays the real A2-ORFO candidate Runtime evidence with
protected setup WNS `-3.85937 ns` through an append-only control database:

```text
planning -> awaiting_runtime -> analyzing -> debugging -> failed

var/evidence/l1-pdagent-control-state-20260905-r1/summary.json
SHA-256 9360cb95377cd7c1f57e105d95776557337f300a6451a2b482702af82751d158
accepted true
```

It detects the timing blocker, binds Analyzer and Debugger states to the same
DiagnosisReport and protected artifact, proposes a typed `stop`, and performs
no EDA or artifact mutation. This is a state-transition acceptance, not a
debug-fix or benchmark-quality claim.

## Protected and unrelated behavior

No Runtime authority, evaluator, RTL, PDK, SDC, plugin, campaign, or upstream
source changed. The A2 evidence SHA remains byte-identical.

## Rollback

Remove the control contracts, state machine/store exports, tests, acceptance
script, and this record. Existing L1 loop and all prior evidence remain valid.
