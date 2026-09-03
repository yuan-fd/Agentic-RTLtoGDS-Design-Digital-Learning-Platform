# ORFS-Agent plugin admission report

Status: **admitted as a bounded L2 Runtime plugin** on 2026-08-30.

This report records an integration admission, not a claim that ORFS-Agent
improves PPA.  The first proposed candidate was intentionally retained even
though all its repeated physical-design runs failed.  That is evidence that
the platform runs the real candidate, preserves an unfavourable outcome, and
does not call an unmeasured proposal an optimization result.

## What is admitted

| Item | Evidence |
| --- | --- |
| Upstream project | `https://github.com/ABKGroup/ORFS-Agent.git` |
| Pinned commit | `730f1fa11f9c17c0aaac332412af2b2538f42e9b` |
| License | BSD-3-Clause; `LICENSE` was inspected in a fresh detached checkout |
| Native algorithm | Upstream `analyst_agent_workbench.py`, using `scikit-optimize` Gaussian Process plus Expected Improvement |
| Platform role | typed task construction, Runtime isolation, source/commit check, parameter allowlist/translation, repeated OpenROAD measurements, protected QoR and provenance |
| Explicitly not replaced | ORFS-Agent's GP/EI model and its candidate generator |

The registered source is a separate clean detached checkout recorded in
`integrations/orfs_agent/source.lock.json`.  The older cached checkout is not
used by the admitted manifest.  A partially started extra clone caused by a
network-stalled fetch is not referenced by any manifest or Runtime task and is
left untouched as historical filesystem evidence rather than silently deleted.

## Plugin boundary

```text
Runtime observation artifacts
    -> ORFS-Agent adapter: full rows + artifact references
    -> Codex policy: chooses training row IDs only
    -> pinned upstream ORFS-Agent: GP/EI candidate generation
    -> adapter: quantize/map only the shared allowlisted knobs
    -> Runtime: launches repeated ORFS candidate runs
    -> protected evaluator v3: canonical feasible QoR or recorded failure
```

The model has no shell-text path and does not invent candidate numbers.  The
only tunable intersection in this integration is `UTIL`, `TNS_End_Percent`,
`GP_PAD`, `DP_PAD`, `DPO`, `LB_ADDON`, `CTS_CSIZE`, and `CTS_CDIA`.  Clock,
PIN_ADJ, UP_ADJ and HIER_SYNTH are explicitly frozen.  The adapter rejects a
source tree whose checked-out commit or BSD license does not match the lock.

## Native and platform experiment

The source was freshly cloned, detached to the pinned commit, and clean before
and after the experiment.  Its isolated Python environment contained pandas
2.3.3 and scikit-optimize 0.10.2.  The platform ran the following frozen
protocol on `nangate45` and GCD RTL (`gcd` top):

1. Run the same baseline three times, seeds 101, 211 and 307.
2. Export only Runtime-backed observations and their artifact references.
3. Run ORFS-Agent natively through the plugin adapter, with optimizer seed
   `20260830` and one requested GP/EI suggestion.
4. Map its proposal into the protected ORFS parameter allowlist.
5. Run that exact proposal three times, using the same seeds.
6. Preserve every terminal result and finish the fixed one-candidate budget.

Evidence root:

```text
var/orfs-agent-gcd-admission-20260830-tL9qOv/
```

### Baseline measurements

All three baseline runs reached `finish`, produced GDS/DEF/netlist/ODB, and
passed common evaluator v3.  Their measured QoR was identical; runtime varied
from 96.888 to 103.904 seconds.

| Metric | Median |
| --- | ---:|
| Area | 595.042 um² |
| Setup WNS | 7.46494 ns |
| Power | 0.000122138 W |
| DRC errors | 0 |
| Runtime | 103.888 s |

The three canonical evaluator IDs are
`31d6b803…c4f9abef`, `c8c7a37a…3bb47bb09`, and
`d8d20b04…edaa49c7`; their complete immutable JSON reports and registered
SHA-256 values remain in the three attempt workspaces.

### What upstream ORFS-Agent proposed

The real native workbench reported `scikit-optimize GP + EI`; the model-policy
trace selected rows 0 and 1 and explicitly stated that the three baseline
rows had no parameter diversity.  Its one raw proposal was:

```text
UTIL=58, TNS_End_Percent=48, GP_PAD=2, DP_PAD=0, DPO=1,
LB_ADDON=0.0655867347, CTS_CSIZE=27, CTS_CDIA=115
```

The adapter preserved the raw values and transported the executable vector as
`place_density_lb_addon=0.07` (the platform's 0.01 quantization), with all
other values retained.  The candidate file and full policy trace are Runtime
artifacts under the optimizer attempt
`788737d5462f409fb4c27f76a1bbeb2e`.

### Candidate result: failure is retained, not hidden

All three candidate replicas reached the actual OpenROAD placement stage and
failed consistently with `FLW-0024` in `global_place_skip_io.tcl`.  They did
not receive a QoR score and were not marked as improvements.  The durable L2
checkpoint therefore ended as `completed / fixed_candidate_budget_exhausted`,
with `eligible: false`, no best-candidate update, and all three failure
receipts retained.

This is the correct result for this bounded admission run.  It proves the
closed-loop safety property—an upstream proposal goes through the same ORFS
and evaluator gate as any other configuration—and it disproves any claim that
this proposal improved the baseline.

## Changes made for admission

- The adapter now accepts only a Runtime-configured source root whose commit
  and license match the lock; it does not use an arbitrary cache path.
- The adapter seeds process-level RNGs before calling the unchanged upstream
  GP/EI workbench.  This makes a fixed Runtime task reproducible without
  changing upstream GP/EI code.
- A typed `build_orfs_agent_native_task()` requests native GP/EI without
  embedding an optimizer in the platform.
- `scripts/run_orfs_agent_admission.py` creates the complete bounded protocol
  and validates artifact hashes.
- API composition registers ORFS-Agent only when the reviewed lock has the
  exact bounded-admission status; missing source/environment still fails
  closed.

## Verification and rollback

Focused plugin/API regression checks passed:

```text
tests/test_l2_external_admission.py
tests/test_orfs_agent_plugin.py
tests/test_external_l2_service.py
tests/test_web_app.py
```

The static package-boundary suite and `git diff --check` also pass.  Rollback
is a normal Git revert of the admission adapter/builder/composition files and
the lock status.  Do not delete the evidence directories: both the failed mux
preflight (`var/orfs-agent-admission-20260830-lgR75Z/`) and the GCD admission
campaign are part of the audit trail.

## Honest operating limit and next research task

This admits ORFS-Agent as an executable L2 plugin; it does **not** establish
PPA superiority.  The cold-start protocol currently has repeated baseline
measurements but no diverse warm-up design of experiments.  As the recorded
policy trace says, GP/EI therefore had no informative parameter variation and
its first candidate was exploratory and infeasible.

Before any paper-quality optimizer comparison, freeze a separate L2 campaign
protocol with a small, evidence-backed diverse warm-up set, repeated baselines,
fixed candidate budget, random/Sobol controls, and repeated feasible-candidate
measurement.  That is a distinct algorithm-evaluation slice, not something
to smuggle into this plugin admission result.
