# ORFS-Agent reproduction audit

Date: 2026-08-30  
Scope: pinned ORFS-Agent `730f1fa11f9c17c0aaac332412af2b2538f42e9b`

This is an evidence record.  It separates four different statements that are
often incorrectly compressed into the word “reproduced”.

| Statement | Current status | What proves it / what remains |
| --- | --- | --- |
| Source identity and license are admitted | Passed | Clean detached ORFS-Agent source at the locked commit; BSD-3-Clause checked; lock in `integrations/orfs_agent/source.lock.json`. |
| The upstream GP/EI algorithm is preserved at the platform boundary | Passed | `var/orfs-agent-native-parity-20260830-02/parity-report.json`: direct upstream call and Runtime Adapter returned identical five raw candidates from the same six rows, constraints, seed and isolated environment. |
| The complete Runtime protocol runs at official-scale shape | Restart pending | The first Sky130HD/AES attempt produced three feasible measured baselines, but its evidence exporter rejected their source-bundle identity before warm-up.  The failed attempt is preserved; a new campaign must rerun all replicas under the corrected, tested identity contract. |
| Published-paper PPA numbers are exactly reproduced | Not yet established | Paper README requires ORFS `ce8d36a`; prior platform campaign uses `51ad1231`.  Exact benchmark assets, tool binaries, objective/model layer and full launch protocol must be independently verified. |

## Fixed identities

| Component | Identity | Evidence |
| --- | --- | --- |
| Upstream plugin | `https://github.com/ABKGroup/ORFS-Agent.git` @ `730f1fa11f9c17c0aaac332412af2b2538f42e9b` | `integrations/orfs_agent/source.lock.json` |
| Upstream license | BSD-3-Clause | `LICENSE` SHA-256 `243601633b171278cd98f9ea495cbfc74aad9d7fc062c6e7c81e20d1fc44a22f` |
| Isolated plugin interpreter | `.tools/venvs/orfs-agent/bin/python`, Python 3.9.9 | `integrations/orfs_agent/environment.lock.json` |
| GP/EI dependencies | `numpy 2.0.2`, `pandas 2.3.3`, `scikit-learn 1.6.1`, `scikit-optimize 0.10.2`, `scipy 1.13.1` | `environment.lock.json` |
| Paper ORFS revision | `ce8d36a7fef0ab9c47d183bcf078bce0f60f5a54` | Upstream ORFS-Agent README, section “Prerequisites” |
| Paper-revision worktree | `var/toolchains/orfs-ce8d36a-paper` | Detached, clean superproject worktree created 2026-08-30 |
| Adapted campaign revision | `51ad1231a231ee85234c06db807688d029b85c35` | Campaign receipt; it is not labeled paper-identical |

## What is directly reused and what is adapted

The platform directly imports the pinned upstream
`analyst_agent_workbench.suggest_bayesian_optimization_configs` function.  Its
`scikit-optimize Optimizer(base_estimator="GP", acq_func="EI")` remains the
numeric candidate generator.  The Adapter only:

1. supplies artifact-backed Runtime observations in upstream row format;
2. freezes the platform’s fair common parameter domain;
3. seeds Python and NumPy at the process boundary; and
4. maps an auditable raw suggestion to the platform’s typed ORFS parameters.

The upstream full launcher is not executed by Runtime because it has a second
scheduler and unsafe assumptions: it mutates ORFS files, deletes result
directories, uses fixed remote host names through SSH, and expects an
Anthropic credentialed conversation.  The platform therefore uses a
model-substituted typed policy (`gpt-5.6-terra`) only to choose measured
training rows; it never generates numeric settings.  This is a **platform
adaptation**, not a claim of exact Claude-3.5-Sonnet agent replication.

## Exact-paper toolchain intake status

