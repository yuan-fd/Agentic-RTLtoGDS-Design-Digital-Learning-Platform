# Slice 044: executed backend-to-RTL checkpoint recovery

## Boundary

This slice adds and accepts one platform-owned, bounded cross-stage recovery
trajectory. It does not implement an RTL repair algorithm, modify RTLScout,
alter ORFS/PDK/SDC/evaluator inputs, add a product optimizer, or claim an
official CLOSER-Bench result.

```text
pinned native RTLScout RTL + frozen functional oracle
  -> platform-owned SYNTHESIS-only fault candidate
  -> real frontend verification pass
  -> real ORFS failure
  -> evidence-only DiagnosisReport + typed recovery decision
  -> content-addressed clean checkpoint selection
  -> real re-verification + ORFS finish/GDS + protected QoR
```

## Architectural change

Before, `DiagnosisReport` and `RecoveryDecision` could propose recovery from
measured QoR, but a Runtime failure before QoR parsing could not enter the
Debugger state, and no typed contract bound a restore decision to an exact RTL
candidate.

After:

- `diagnose_terminal_failure` represents all four QoR domains as unavailable,
  cites the Runtime record and registered artifacts, and emits a coarse
  backend blocker without inventing QoR or a physical root cause;
- `DebuggerState` permits an empty numeric-fact basis only because its
  evidence tuple remains mandatory;
- `RTLCheckpointRestorePlan` binds the recovery decision, checkpoint, failed
  candidate, direct ancestor candidate and exact RTL SHA-256;
- scheduler admission requires existing compile/lint and independent
  functional passes for the target checkpoint; and
- the append-only L1 store persists the exact restore plan before any new
  Runtime submission.

The restore plan carries no source text, patch, parameter, command or shell.
Verification and ORFS implementation remain normal Runtime-owned tasks.

## Frozen fault protocol

The accepted run freezes a two-backend-run budget. The fault fixture preserves
the exhaustive 65,536-vector functional behavior outside synthesis and
instantiates an unresolved blackbox only under `SYNTHESIS`. It therefore tests
a real frontend/backend boundary without changing the testbench, clean RTL,
Nangate45 platform, ORFS parameters, seed or evaluator.

The clean target is the exact RTL produced by the accepted native RTLScout run:

```text
var/evidence/rtlscout-native-spec-to-gds-20260905-r8/summary.json
SHA-256 602a13dc56145ab3b3e3f7c290b92c269fe4f137b54e6e14b3185f8b075f4cb0
RTL SHA-256 bc06e926eb3b9df99c1455ebb78d04a5f618bda623f261c4437c5a5ed50de69a
```

Fault fixture SHA-256:
`e81c473e2a8b4c2aa8d2f5ce5584b228054be2a0cc68a2f411a24607fc53b037`.

## Changed files

- `packages/contracts/src/openroad_platform_contracts/recovery.py`
- `packages/contracts/src/openroad_platform_contracts/l1_control_state.py`
- `packages/contracts/src/openroad_platform_contracts/__init__.py`
- `packages/analysis/src/openroad_platform_analysis/stage_diagnostics.py`
- `packages/analysis/src/openroad_platform_analysis/__init__.py`
- `packages/scheduler/src/openroad_platform_scheduler/rtl_checkpoint_restore.py`
- `packages/scheduler/src/openroad_platform_scheduler/l1_control_state_machine.py`
- `packages/scheduler/src/openroad_platform_scheduler/__init__.py`
- `tests/test_cross_stage_recovery.py`
- `tests/fixtures/cross_stage_synthesis_blackbox.sv`
- `scripts/run_cross_stage_rtl_recovery_acceptance.py`
- this record

## Tests and real bounded acceptance

Focused control/diagnostic tests passed: `16 passed`. They cover evidence-only
terminal failure diagnosis, four unavailable domains, verified direct-ancestor
selection, content mismatch rejection and durable plan storage.

Repository regression after Slices 043-045: `841 passed, 1 deselected`; the
63 reported messages are dependency deprecation/numerical warnings, not test
failures. `git diff --check` passed.

Canonical accepted evidence:

```text
var/evidence/platform-cross-stage-rtl-recovery-20260905-r2/summary.json
SHA-256 1606eb84083be453a9efe2e8b1cfa7986899089332d08059247f0250472bbf6d
```

Observed real statuses:

```text
clean checkpoint: verify succeeded, simulation succeeded
fault candidate:   verify succeeded, simulation succeeded, ORFS synth failed
restored target:   verify succeeded, simulation succeeded, ORFS finish succeeded
```

The restored run registered GDS SHA-256
`de9e3da0f965f3aeaf9553830d9542f6428e72970b7d2ed23f24b7376dae1d70`
and protected evaluator output. The failed and successful backend checks are
both retained in the append-only candidate lineage. Total acceptance time was
181.88 seconds.

The initial r1 run is retained as failed debug evidence. It exposed that
`DebuggerState` required numeric facts even when a real Runtime failure
occurred before QoR parsing. No result was overwritten, and r1 must not be
cited as accepted evidence.

## Claim boundary

This proves one deterministic integration path for backend failure detection,
typed checkpoint selection, re-verification and successful reimplementation.
It is not CLOSER-Bench, not an autonomous source-repair result, not a diagnosis
accuracy estimate and not evidence of general recovery across designs or
failure classes.

## Protected and unrelated behavior

The native RTLScout source, accepted clean RTL, exhaustive testbench, ORFS
source, Nangate45 platform, flow parameters, seed and protected evaluator were
unchanged before and after execution. A2-ORFO, ORFS-Agent's 12-D domain, API
and web routes were not modified. The 151-run campaign was not started.

## Rollback

Remove the restore-plan contract, scheduler admission module, terminal-failure
analysis, store table/methods, tests, fixture and acceptance script listed
above. Restore the previous `DebuggerState` numeric-fact requirement. Preserve
both r1 and r2 evidence plus this governance record as historical evidence of
the migration and its discovered contract gap.
