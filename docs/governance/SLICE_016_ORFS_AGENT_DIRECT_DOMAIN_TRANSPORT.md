# Slice 016 — ORFS-Agent direct-domain transport

## Problem

The v7 formal campaign reached the unchanged upstream GP/EI proposal step,
but the adapter mapped its proposals to a sparse endpoint-only execution
envelope.  Distinct upstream proposals then became identical effective ORFS
parameter vectors.  The Scheduler correctly stopped the campaign, but its
old sequential submission left a queued prefix before it found the duplicate.

## Evidence

- Campaign: `var/orfs-agent-paper-campaign-20260901-v7-clean-source-lexical-codex-7200`.
- `orfs-agent-0000` and `orfs-agent-0004` have different upstream values but
  both mapped to `UTIL=30`, `GP_PAD=3`, `LB_ADDON=0.425`,
  `TNS_End_Percent=75`.
- The pinned upstream workbench defines `UTIL`, `TNS_End_Percent`, and
  `GP_PAD` as `Integer` intervals and `LB_ADDON` as a `Real` interval.  It
  does not provide a representation for arbitrary sparse integer categories.

## Change

1. The campaign constructs complete integer intervals between admitted
   endpoints before invoking the upstream workbench.
2. The adapter materializes those exact intervals in its temporary upstream
   `constraints.json`; sparse integer domains fail before proposal execution.
3. `LB_ADDON` remains a bounded continuous Real value.  The platform no
   longer imposes an artificial quantization grid or snaps it to a warm-up
   lattice value.
4. The adapter rejects an out-of-domain or cross-parameter-invalid proposal;
   it never substitutes a nearest value.
5. The Scheduler validates a whole candidate batch before submitting any
   Runtime candidate task.

The finite warm-up lattice is retained solely to make initial DOE sampling
reproducible.  It is not a claim that only those floating-point coordinates
are executable.  A newly generated v8 campaign will freeze this revised
execution envelope; v7 remains immutable failed evidence.

## Protected components

No v7 benchmark, RTL, PDK, SDC, evaluator, recorded artifact, seed, or
upstream source was changed.  The upstream ORFS-Agent GP/EI implementation at
commit `730f1fa11f9c17c0aaac332412af2b2538f42e9b` is unmodified.

## Verification

Focused automated checks cover direct-domain task construction, no-grid float
transport, sparse-domain rejection, and all-or-nothing Scheduler submission.
The real native-policy smoke artifact is recorded separately under
`var/orfs-agent-representable-domain-native-smoke-20260901-*`.

## Invalid launch record

`var/orfs-agent-formal-supervisor-20260901-v8-direct-domain-7200` and its
matching formal directory were created by an operator invocation that
incorrectly included the supervisor's `--worker` flag.  The controller was
therefore outside the required systemd cgroup and was terminated before it
created a Runtime run; only a frozen SDC file exists.  These directories are
retained as invalid-launch evidence and are not reused.  The valid campaign
uses a fresh `v8b` identity and the launcher (not worker) entrypoint.

## Rollback

Revert only this slice's changes to the ORFS-Agent adapter, ORFS parameter
schema, campaign-envelope construction, Scheduler batch validation, and the
focused tests.  Do not alter any `var/orfs-agent-*v7*` evidence directory.
