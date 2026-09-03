# P2 release-gate stop record

Status: blocked pending an atomic migration slice and new bounded-smoke evidence  
Date: 2026-09-02

## Problem

The verified-RTL provenance gate is implemented and its fail-closed unit and
HTTP-boundary tests pass, but it cannot be merged as the declared P2 migration
slice because the current worktree does not provide a reviewable P2-only change
set.

## Evidence

- `apps/api/app.py` has a 1,862-line unstaged diff in a worktree containing
  unrelated historical and later-platform edits.  The P2 document declares a
  four-file slice, while its acceptance test and gate document are currently
  untracked.  There is no reviewable P2-only change set.
- `docs/evidence/P2_ORFS_ACCEPTANCE.json` proves the older direct ORFS plugin
  flow, but records `milestones.functionally_verified: false`; it cannot prove
  the new admission path.  The gap is now covered separately by
  `docs/evidence/P2_VERIFIED_RTL_L2_SMOKE.md`; that smoke is an admission
  check, not an optimizer/QoR acceptance.
- The focused safety suite passed on this checkout:
  `tests/test_l2_verified_rtl_gate.py`, `tests/test_auth_isolation.py`, and
  `tests/test_external_l2_service.py` (24 tests).  This is regression evidence,
  not a replacement for a tool-backed acceptance artifact.

## Why the current plan fails

Calling the old ORFS evidence a successful post-gate smoke would be a false
claim: it has neither a functional verification pass nor the new provenance
resolver/checkpoint.  The new smoke resolves that evidence gap, but committing
or staging the whole dirty API diff would still bundle unrelated work and
violate the one-boundary migration rule.

## Option A

First isolate P2 into a dedicated branch/commit (or a reviewed P2-only patch)
containing only its API composition, focused tests and this governance record.
The bounded product smoke has now been run and recorded.  Preserve it while
isolating the P2-only change set, then have a fresh merge gate inspect both.

## Option B

Treat the gate as test-verified but not release-accepted, leave it unmerged,
and postpone P2 until the product RTL pipeline can produce the required real
candidate and oracle evidence on the pinned local toolchain.

## Recommendation

No merge and no progression to P3 are authorized until Option A is supplied.
It is the only option that gives a reversible atomic slice and does not turn
fixture evidence into an EDA acceptance claim.

## Rollback

No data migration or deletion occurred.  Revert the isolated future P2 commit
only; retain all legacy artifacts and historical evidence.