The first attempt to initialize a detached `ce8d36a` Git *worktree* is retained
as invalid environment evidence, not used as a toolchain.  During submodule
initialization its recorded Yosys gitlink was `3e0dc2ff…`, but its working
submodule resolved to `06ed2104…` and reported a deletion-heavy dirty state.
This violates the exact-environment admission gate.  It will not be repaired
in place, reset, or used for a paper comparison.  Once its still-running Git
operation ends, a wholly independent ordinary clone (rather than a Git
worktree sharing parent module administration) is the clean alternative.

The historical `setup.sh` explicitly requires `sudo`, which is outside the
allowed server installation policy.  The next admission step therefore remains
user-space only: clean source/submodule verification, then an inspection of
whether the historical sources can be built with separately installed,
user-space dependencies.  No current tool binary is being passed off as the
historical paper binary.

## Acceptance gates

1. **Native-core gate (passed):** exact raw GP/EI candidate parity.
2. **Environment gate (blocked by external network evidence):** a standalone,
   locked paper-revision ORFS environment that does not alter the active
   `51ad1231` worktree.  Two bounded GitHub acquisition attempts failed before
   a usable checkout; see the independent-admission incident below.
3. **Closed-loop gate (in progress):** repeated feasible baseline, 50 frozen
   warm-up runs, five 50-candidate upstream-GP/EI batches, and independent
   repeated confirmation, all measured by the protected evaluator.
4. **Paper-comparison gate (not started):** exact design/PDK/ORFS/tool/model
   identities plus equivalent published objective and statistics.  Only then
   may measured values be compared with the paper’s published numbers.

If a gate fails twice from the same root cause, the work stops for a written
problem/options decision instead of accumulating compatibility patches.

## 2026-08-31: locked-toolchain parameter-liveness calibration

**Purpose.** Before another Runtime-scale ORFS-Agent campaign is admitted, the
platform must establish that its allowed flow parameters actually reach the
locked ORFS `51ad1231` consumer.  This is not an optimizer experiment and does
not establish a beneficial QoR effect.

**Frozen execution receipt.**

| Item | Value |
| --- | --- |
| Evidence root | `var/calibration/orfs-51ad1231-asap7-v1` |
| ORFS identity | `51ad1231a231ee85234c06db807688d029b85c35` plus registered toolchain patch `9adff4b…ca58` |
| Design / platform | ORFS GCD / ASAP7 |
| Protocol | single-knob, low/mid/high, three paired OR seeds (`101, 211, 307`) |
| Executed cases | 90 / 90 Runtime-successful |
| Plan SHA-256 | `64bd327be5a3a8f1e60ca5be2b8461b28ae41609f9dd49763e4a9a8150b43a00` |
| Report SHA-256 | `23bafb2aac467a2f6aaa63a85ae56c07135820bca5c125934d8b76fa8776273a` |

The report marks `core_utilization_pct`, `cts_cluster_size`,
`cts_cluster_diameter`, `detail_placement_padding`, `enable_dpo`,
`global_placement_padding`, `gpl_routability_driven`,
`gpl_timing_driven`, `place_density_lb_addon`, and `tns_end_percent` as
search-eligible.  `routing_layer_adjustment` is explicitly **unresolved** and
therefore excluded.  The exclusion is part of the evidence, rather than an
invitation to treat that parameter as silently fixed-or-live.

**Boundary.** This controlled result proves only GCD/ASAP7 transport and
consumer-stage behavior.  It does not prove that a broad random configuration
is feasible for the target AES design, nor that any configuration improves
QoR.  In particular, it cannot rehabilitate or supply observations to the
historical successor-v3 AES campaign.  A new AES campaign must use a new
target-design feasibility receipt, a new output root, and all-new baseline,
warm-up, GP/EI and confirmation evidence.

### Decision record: target-design feasibility before a new AES campaign

**Problem.** The completed GCD calibration proves the eight ORFS-Agent shared
knobs are live on the locked toolchain, but it does not determine which
combinations are executable and evaluator-feasible for Sky130HD/AES at the
frozen 4.5 ns target.

