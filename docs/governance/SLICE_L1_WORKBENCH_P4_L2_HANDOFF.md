# L1 Workbench P4: evidence-backed L2 external handoff

`OptimizationRequest` is a dependency-free, versioned contract that binds a
durable L1 trace, finalized Goal, evidence-backed terminal State, frozen budget,
protocol evidence and search-space evidence to one admitted external capability.

`OptimizationHandoffService` authorizes only `ProductRole.L2_OPTIMIZATION`,
constructs a plugin-owned `TaskSpec` through an injected adapter, attaches only
correlation/evidence labels, then asks Runtime to submit it. It has no GP/EI,
candidate generation, QoR parsing, evaluator, shell command, or legacy external
loop dependency.

The approved current identity is `orfs-agent / optimizer.l2.propose`; no new
`eda.dse.optimize` capability is invented because it would silently diverge
from the admitted plugin manifest. P5 supplies the pinned adapter smoke.

Rollback: revert these two modules, tests, and this record. No Runtime,
evaluator, upstream algorithm, or historical material is modified.
