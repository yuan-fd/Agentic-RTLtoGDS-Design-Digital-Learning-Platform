# Slice 043: CLOSER-Bench intake stop and protocol alignment

## Boundary

This slice performs a source-audit-only intake of the public CLOSER-Bench
paper and audits existing platform evidence against the paper's published
protocol requirements. It does not register a CLOSER plugin, recreate its
tasks or hidden oracle, execute guessed artifacts, or claim an official
benchmark result.

```text
pinned public paper + unavailable release fields
  -> fail-closed external-project lock
  -> existing Spec-to-GDS and typed-recovery evidence
  -> non-claiming protocol-alignment audit
```

## Stop record

### Problem

The requested official CLOSER-Bench evaluation cannot be admitted because no
canonical source/data release, exact commit, source/data license, native
entrypoint, task checksum manifest, container digest, frozen stage pairs, or
hidden oracle package is publicly verifiable.

### Evidence

- Paper: `https://arxiv.org/abs/2607.16632v1`.
- PDF SHA-256:
  `84280d8b1a79924c5742fa1536fd1c48622cf93b7dd407d348b02c5b4750ac28`.
- Fail-closed lock: `integrations/closer_bench/source.lock.json`.
- Full search and publication audit:
  `docs/governance/CLOSER_BENCH_INTAKE.md`.
- The paper itself describes the task/oracle freeze, repeated trials and final
  signoff matrix as incomplete or future work.

### Why the current plan fails

The repository intake gate requires a canonical upstream URL, exact commit,
license, native smoke and bounded platform smoke before executable
registration. Reconstructing stage pairs or hidden labels from prose would be
a local benchmark reimplementation and would violate `Reuse > Adapt >
Reimplement`. Calling an internal fault injection CLOSER-Bench would also be a
false benchmark claim.

### Option A

Wait for an official source/data release, then repeat intake, run the smallest
native smoke, and integrate the released task and scorer boundary through
Runtime.

### Option B

Use only existing immutable evidence to run a clearly labelled
`protocol_alignment_only` audit. Independently add a platform-owned bounded
backend-failure-to-RTL-recovery acceptance without using the CLOSER name.

### Recommendation

Keep official CLOSER execution blocked under Option A. Complete Option B now
to close the platform's executed cross-stage-recovery evidence gap without
weakening the external-project gate or making an unsupported claim.

## Before / after dependency edge

Before:

```text
public CLOSER paper -> unresolved request for benchmark execution
```

After:

```text
public CLOSER paper -> Red/source-audit-only lock
existing Runtime evidence -> analysis-only alignment report
```

No executable CLOSER capability or product-surface dependency was introduced.

## Changed files

- `docs/governance/CLOSER_BENCH_INTAKE.md`
- `integrations/closer_bench/source.lock.json`
- `packages/analysis/src/openroad_platform_analysis/closer_alignment.py`
- `packages/analysis/src/openroad_platform_analysis/__init__.py`
- `tests/test_closer_alignment.py`
- `scripts/run_closer_protocol_alignment_audit.py`
- this record

## Tests and bounded evidence

Focused CLOSER alignment tests: `2 passed`. The combined PostEDA/CLOSER group
also passed: `7 passed`.

Canonical alignment evidence:

```text
var/evidence/closer-protocol-alignment-20260905-r1/summary.json
SHA-256 88f9bd0859206c16e48628be0ae52ee7725c7ee513acca596446ec7995b7fc89
```

The audit records four criteria as met, two partial and four missing. In
particular, it refuses to count the typed recovery proposal as an executed RTL
fix/rollback and sets both `protocol_alignment_only=true` and
`official_closer_bench_result=false`.

## Protected and unrelated behavior

No external source was installed or executed. No RTL, PDK, SDC, ORFS
toolchain, protected evaluator, A2-ORFO policy, ORFS-Agent search space, API or
web route changed. The immutable accepted Spec-to-GDS and recovery summaries
were read by hash and were not modified.

## Rollback

Remove the analysis module, export, test and audit script listed above. Keep
the intake record, fail-closed source lock and canonical audit evidence as
historical governance evidence; they document why official execution was not
permitted.