**Evidence.** The historical, otherwise protocol-correct v3 AES warm-up
retained 50 attempted configurations: 41 failed in ORFS, nine reached the
evaluator, and only one distinct warm-up configuration was feasible.  Together
with the frozen baseline this yielded two distinct feasible observations,
below the predeclared minimum of 12.  The just-completed GCD study cannot turn
those failed AES configurations into valid observations.

**Why reusing the old plan fails.** Launching the same broad 50-point warm-up
again changes neither the target feasibility evidence nor the event that
stopped v3.  Relaxing the 12-observation gate, reusing v3 rows, or silently
changing the parameter domain after launch would make the proposed GP/EI
campaign non-comparable and violate the protected protocol.

**Option A — exact paper reproduction.** Acquire and admit the upstream
`ce8d36a` source/toolchain and use its complete assets/protocol.  This route
remains externally blocked by the documented GitHub acquisition failures; it
must not be approximated with the current binary.

**Option B — target-design preflight followed by a new adapted campaign.**
Run a separately named Sky130HD/AES feasibility preflight around the frozen
upstream anchor, with the same RTL bundle, 4.5 ns SDC bytes, locked current
toolchain, allowlisted knobs, paired seeds and protected evaluator.  Freeze a
subtractive domain only from its artifact-backed result.  Then rerun every
formal stage in a fresh campaign directory.  The resulting claim remains
platform/toolchain-specific, not an original-paper-number reproduction.

**Recommendation adopted.** Proceed with Option B as one bounded migration
slice.  Its code may create a new preflight runner and evidence schema, but it
must not alter the pinned ORFS-Agent source, current Runtime, protected
evaluator, historical campaign directories, benchmark RTL, SDC, PDK, or the
upstream GP/EI implementation.  If the preflight cannot yield a reproducible
subtractive domain, stop with its evidence rather than add a heuristic retry
loop.

### 2026-08-31: post-subdomain-adapter candidate parity recheck

The target-domain Adapter adds only a subtractive constraint/value-set mapping:
it retains an upstream raw candidate and records a separately named, typed
projection before Runtime executes it.  To ensure this boundary change did not
replace the default GP/EI algorithm, the same-input/same-seed parity check was
rerun after the change at
`var/orfs-agent-native-parity-20260831-target-domain-boundary/parity-report.json`.
It passed with six input rows, seed `20260830`, five suggestions and source
commit `730f1fa11f9c17c0aaac332412af2b2538f42e9b`; the registered candidate
artifact SHA-256 is
`e4c4a11e54fe2db9a76803df62052f521be54e8e6d1b3516303f33696d83c1db`.

This is a boundary-fidelity result only.  It proves that the default shared
domain still calls the unmodified upstream GP/EI routine; it is not evidence
that a target-domain campaign has improved AES QoR.

### 2026-08-31: invalid upstream-README anchor preflight, and successor policy

The first target-design preflight (`.../sky130hd-aes-v3`) must not be used as
the target-domain source.  Its three frozen anchor replicas completed ORFS,
but each protected evaluation failed setup timing at `-0.112255 ns` (with
`DRC=0`).  It was stopped under a dedicated process/session shutdown and is
marked by `HISTORICAL_EVIDENCE.md` as `INVALID_FOR_TARGET_DOMAIN / DO_NOT_TRAIN
/ DO_NOT_RESUME`.

The cause is an effective-flow mismatch, proved by a direct artifact
comparison: the prior v3 evaluator-feasible configuration has
`GP_PAD=0`, `DP_PAD=0`, `CTS_CDIA=80` plus fixed GPL/routing controls, whereas
the invalid preflight used `GP_PAD=3`, `DP_PAD=3`, `CTS_CDIA=100`.  The RTL
bundle, SDC bytes, 4.5 ns target, toolchain and OR seeds match.  This is not
an inference from logs or an excuse to reinterpret results.

