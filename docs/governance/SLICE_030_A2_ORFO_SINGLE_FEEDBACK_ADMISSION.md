# Slice 030: A2-ORFO bounded policy admission and single feedback loop

Status: **complete**

Date: 2026-09-05

## Boundary and intended change

Admit pinned A2-ORFO as a policy plugin only:

```text
artifact-backed measured observations
  -> native A2-ORFO OptimizationWorkflow.run_iteration
  -> typed complete 12-D proposal
  -> Runtime ORFS execution
  -> protected evaluator
  -> measured feedback
  -> native A2-ORFO next proposal
```

A2-ORFO does not launch ORFS, SSH, shell text written by a model, or declare
QoR/success.  Runtime remains the process and state authority.  The existing
ORFS-Agent campaign remains independent historical work.

## External admission

- upstream: `https://github.com/CODA-Team/TaiWei-flow-Agent.git`;
- commit: `8b20a3c1f22934a39c7ba51ed0ec6dffe730da2d`;
- tree: `b3906db597359f5786e6cfc69f308479e26f5800`;
- license: BSD-3-Clause, Green with notice retention;
- embedding model: `mixedbread-ai/mxbai-embed-large-v1` commit
  `b33106f585b9ce46904ad7443a3b52b7a63e231c`, Apache-2.0;
- model tree SHA-256:
  `feeb00c02e146d3a09d8b825af77224c2bbcc158bd5e2a5dbb18c3904d067f26`;
- isolated Python lock SHA-256:
  `dae5ddaf71b437c0e13996a8edbff881a61ca68a5cfab2654713a0019ae0edc6`.

The upstream launcher paths `maindriver.sh`, `run_parallel.sh`, SSH helpers,
and `run_or_job.py` are denied.  The adapter creates an attempt-private
`git archive`; all generated designs/logs/prompts and the model symlink stay in
that private copy.

The upstream requests `DeepSeek-R1`.  The admitted environment uses the
platform-managed Codex CLI with `gpt-5.6-terra`; every call records requested
model, executed model, prompt/schema/result hashes and typed arguments.  No API
key is accepted in a TaskSpec or persisted in an artifact.

## Compatibility decisions

Two bounded adaptations are recorded in every policy trace:

1. the native launcher's measured baselines are supplied from the frozen
   protocol in the attempt-private `opt_config.json`;
2. `OptimizationWorkflow.param_constraints` is bound before execution to the
   same commit's formal 12-D AutoTuner `constraints.json` because the ranges
   hard-coded inside `optimize.py` diverge from it.

The existing upstream inspection, RAG, statistical analysis, ReAct GPR,
candidate generation, supervisor and TextGrad paths are invoked.  Candidate
values are never post-hoc clipped by the platform, and no dimension is fixed
or removed.

## Changed files

- `docs/governance/A2_ORFO_INTAKE.md`
- `docs/governance/SLICE_030_A2_ORFO_SINGLE_FEEDBACK_ADMISSION.md`
- `integrations/a2_orfo/source.lock.json`
- `integrations/a2_orfo/environment.lock.json`
- `integrations/a2_orfo/a2_orfo_adapter.py`
- `integrations/a2_orfo/a2_orfo_managed_provider.py`
- `packages/execution/src/openroad_platform_execution/a2_orfo_plugin.py`
- `packages/execution/src/openroad_platform_execution/__init__.py`
- `packages/execution/src/openroad_platform_execution/orfs_agent_task.py`
- `packages/scheduler/src/openroad_platform_scheduler/runtime.py`
- `packages/analysis/src/openroad_platform_analysis/orfs_protected_evaluator.py`
- `scripts/run_a2_orfo_single_feedback_acceptance.py`
- `tests/test_a2_orfo_plugin.py`

## Before and after dependency edge

Before: the platform had a full ORFS-Agent proposal/execution path but no
admitted A2-ORFO identity or safe way to invoke its RAG/ReAct/supervisor policy.

After: a typed `a2-orfo` policy TaskSpec invokes only the pinned native policy;
its proposal is explicitly handed to the existing Runtime-owned ORFS executor,
whose evaluator records `a2-orfo-proposed-runtime-orfs-candidate` provenance.

## Tests and real evidence

Focused regression:

```text
python3 -m pytest -q tests/test_a2_orfo_plugin.py
3 passed

python3 -m pytest -q tests/test_a2_orfo_plugin.py \
  tests/test_runtime_protected_evaluator.py \
  tests/test_orfs_agent_full_domain.py tests/test_orfs_agent_plugin.py
27 passed
```

Canonical acceptance:

- summary:
  `var/evidence/a2-orfo-single-feedback-20260905-r4/summary.json`;
- summary SHA-256:
  `c11638e49bf345987afda2f7159856a67cb4b1f962ceb6a8520d95f6ff7f55aa`;
- first A2 policy Runtime run: `ae6da176d4b34bbf831bb99c1cb6b7d9`;
- ORFS candidate Runtime run: `335167f6f3bc4c15a03796e015bb7101`;
- feedback A2 policy Runtime run: `3b66e823738e406daaa575259aa715e6`;
- protected evaluation ID:
  `96da584fbe81a31fb6fd678c46037929c14ac7106ade67722bafa01ce0243b05`;
- protected evaluation SHA-256:
  `b6f3555283501d0d35d8ba3173727c3a63d8e23c993c4e99868882c8e5067621`.

Both A2 runs loaded 580 documents with 1024-dimensional embeddings.  Provider
traces show exact stage dispatch and explicit model substitution.  The first
and next proposals each contain all 12 formal fields.

The candidate completed Runtime execution but was correctly marked infeasible
by the protected evaluator: WNS `-3.85937 ns`, TNS `-725.629 ns`, zero DRC,
area `140746 um^2`, power `2.62627 W`, and missing `6_final.gds`.  That
infeasible result, its evaluation ID and source artifacts were preserved and
consumed by the second A2 call.  This proves integration and feedback, not PPA
superiority or a complete A2 campaign.

Retained failed/invalid attempts:

- `...-r1`: provider schema incompatibility;
- `...-r2`: incorrect stage dispatch (invalid as acceptance evidence);
- `...-r3`: upstream domain divergence caught before EDA.

## Protected and unrelated behavior

No protected RTL, PDK, SDC, frozen evaluator rule, ORFS source checkout, A2
source checkout, or existing campaign checkpoint was modified.  The real
candidate used the already admitted pinned ORFS toolchain and evaluator.  The
running legacy 78-measurement ORFS-Agent campaign was neither stopped nor
relabelled.

## Rollback

Stop constructing/registering `a2_orfo_plugin_manifest` and remove the
`a2-orfo` Runtime receipt branch.  Continue accepting the existing
`orfs-agent` plugin.  Preserve source locks, failed attempts, Runtime databases,
workspaces and summary hashes as historical evidence; do not route A2 requests
to the legacy ORFS-Agent identity.

