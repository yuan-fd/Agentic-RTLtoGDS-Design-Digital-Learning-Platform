# P2 verified-RTL provenance gate

Status: proposed for independent merge-gate review  
Date: 2026-09-02

## Intent

Close the P0-recorded `direct import -> L2` bypass.  The product L2 entry now
accepts `spec_id` and optional `candidate_id`, rather than an upload-backed
`design_id`.

## Boundary change

```text
Before: design_id -> DesignService RTL path -> ORFS-Agent L2 TaskSpec
After:  spec_id/candidate_id -> RTLScout-v2 lineage + Runtime verification
        artifact/hash -> ORFS-Agent L2 TaskSpec
```

The resolver requires, before any TaskSpec submission:

1. an owned immutable SpecIR lineage and pinned RTLScout-v2 candidate;
2. a managed candidate artifact with a matching SHA-256;
3. a recorded compile/lint pass with a Runtime run id;
4. a Runtime-backed simulation or formal pass whose terminal task identity,
   candidate/spec labels, report artifact identity and report SHA-256 all
   agree with the append-only check row; and
5. a successful Runtime RTL artifact that is workspace-contained and hash-equal
   to the managed candidate.

The browser may choose only the registered `spec_id`, an optional pinned
candidate, and the approved objective vocabulary.  Clock, timing period,
platform/PDK and other physical constraints are derived from the immutable
SpecIR constraints; client values cannot override them.

The L2 base task and checkpoint retain spec, candidate, verification run and
RTL hash provenance.  Product-role authorization also checks the P1
ORFS-Agent allowlist before this path starts.

## Changed files

- `apps/api/app.py`
- `tests/test_auth_isolation.py`
- `tests/test_l2_verified_rtl_gate.py`
- `docs/governance/P2_VERIFIED_RTL_PROVENANCE_GATE.md`

## Explicitly out of scope

Direct RTL import remains a preserved legacy research/fixture capability; P2
does not delete it or modify its stored artifacts.  This slice does not change
Runtime lifecycle, ORFS-Agent algorithm/source lock, evaluator, benchmark,
PDK, SDC, TaiWei, Web UI or local research algorithms.

## Acceptance

- A direct `design_id` payload is rejected by the product L2 HTTP allowlist.
- A non-RTLScout candidate, missing or forged functional evidence, missing
  Runtime provenance, wrong Runtime plugin/terminal state, path escape or hash
  mismatch fails before TaskSpec construction.
- A valid RTLScout/Runtime-backed candidate resolves to a provenance-bearing
  L2 input.
- Existing ownership isolation and L2/RTL focused tests pass.

## Rollback

Revert this API-composition change and its tests.  No database schema,
historical design record, RTL lineage, Runtime artifact or experiment checkpoint
is migrated or deleted by P2.