The new `.../sky130hd-aes-v4-verified-anchor` preflight is a fresh 45-run
campaign rooted in the artifact-verified configuration, with all previous
results excluded.  The preflight report now records the full flow anchor; the
later target-calibrated L2 protocol must bind that anchor, its report digest,
the selected search parameters, their discrete observed value sets and all
fixed non-search parameters before it may submit a new baseline.

## 2026-08-30: source-bundle identity incident and bounded repair

**Problem.** The first platform-scale campaign at
`var/orfs-agent-paper-scale-20260830/sky130hd-aes-upstream-anchor4500`
terminated after three successful, evaluator-feasible baselines with the
message that there were not two usable observations.

**Evidence.** Each Runtime task correctly carried the primary file digest for
`aes_cipher_top.v`, while the `LearningContext` correctly carried the frozen
digest of the whole reference bundle.  The former exporter compared those two
different identities.  Re-exporting one run reproduced the precise exception:
`Runtime RTL fingerprint does not match learning context`.  This was a
controller/evidence contract fault, not an ORFS result or a QoR failure.

**Bounded repair.** `RuntimeEvidenceExporter` now prefers a declared,
lowercase-SHA-256 `design_bundle_sha256` label; the old
`reference_source_sha256` is accepted only as a checked compatibility alias.
Absent either label, the existing single-RTL digest rule is unchanged.  The
paper runner now emits the canonical bundle label.  The focused regression set
passed 21 tests, including bundle acceptance, mismatch rejection, malformed
legacy-label rejection, the old single-file behavior, the external L2 service,
admission, and adapter tests.

**Protocol consequence.** The stopped directory is retained unchanged as
historical failure evidence.  Its baseline runs will not be copied into a new
campaign.  The successor campaign receives a new output directory and reruns
baseline, warm-up, candidate screening, and confirmation from scratch.

## 2026-08-31: successor campaign baseline evidence

The successor campaign is
`var/orfs-agent-paper-scale-20260830/sky130hd-aes-upstream-anchor4500-bundleid-v2`.
It reran, rather than copied, all three frozen baseline replicas.  Each reached
Runtime `succeeded` and has a registered, SHA-verified
`common_evaluation.json` from the protected evaluator:

| Quantity | Replica observations | Interpretation |
| --- | --- | --- |
| Area | `108653 um^2`, `108653 um^2`, `108653 um^2` | no measured area spread at the emitted precision |
| Setup WNS | `+0.00302292 ns` for all three | timing-feasible at the frozen 4.5 ns target |
| Setup TNS | `0 ns` for all three | timing-feasible |
| DRC | `0` for all three | evaluator-feasible |
| Power | `0.371951 W` for all three | no measured spread at the emitted precision |
| Runtime | `2730.216 s`, `2743.402 s`, `2713.203 s` | execution-time variation is retained separately |

These are baseline facts, not an optimization claim.  After the third
baseline terminal receipt, Runtime entered the already frozen 50-recipe
warm-up.  Early warm-up failures are retained as observed infeasible evidence;
for example, recipes 001, 002, and 007 terminated at ORFS placement with
`FLW-0024` under their recorded high-utilization parameter vectors.  The
campaign has not changed its source bundle, SDC, PDK, evaluator, parameter
domain, or warm-up recipes in response.

## 2026-08-30: independent paper-revision source admission

The earlier `orfs-ce8d36a-paper` Git worktree has now converged to a clean
superproject and the recorded OpenROAD/Yosys submodule commits.  It remains
unsuitable as an isolated toolchain because its `.git` points into the active
parent repository's worktree administration.

An ordinary-clone attempt at `var/toolchains/orfs-ce8d36a-isolated` is retained
as `INVALID` network evidence: Git failed before a usable `HEAD` with remote
`curl 56 OpenSSL SSL_read: Connection reset by peer`, `early EOF`, and invalid
index-pack output.  Its one permitted bounded retry,
`var/toolchains/orfs-ce8d36a-isolated-fetch1`, used a fresh ordinary repository
and requested only the exact `ce8d36a` commit.  It also failed before a usable
checkout: `Failed to connect to github.com port 443` after 131155 ms.

