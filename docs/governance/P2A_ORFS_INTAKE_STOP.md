# P2a ORFS executable-admission stop record

Status: superseded by local-managed-toolchain authorization
Date: 2026-09-02

## Historical problem

The historical `orfs@1.2.0` Runtime plugin cannot be admitted as an executable
external integration under the repository intake gate.

## Evidence

- inspected local checkout: `https://github.com/The-OpenROAD-Project/OpenROAD-flow-scripts.git`
  at `51ad1231a231ee85234c06db807688d029b85c35`;
- no `LICENSE`, `LICENSE.md`, `COPYING`, or `NOTICE` exists in that checkout;
- read-only requests for each of those paths at the same GitHub commit returned
  HTTP 404 on 2026-09-02;
- the checkout is also dirty, so it cannot be silently treated as a pristine
  pinned executable source.

## Why the current plan fails

Historical implementation smoke proves only that a local tool process ran.  It
does not establish license/redistribution permission.  Calling it a new
admission or continuing to execute it would violate the external-project intake
gate.

## Options

- Record a reviewed license file and redistribution conclusion for this exact
  commit, then create a new immutable checkout and complete native plus bounded
  platform smoke evidence.
- Select a different, pinned upstream ORFS release/commit with a reviewed
  license, run the full intake, and adapt through the same bounded adapter
  boundary.

## Superseding local-toolchain decision

On 2026-09-02 the project owner clarified that this is a server-managed local
ORFS/OpenROAD installation, authorized for use by this platform.  The platform
does not vendor or redistribute it.  The intake lock therefore permits only
bounded server-local execution; it does not make a redistribution claim or
waive the requirement for provenance, Attempt-local writes, raw logs, or
native/platform smoke evidence.

## Historical enforcement

`integrations/orfs/orfs.intake.lock.json` marks the source `red` and
`source-audit-only`; `orfs_plugin_manifest()` rejects executable registration.
No historical code, raw logs, artifacts, or prior smoke results were deleted.

## Rollback

Reverting the future P2a admission-boundary commit restores the previous
historical behavior, but must not be used to bypass the intake gate.
