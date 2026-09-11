# Slice 021 — Complete upstream ORFS-Agent campaign execution

## Intended architectural change

Turn the authorized L2 checkpoint from Slice 020 into a resumable execution
controller for the complete upstream ORFS-Agent domain. The production path is

```text
upstream initializer
→ Runtime candidate measurements
→ artifact-backed observations
→ managed analyst row policy + pinned upstream GP/EI
→ Runtime candidate measurements and feedback
→ repeated rounds
→ independent-seed confirmations
```

The search domain is the exact 12-field `constraints.json` contract, including
candidate-specific `CLK`. It supports the upstream ECP, detailed-route
wirelength, and fractional-loss objectives. No 8-D projection, baseline merge,
grid snapping, fixed-clock substitution, or local optimizer is on this path.

## Files changed

- `integrations/orfs_agent/orfs_agent_full_initializer_adapter.py`
- `integrations/orfs_agent/orfs_agent_adapter.py`
- `integrations/orfs_agent/orfs_agent_paper_policy_adapter.py`
- `integrations/orfs_agent/orfs_agent_reproduction_adapter.py`
- `integrations/orfs_agent/environment.lock.json`
- `integrations/orfs_agent/README.md`
- `packages/execution/src/openroad_platform_execution/orfs_agent_domain.py`
- `packages/execution/src/openroad_platform_execution/orfs_agent_task.py`
- `packages/execution/src/openroad_platform_execution/orfs_agent_plugin.py`
- `packages/execution/src/openroad_platform_execution/adapter.py`
- `packages/execution/src/openroad_platform_execution/__init__.py`
- `packages/scheduler/src/openroad_platform_scheduler/orfs_agent_full_campaign.py`
- `packages/scheduler/src/openroad_platform_scheduler/runtime.py`
- `packages/scheduler/src/openroad_platform_scheduler/__init__.py`
- `packages/analysis/src/openroad_platform_analysis/orfs_protected_evaluator.py`
- `apps/l1_workbench/l2_campaign_evidence.py`
- `apps/l1_workbench/l2_campaign_worker.py`
- `apps/l1_workbench/service.py`
- `apps/l1_workbench/server.py`
- `apps/l1_workbench/README.md`
- `scripts/run_orfs_agent_full_candidate_smoke.py`
- `tests/test_orfs_agent_full_domain.py`
- `tests/test_orfs_agent_full_campaign.py`
- `tests/test_orfs_agent_reproduction_adapter.py`
- `tests/test_l2_campaign_worker.py`
- focused evaluator, plugin, Runtime, and Workbench tests changed with this
  boundary
- this evidence record

## Before and after dependency edge

Before: the product could authorize a complete ORFS-Agent role, but it had no
controller that called the upstream initializer, executed every proposed point
through Runtime, fed measured rows to upstream GP/EI, or confirmed an incumbent.
The only paper candidate executor lived behind a separate reproduction plugin
identity and did not produce a campaign.

After: `ORFSAgentFullCampaignService` knows only typed full-domain task builders,
Runtime status, registered evidence callbacks, and durable checkpoints. All
three modes use the single admitted `orfs-agent` plugin identity. Numeric
candidate creation belongs to the pinned upstream initializer and upstream
scikit-optimize GP/EI. EDA execution and protected evaluation belong to
Runtime. The HTTP API can authorize, configure, schedule, and read but forces
`execute=false`; the independent trusted worker is the only Workbench process
that advances with `execute=true`.

## Integrity and recovery properties

- Domain and protocol objects are self-hashed and fail closed if fields are
  removed, reordered at the adapter boundary, or changed.
- Protocol receipts bind the exact ORFS-Agent commit, paper ORFS commit,
  design and PDK Git objects, AutoTuner config/SDC/FastRoute bytes, OpenROAD,
  Yosys, Yosys data tree, architecture, and audited runtime environment.
- Candidate TaskSpecs carry all 12 raw fields and a separate Runtime `OR_SEED`.
- Stable TaskSpec IDs plus `submit_idempotent()` make every submission
  crash-recoverable. A checkpoint is saved after each individual submission.
- Candidate failures retain their legal materialization/config/log artifacts.
  They remain in terminal observation/history records and are never presented
  as measured successes.
- The controller submits exactly the frozen budget and caps actual worker
  concurrency at the authorized `max_parallel` value.
- The optimizer consumes only rows with a numeric requested objective and
  registered artifact references. Confirmation runs repeat the same incumbent
  under distinct, frozen seeds.
- Adapter metrics are explicitly non-canonical. Only the protected evaluator
  emits `official_qor=true`; variable-clock objective metrics are retained in a
  separately labeled metadata object and never claimed as fixed-SDC fair PPA.

## Upstream and license evidence

- ORFS-Agent upstream: `https://github.com/ABKGroup/ORFS-Agent.git`
- exact commit: `730f1fa11f9c17c0aaac332412af2b2538f42e9b`
- license: BSD-3-Clause; validated from the clean detached execution checkout
- constraints SHA-256:
  `9de2da8058266f8287b153a06ecafbc3698281b24ea226f9e72e458336dcf7ad`
- paper ORFS commit:
  `ce8d36a7fef0ab9c47d183bcf078bce0f60f5a54`
- upstream initializer entrypoint:
  `OptimizationWorkflow.generate_initial_parameters`
- upstream GP/EI entrypoint:
  `analyst_agent_workbench.suggest_bayesian_optimization_configs`

The committed upstream `optimize.py` contains a syntactically incomplete API
key placeholder and imports optional analysis modules with an undeclared
dependency. The initializer adapter makes only those two compatibility changes
in its Runtime-private copy, records before/after hashes, and invokes the
unchanged upstream initializer method body. Neither clean checkout is modified.