No build, installer, benchmark, or evaluator was run from either invalid
directory.  This is the second same-root external-network failure, so this
admission route is now stopped rather than retried with mirrors, changed
versions, or an unpinned revision.  Recovery requires one of: restored GitHub
connectivity, an administrator-provided immutable source bundle whose commit
and submodule objects verify exactly, or an already-admitted local mirror.  A
current `51ad1231` binary must not be relabeled as the historical paper binary.

## 2026-08-30: successor-v2 controller-loss incident

**Problem.** The successor-v2 campaign controller disappeared while the frozen
50-recipe warm-up was executing.  The two currently live ORFS children were
orphaned under PID 1; the controller itself was absent.  The Runtime database
therefore still displayed 12 `running` runs even though no controller could
collect their results or schedule the remaining queue.

**Evidence.** At `2026-08-30T17:22:09Z`, ten of those twelve attempt
workspaces contained an `adapter_result.json` whose terminal payload was
`status=failed`, `category=adapter_error`, and
`BrokenPipeError: [Errno 32] Broken pipe`.  The other two had active OpenROAD
detail-route processes but no result file.  The most recent durable pipeline
checkpoint and heartbeat were at `2026-08-30T16:08Z`, whereas the result files
continued to appear afterwards.  This is an orchestration-process loss: it is
not evidence about an ORFS-Agent suggestion, an ORFS recipe, or QoR.

**Protocol decision.** This campaign directory is retained unchanged as
`HISTORICAL_EVIDENCE / INVALID_FOR_QOR_STATISTICS`.  No result from it will be
promoted to the GP/EI training set, counted as a warm-up feasibility result, or
compared with the baseline.  It will not be resumed through lease expiry,
because doing so would turn an external controller interruption into synthetic
`worker_lost` outcomes and mix invalid execution with the frozen experiment.

**Recovery boundary.** The next successor must use the same receipt, source
fingerprints, SDC bytes, toolchain, warm-up seed/recipes, candidate budget and
statistics, but be launched under an independently detached supervisor with
stdin/stdout/stderr redirected to durable files and a PID/health record.  It
must be a new output directory and rerun all three baseline replicas.  This is
an execution-lifecycle correction, not a change to the research algorithm or
experimental protocol.

## 2026-08-30: regression-suite evidence during successor-v3 execution

The complete repository Python suite was executed independently of the active
campaign, with its durable terminal log at
`var/verification/orfs-agent-v3/full-pytest.log` and exit receipt at
`var/verification/orfs-agent-v3/full-pytest.exitcode`.  It completed with
`535 passed, 1 deselected, 63 warnings in 337.78s`; the exit code is `0`.
Warnings are from Ray, Optuna and BoTorch dependency APIs and are retained in
the log.  This validates the repository's static and mocked execution
contracts.  It is not evidence of live ORFS QoR, which remains exclusively
defined by the active campaign's protected-evaluator artifacts.

## 2026-08-30: detached successor-v3 baseline evidence

The independently supervised successor is
`var/orfs-agent-paper-scale-20260830/sky130hd-aes-upstream-anchor4500-detached-v3`.
Its controller uses an independent session and durable `controller.log`/
`controller.pid`; unlike successor-v2, it remained alive through the baseline
to warm-up transition.  All three new baseline replicas reached Runtime
`succeeded` and each has a protected `common_evaluation.json` with gate status
`passed`:

| OR seed | Area (`um^2`) | Setup WNS (ns) | Hold WNS (ns) | Power (W) | DRC | Runtime (s) |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 101 | 108653 | +0.00302292 | +0.50139 | 0.371951 | 0 | 2739.242 |
| 211 | 108653 | +0.00302292 | +0.50139 | 0.371951 | 0 | 2706.725 |
| 307 | 108653 | +0.00302292 | +0.50139 | 0.371951 | 0 | 2732.379 |

