# L1 S3 Runtime bridge

Boundary: typed L1 tools may construct validated immutable capability tasks or
read Runtime-owned facts; they do not run EDA processes or own state.

Changed files: `l1_semantic_policy.py`, `l1_runtime_bridge.py`, `runtime.py`,
and `test_l1_runtime_bridge.py`.

Before: `L1ORFSToolService` retained experiments and states in process memory.
After: runs submit through `WorkflowRuntime`, cancellation and artifact excerpts
are Runtime ports, and observations reduce through S2 trace/state services.

Evidence: `tests/test_l1_runtime_bridge.py` includes a bounded
`WorkflowRuntime -> ProcessAdapter -> registered artifact` smoke and terminal
timeout/lost trace assertions.

Rollback: revert S3 commits beginning `8198c72` through the current S3 commit;
this removes only the new bridge/policy path and does not alter Runtime,
evaluator, external plugins, or historical traces.