## Acceptance evidence

Focused regression after the controller and worker changes:

```text
40 passed in 35.63s
9 passed in 1.27s
25 passed in 16.04s
2 passed in 0.41s
30 passed in 18.74s
```

These overlapping focused groups cover exact 12-D transport, the real upstream
initializer, Runtime failure artifacts, protected evaluator semantics, durable
campaign restart/idempotence, failed-candidate feedback handling, independent
confirmation seeds, authorization parallelism limits, the scheduling-only API,
and the independent worker boundary. The final whole-repository count is
recorded by the final audit, not inferred by adding these groups.

Real candidate evidence is intentionally cumulative:

1. `var/evidence/orfs-agent-full-candidate-smoke-20260904` failed before
   synthesis because the pinned Yosys binary's compiled `share/yosys` data
   layout did not match its installation. The compatibility symlink repairs
   only the installed tool layout; its data-tree hash is part of the receipt.
2. `var/evidence/orfs-agent-full-candidate-smoke-20260904-r2` completed the
   complete AES/Sky130HD flow with zero detailed-route violations and produced
   final reports. Runtime then correctly exposed a platform artifact-contract
   defect: the adapter registered `candidate_metrics.json` under two kinds,
   violating the one-store-key/one-artifact-identity constraint. The failure
   remains preserved. The adapter now emits a distinct, explicitly
   non-canonical `candidate_execution_report.json` index.
3. `var/evidence/orfs-agent-full-candidate-smoke-20260904-r3` ran the preserved
   upstream candidate whose source SHA-256 is
   `cb236045e53ede3879462998a527b26602e77b95e4b249fa2bf71e212dc613bf`.
   Runtime terminal status is `succeeded`; run ID is
   `243a959ddb4846ef9e5dad014d45f217`. The summary SHA-256 is
   `af546d9d3557da50c96eb23433eba4eb9dccca31f93758783511b67fffb9e60f`.
   Registered evidence includes distinct adapter metrics and report objects:
   `candidate_metrics.json`
   (`8f788fec99e2a3d48dbc73c2579d71f95d978c6d18b0a029ac20028ea9d73a21`)
   and `candidate_execution_report.json`
   (`c6ad659c66bb580e1e157efcc7f57ff6e2ddc11a84364997f29e2e36b9c93665`).
   The protected evaluation SHA-256 is
   `5033e85381e709cf420195bf60475260b04a035ff187d7fec300ce36a8d1929b`;
   its registered metadata states `official_qor=true`,
   `runtime_authority=protected_evaluator`,
   `qor_semantics=candidate-variable-clock-signoff`, and
   `fixed_sdc_fair_comparison=false`.
4. `var/evidence/orfs-agent-full-candidate-smoke-20260904-r4` repeats that
   preserved complete candidate under the current physical-output contract.
   Runtime terminal status is `succeeded`; run ID is
   `87672ea3d0d44b2da16548bfd261999b`, and the summary SHA-256 is
   `885d4a0e50fa9341e06e9c54414dfd5a4523f98ea70066d6efbf52cbf8d33883`.
   The sole attempt is `9ce865d9ee084774af8a1e16af2c6cb6`. Runtime registered
   12 artifacts under 12 unique store keys, and an independent post-run read
   rehashed every registered file successfully. In addition to the same
   metrics (`8f788fec99e2a3d48dbc73c2579d71f95d978c6d18b0a029ac20028ea9d73a21`),
   execution report
   (`c6ad659c66bb580e1e157efcc7f57ff6e2ddc11a84364997f29e2e36b9c93665`),
   and provenance
   (`8e054a8d2c324a9ecd2c2540a66a2c985c606a3ae9f6d8f1304e409b99fe7cd8`),
   the registered final physical outputs are:

   - ODB: `d77e240483e4ecb1ed2f21acc7d665c67b840881b0506baab2c03c932b2a963c`
   - DEF: `381976cc1281ff6fcf0370d1079ef890539ed4439676190c02d31cfe567c8994`
   - gate-level netlist:
     `58c0ca8f4ffd86275d3653e1d4e80e69bb548ea67b4bdc4828e01cc5f5b70f8b`
   - final SDC: `7ea0fc1c67e0b5be5cd275bf4ac6a7ad52911e87cda449f1e0fd683c3caae33c`
   - SPEF: `833118e309b805eef1f54963097ee2cf5cb1e8b1093c1fdfc6ac91a212677eba`

   The protected evaluation is
   `1651149ff9ce31019e8d03d8f83ed90ef35c1d0b3e8512bc8d2d69b5c5b6e846`.
   Its registered metadata again states `official_qor=true`,
   `runtime_authority=protected_evaluator`,
   `qor_semantics=candidate-variable-clock-signoff`, and
   `fixed_sdc_fair_comparison=false`. This remains a complete-candidate
   integration smoke, not a completed 78-measurement campaign or a PPA claim.

## Protected components and unrelated behavior

No benchmark RTL, PDK, AutoTuner SDC, FastRoute input, upstream constraint,
objective formula, evaluator threshold, or source checkout was changed to make
a candidate pass. The Yosys installation-layout link and attempt-private ORFS
compatibility patches are included in hashed receipts. Historical 8-D and
reproduction artifacts remain unchanged and are classified as legacy or
historical evidence; they do not define the product capability.

## Rollback

Revert only the files listed above for this slice. Preserve all Runtime SQLite
files and attempt workspaces as historical evidence. Remove the worker process
from service supervision before reverting its code. A rollback must also move
the product capability back to `authorized`/unavailable; it must not silently
route full-12-D requests into a legacy optimizer or paper-reproduction shim.