All three carry the same source-bundle SHA-256
`ccdb34159d88edc4fadd7bd9eda1b379b46f78150cf6faeef354943bee876a3b` and
the same frozen-SDC SHA-256
`72fbb10d2783eda6a086819f6b5a47ef71c7ccd97a007740f12a9fd750c1df3c`.
The three effective-config hashes differ because the frozen replica seed is a
provenance input.  These numbers are baseline evidence only.  They neither
demonstrate an ORFS-Agent improvement nor establish paper-number equality.

After the third terminal baseline the same controller submitted the frozen
warm-up recipes; it did not alter the source bundle, SDC, toolchain, objective,
domain, warm-up seed or recipe list.  At this point the closed-loop gate is
actively executing its 50-recipe warm-up phase.

## 2026-08-30: detached successor-v3 warm-up terminal decision

**Problem.** The detached Sky130HD/AES successor completed its frozen
50-recipe warm-up but could not meet the external-optimizer protocol's
minimum of 12 distinct evaluator-feasible observations.  Consequently it did
not submit an ORFS-Agent GP/EI task, candidate task, or confirmation task.

**Evidence.** The terminal checkpoint is
`var/orfs-agent-paper-scale-20260830/sky130hd-aes-upstream-anchor4500-detached-v3/checkpoint-export.json`.
It records `status=failed`, `round=0`, `candidate_count=0` and the exact
failure message: `warm-up yielded 2 distinct feasible observations; protocol
requires 12`.  Across the 53 Runtime runs, the three baseline replicas passed
the protected evaluator; of the 50 warm-ups, 41 were Runtime `orfs_failure`,
and nine reached the evaluator, but only warm-up 003 was evaluator-feasible.
The two distinct observations are therefore the shared baseline configuration
and warm-up 003, not twelve data points.  Examples of retained physical
failures include placement `FLW-0024`, detailed-placement `DPL-0036`, and
global-route `GRT-0116`; separately, several ORFS-complete runs were rejected
by the evaluator for negative setup WNS.  None is reclassified as training
data.

**Why the current plan fails.** This platform campaign uses the safe,
transportable eight-knob intersection of the upstream configuration and the
current `51ad1231` ORFS toolchain.  The upstream README's published example
is ASAP7/AES and its `opt_config.json` declares an eleven-knob configuration
including `PIN_LAYER_ADJUST`, `ABOVE_LAYER_ADJUST`, and `FLATTEN`, plus custom
`fastasap.tcl`/`fastsky.tcl` integration.  The current protected Adapter does
not pretend that these non-equivalent mechanisms are live on `51ad1231`.
The separately required exact ORFS revision `ce8d36a` remains unavailable as
an independently verified source/toolchain after the recorded bounded network
attempts.  Thus neither changing Sky130 recipes after observation nor
claiming the current eight-knob run is an exact paper reproduction is valid.

**Option A — exact-paper admission.** Obtain an immutable ORFS `ce8d36a`
source bundle with its required submodule objects from an administrator or an
admitted local mirror, verify the commit/submodules, build it in a dedicated
plugin environment, and then run the upstream ASAP7/AES configuration with
the officially declared mechanism set.  This is the only route that can test
paper-number equivalence; it is currently blocked by unavailable source
provenance, not by an Adapter patch.

**Option B — current-toolchain platform acceptance.** Define a new,
separately named, feasibility-calibrated `51ad1231` domain using a controlled
calibration study and retain the eight-knob boundary.  Freeze that new domain,
rerun all baselines and the entire 50 + 250 + confirmation protocol in a new
directory, and label the result as platform/toolchain-specific rather than
paper-identical.  It must not reuse v3's warm-up or baseline results.

**Recommendation.** Treat v3 as valid negative evidence and stop this
protocol rather than patching its finished campaign.  Continue only through
Option A when exact-source admission becomes possible, or through a clearly
new Option B calibration-and-campaign slice.  No performance success claim is
made for v3.
