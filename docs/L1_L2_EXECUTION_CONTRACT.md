# L1/L2 Execution Contract

This document defines the v2 control boundary.  It is deliberately narrower
than white-box tool modification: OpenROAD source code is not an action surface
in L1 or L2.

## L1: typed execution

The approved target product entry is:

```text
natural-language SpecIR -> platform-managed RTLScout -> independent verification
-> verified RTL artifact -> DesignGoal / typed policy -> admitted ORFS-Agent plugin
-> immutable TaskSpec -> Runtime -> raw OpenROAD/ORFS artifacts -> protected QoR
-> DesignState + EDAIR evidence
```

`DesignGoal` fixes the PDK, toolchain identity, hard constraints, stages,
registered parameter names, tool allowlist and budgets.  `DesignState` records
the observed stage, QoR, evidence and remaining budget.  The LLM may issue a
`SemanticToolCall`, but it cannot provide a shell command, executable path,
credential, unregistered parameter or new tool name.

The future L1 runtime adapter for an already verified RTL task must support
creation of an experiment, legal parameter changes, stage submission, bounded
queries, comparison and stop/escalate.  A submitted run must be reported as
`accepted`; only the protected evaluator may later publish an observed state.
This prevents a UI or LLM response from presenting queued work as QoR.

### Transitional provenance exception

The legacy direct-import route remains reachable.  P0 does not claim a product
L2 provenance gate exists yet; a later P2 slice must isolate direct import to a
research/fixture surface and reject an L2 product request lacking verified RTL
provenance.

## L2: admitted black-box tuning plugin

L2 does not alter OpenROAD source.  Its division of authority is:

| Component | Authority |
| --- | --- |
| L1 policy | Select a permitted capability, legal parameter subspace, hypothesis and stop condition from evidence. |
| Policy gate | Reject a mode, parameter or tool outside `DesignGoal`. |
| ORFS-Agent plugin | Own its pinned upstream candidate-selection logic and checkpoint semantics. |
| Runtime/common evaluator | Execute and measure; predictions are never canonical QoR. |

The platform does not expose a local BO/GP, stateful portfolio, or optimizer
fallback as a product capability.  ORFS official AutoTuner and seeded random
control are permitted only as frozen, equal-budget research comparators.  A
flow/process failure remains an observed Runtime fact; only the protected
evaluator can publish canonical feasibility and QoR.

## Study evidence

Historical local-portfolio studies remain preserved as research evidence.  They
are not evidence for, or a fallback from, the future admitted product path; any
comparison requires a new frozen protocol with common inputs, budget, seeds,
evaluator and statistics.
