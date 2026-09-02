# L1 S3 Runtime bridge

Boundary: typed L1 tools may construct validated immutable capability tasks or
read Runtime-owned facts; they do not run EDA processes or own state.

Changed files: `l1_semantic_policy.py`, `l1_runtime_bridge.py`,
`test_l1_runtime_bridge.py`, and this record. Runtime is unchanged.

Before: `L1ORFSToolService` retained experiments and states in process memory.
After: runs submit through `WorkflowRuntime`; the bridge's bounded adapter
reads registered workspace artifacts with hash verification, and cancellation
is an injected existing authority. Observations reduce through S2 services.

Evidence: `tests/test_l1_runtime_bridge.py` includes a bounded
`WorkflowRuntime -> ProcessAdapter -> registered artifact` smoke and terminal
timeout/lost trace assertions.

Rollback: revert commits `8198c72`, `676f2b9`, `7c2ade0`, `7cb2679`,
`6f43f59`, `27568da`, `576e044`, `be7b5e1`, `7d857b9`, `5a64a11`, and
`7445e8a`; this removes only S3 bridge/policy/test/docs changes.
