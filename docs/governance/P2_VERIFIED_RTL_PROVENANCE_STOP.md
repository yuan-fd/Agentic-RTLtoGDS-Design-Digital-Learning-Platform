# P2 verified-RTL provenance gate: stop record

Status: decision required before implementation  
Date: 2026-09-01

## Problem

The approved L2 product path requires independently verified RTL.  The current
`POST /api/v2/external-optimizer-loops` request, however, accepts only a
`design_id`.  `ApiState.start_external_optimizer_loop` checks design ownership
and reads `DesignService.rtl_path`; it does not verify RTLScout provenance or a
Runtime-backed verification record.  An ordinary direct import can therefore
enter L2.

## Evidence

- `apps/api/app.py:start_external_optimizer_loop` obtains an owned design and
  immediately builds the ORFS base task from its RTL path.
- `apps/api/app.py:POST /api/designs/import` registers arbitrary authenticated
  RTL in `DesignService`.
- Verified RTL currently lives in the RTL frontend lineage and Runtime artifact
  records used by `promote_verified_rtl_to_orfs`; it is not represented as a
  provenance-linked DesignService record that the L2 endpoint can require.

## Why the current plan fails

Adding an `origin == "rtlscout_verified"` check to the existing `design_id`
route would be a false solution: current verified RTL promotion does not create
such a design record, so it would block every L2 product request while leaving
no supported handoff.  A caller-provided boolean/label would be equally unsafe.

## Option A — promote verified RTL into a registered design record

After the independent verification gate, create an immutable DesignService
record containing the RTL artifact hash, source Runtime run, SpecIR id,
candidate id and verification id.  L2 continues to accept `design_id` and
rejects any record without this provenance.

- Benefit: preserves the public L2 request shape and design-centric read model.
- Cost: DesignService becomes responsible for a new immutable provenance
  representation; migration needs careful owner/hash checks.

## Option B — make L2 accept a verified RTL reference

Replace the product L2 input with a `spec_id`/`candidate_id` or a dedicated
verified-artifact reference.  The L2 application service resolves the lineage,
verification evidence and content-addressed RTL artifact before TaskSpec
construction; `design_id` is derived internally.

- Benefit: follows the actual source of truth and makes bypass impossible by
  construction.
- Cost: public API/read model changes and a dedicated verified-artifact
  resolver are required.

## Recommendation

Choose **Option B**.  The approved architecture says an immutable verified RTL
artifact, not a mutable design upload, is the input to L2.  This keeps the
provenance authority with RTL frontend/Runtime, avoids duplicating raw RTL in a
second state owner, and gives L1 a typed artifact reference for its future
`DesignGoal`.

## Constraints for either option

- Do not alter the evaluator, benchmark, PDK, SDC, ORFS-Agent algorithm or
  source lock.
- Preserve direct import as legacy research/fixture evidence; do not delete it.
- Reject missing, changed, cross-owner, unverified, or non-RTLScout product
  inputs before TaskSpec/Runtime submission.
- Record the selected provenance references in the L2 checkpoint and include
  focused API, ownership and hash-integrity tests plus a bounded smoke.

## Rollback

The eventual P2 change must be separately reversible without rewriting
historical design records, RTL lineage, Runtime artifacts or experiment
checkpoints.
