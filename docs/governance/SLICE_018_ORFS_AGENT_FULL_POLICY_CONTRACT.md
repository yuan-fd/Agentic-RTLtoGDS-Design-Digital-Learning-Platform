# Slice 018 — ORFS-Agent full policy contract

## Intended architectural change

Make the sole product L2 optimizer policy capable of expressing the complete
upstream ORFS-Agent domain.  The new `upstream_full_policy` mode preserves the
twelve parameters `CLK`, `UTIL`, `TNS_End_Percent`, `GP_PAD`, `DP_PAD`, `DPO`,
`PIN_ADJ`, `UP_ADJ`, `LB_ADDON`, `HIER_SYNTH`, `CTS_CSIZE`, and `CTS_CDIA`, as
well as `ECP`, `DWL`, and `COMBO` and variable-clock semantics.

This slice does not claim candidate execution, a complete campaign, protected
evaluation, or paper PPA equivalence.  Those are separate acceptance slices.

## Files changed

- `packages/execution/src/openroad_platform_execution/orfs_agent_domain.py`
- `packages/execution/src/openroad_platform_execution/orfs_agent_task.py`
- `packages/execution/src/openroad_platform_execution/orfs_agent_plugin.py`
- `packages/execution/src/openroad_platform_execution/__init__.py`
- `integrations/orfs_agent/orfs_agent_adapter.py`
- `integrations/orfs_agent/orfs_agent_paper_policy_adapter.py`
- `integrations/orfs_agent/environment.lock.json`
- `integrations/orfs_agent/README.md`
- `tests/test_orfs_agent_full_domain.py`
- `tests/test_orfs_agent_plugin.py`
- `docs/governance/LEGACY_CLEANUP_INVENTORY.md`
- this evidence record

## Before and after dependency edge

Before: product imports resolved to a historical eight-field fixed-timing
builder, and the plugin manifest could execute a branch/dirty source path.

After: product imports expose a hash-bound full-domain `TaskSpec`; Runtime
invokes the same `orfs-agent` plugin ID in `upstream_full_policy` mode; the
adapter revalidates domain, protocol, observations, exact source commit,
detached state, clean worktree, and license before delegating numeric proposal
generation to upstream GP/EI.  The source-audit cache is rejected.

## Acceptance evidence

Focused suite on 2026-09-04: **49 passed**.  It includes a real Runtime process
smoke using the pinned ORFS-Agent virtual environment and upstream
scikit-optimize GP/EI.  The model stub only returns typed training row IDs.

Smoke workspace:
`/tmp/pytest-of-yuanwenjie/pytest-1469/test_full_policy_runs_upstream0/work/ce8863d383a04c65bc91fc159fbac3f5/363a0eb563954275950fc7fb94f86b74/attempt-1`

Key SHA-256 receipts:

- `adapter_result.json`: `3f42297aea401b61237e2376f7f680cd2875b26cbf7a3e041cdbf6b32909d1df`
- `paper_candidates.json`: `aa426dbf14c9cf82a4a0c381134708feb0f4686b12dc0127282f36f2bb7c11ea`
- `paper_policy_trace.json`: `5fe2fd17f1f3e68330fcb72c8e8cce7b2e489685a9514cba3ef8990fcc29eb1a`
- upstream `constraints.json`: `9de2da8058266f8287b153a06ecafbc3698281b24ea226f9e72e458336dcf7ad`

The historical eight-field native path is tested to fail closed when its
fixed clock is outside upstream constraints.  It is not repaired by snapping
or silently reducing the upstream search.

## Protected components and unrelated behavior

No evaluator, benchmark RTL, PDK, SDC, ORFS flow source, upstream ORFS-Agent
source, seed policy, or recorded campaign artifact changed.  This slice only
adds a typed policy boundary and admission checks; candidate execution remains
outside its scope.

## Rollback

Revert only the files listed above.  Keep all prior campaign directories and
historical evidence unchanged.  The rollback restores the old builder export
but does not authorize its reduced profile as complete ORFS-Agent behavior.
