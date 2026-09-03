# ORFS-Agent full-reproduction intake

Status: **internal execution authorized; admission in progress**

## Scope

This intake covers a full upstream-style ORFS-Agent reproduction capability,
not the historical five-knob fixed-SDC platform comparison protocol.  The
capability retains the upstream parameter domain, initialization, objectives,
and variable-clock experiment semantics while the platform retains workspace
isolation, resource limits, provenance, artifacts, and Dashboard read models.

## Authorization and redistribution boundary

On 2026-09-02, the project owner stated that this work is being performed
inside Zhiang Wang's group, that the ORFS-Agent author requested the
integration, and that internal retrieval, execution, and integration are
authorized.  This is an **internal-use authorization record**.  It does not
grant a claim to relicensing, vendoring, or public redistribution of either
upstream project.  The platform continues to use external pinned worktrees.

## Upstream identities

| Component | Source | Required revision | Status |
| --- | --- | --- | --- |
| ORFS-Agent | `https://github.com/ABKGroup/ORFS-Agent.git` | `730f1fa11f9c17c0aaac332412af2b2538f42e9b` | BSD-3-Clause; admitted source lock exists. |
| Paper ORFS flow | `https://github.com/The-OpenROAD-Project/OpenROAD-flow-scripts.git` | `ce8d36a7fef0ab9c47d183bcf078bce0f60f5a54` | Internal execution authorized; isolated worktree and submodule/tool audit pending. |

## Native entrypoints and adaptation boundary

- Upstream complete controller: `maindriver.sh`.
- Upstream initialization/config materialization: `run_sequential.sh`.
- Upstream parallel launcher: `run_parallel.sh`.
- Upstream iterative policy: `optimize.py` and its dependencies.
- Upstream AutoTuner analyst/GP-EI workbench:
  `AutoTuner-integration/ORFS-with-AutoTuner/analyst_agent_workbench.py`.

The platform must not execute the upstream shell launcher against a shared
ORFS checkout: it edits a Makefile, creates per-candidate configuration/SDC
files, cleans old outputs, and assumes named SSH hosts.  The Adapter instead
must materialize identical candidate inputs in an isolated Runtime workspace
and let Runtime own scheduling, timeout, cancellation and artifacts.

## Required reproduction semantics

1. Full 12-variable domain: utilization, global/detail padding, flattening,
   pin/upper-layer adjustment, timing-repair percentage, LB addon, CTS size/
   diameter, DPO, and clock period.
2. Upstream local initial perturbation around the selected design baseline.
3. ECP, DWL, and COMBO objectives, including the upstream surrogate metrics.
4. Candidate-specific SDC/clock materialization only within this reproduction
   protocol; it must never be presented as a fixed-constraint fair-PPA claim.
5. Original raw metrics plus the platform's final-signoff evaluator side by
   side.  A signoff-infeasible point remains visible rather than disappearing.
6. A `gpt-5.6-terra` policy substitution is labeled as such; it is not a
   byte-for-byte reproduction of the paper's Claude-3.5 Sonnet interaction.

## Isolation and network policy

- One clean detached ORFS worktree, one pinned Python environment and one
  candidate Runtime workspace per reproduction plugin deployment.
- No mutation of the shared ORFS checkout or of an upstream checkout.
- GitHub is the canonical source.  If a required fetch fails transiently,
  use the Tsinghua Git mirror only for retrieval, then verify canonical URL,
  commit and file hashes before admission.

## Acceptance evidence required

- exact source and submodule commit receipts;
- environment lock and tool-version receipt;
- native local one-candidate execution in the isolated worktree;
- Runtime one-candidate execution through the plugin Adapter;
- verification of all 12 parameter-to-config/SDC mappings;
- a bounded upstream-style multi-candidate smoke before any paper-scale run.

## Execution adapter boundary (2026-09-02)

The former `orfs-agent` bridge is **not** used as the execution path for this
protocol.  It expresses the historical shared-domain intersection and cannot
represent the paper's candidate-specific clock, routing-layer, or hierarchy
fields.  The new `orfs-agent-paper-reproduction` adapter has one narrow job:
execute one upstream candidate in a Runtime attempt workspace.

The candidate schema is exactly the 12 fields from the upstream AutoTuner
`constraints.json`:

`CLK`, `UTIL`, `TNS_End_Percent`, `GP_PAD`, `DP_PAD`, `DPO`, `PIN_ADJ`,
`UP_ADJ`, `LB_ADDON`, `HIER_SYNTH`, `CTS_CSIZE`, and `CTS_CDIA`.

It copies the pinned paper flow and upstream `autotune_configs` to the attempt
workspace, then translates these fields directly to the variables used by the
upstream `run_or_job.sh` wrapper (`CLK_PERIOD`, `SYNTH_HIERARCHICAL`,
`FASTROUTE_TCL`, and so on).  It invokes `make tunereport`; it neither edits
the shared ORFS worktree nor substitutes candidate values.  The direct mapping
and raw `6_report.json`/`4_1_cts.json` evidence are saved in the attempt.

`CLK` remains variable here because that is an upstream reproduction semantic.
Any result from this capability must be labelled *variable-clock ORFS-Agent
reproduction*, never a fixed-SDC fair-PPA comparison.

The paper policy is also retained rather than replaced: its
`analyst_agent_workbench.py` loads its published full 12-D `constraints.json`
and creates proposals with `scikit-optimize` Gaussian Process / Expected
Improvement.  Because the paper used Claude-3.5 Sonnet but this platform uses
managed `gpt-5.6-terra`, Terra is restricted to a typed choice of measured
training rows.  It never writes a numeric candidate.  Thus the outcome is a
**model-substituted ORFS-Agent reproduction**, not a claim of byte-identical
Claude interaction.

## Isolated toolchain build receipt (in progress)

The paper flow pins OpenROAD `4ee14b488230e046c2e52d9094df85ccf299ac80` and
Yosys `3e0dc2ff1ee0dfec10e96b7eaaa774231ba4a248` as submodules.  No matching
binary was installed.  A separate, non-shared build was started at
`var/toolchains/orfs-ce8d36a-paper-build-20260902` with installation target
`var/toolchains/orfs-ce8d36a-paper-install-20260902`.

The initial CMake probe failed before compilation because the 2025 source
defaults to static Boost while the server's admitted dependency prefix provides
dynamic Boost only.  The isolated build uses `-DUSE_SYSTEM_BOOST=ON`; CMake
then found the same managed Boost 1.87 shared libraries and completed
configuration.  This is an environment-compatibility setting, not a source or
algorithm change.  A successful binary identity and a native candidate run are
still required before any reproduction claim.
