# Slice 010: one-factor target-domain capacity stop

Status: completed preflight; formal comparison stopped before its first
baseline.  This is not an optimizer, Runtime, or QoR failure.

## Problem

The supervised campaign
`orfs-agent-formal-comparison-20260831-v3-7200.service` completed its
45-run, three-replica target-feasibility preflight and then failed closed
before formal execution.  The preflight's subtractive domain has only 32
legal unique coordinates, while the frozen official-scale protocol requires
301 unique screening coordinates: one baseline coordinate, 50 warm-up
coordinates, and 250 GP/EI or control coordinates.

## Evidence

- Preflight root:
  `var/orfs-agent-target-feasibility-20260831-systemd-v3-7200/`.
- All 45 Runtime runs and attempts are `succeeded`; all 45 protected
  `common_evaluation.json` artifacts exist.
- `preflight-receipt.json` is `completed` and binds report SHA-256
  `71522b0680ecbfdbb42eb40ab5eccafcb43b45a36f68278622a5a3f985bc89eb`.
- The report's five varying dimensions each have two repeated-feasible
  values, hence `2 * 2 * 2 * 2 * 2 = 32`.  The remaining shared parameters
  are fixed because their one-factor alternatives were not replicated-feasible.
- The controller's terminal error is:

  ```text
  ValueError: admitted target domain has 32 legal coordinates;
  equal-budget protocol requires at least 301 unique coordinates
  ```

- `var/orfs-agent-paper-campaign-20260831-systemd-v3-7200/` contains only
  early formal-script metadata/frozen input material.  It contains no Runtime
  database, baseline, warm-up, GP/EI, or QoR result and is ineligible for any
  comparison claim.

## Why the current plan fails

The preflight protocol correctly says that repeated one-factor feasibility is
not proof that arbitrary combinations are feasible.  Treating its observed
value lists as a 301-point combination catalogue would contradict that claim.
Reducing the 250-candidate budget would no longer be the official-scale
protocol.  Relaxing duplicate detection would make repeated coordinates look
like new DSE information.  Neither changes the measured fact that the v1
domain has capacity 32.

## Options

### Option A: declare the 32-point domain the final experiment domain

Run at most 31 non-baseline points.  This is a valid small target-domain
study, but it is not aligned with the 50 + 250 official-scale protocol and
cannot support the requested equal-budget acceptance.

### Option B: new versioned execution-envelope protocol

Keep the completed preflight as immutable evidence of the anchor and its
one-factor observations.  Start a new formal campaign with a separately
versioned **execution envelope**: values inside documented, observed
one-factor brackets are legal candidates for protected evaluation, but are
not claimed to be preflight-proven feasible in combination.  Runtime retains
every infeasible result.  Both ORFS-Agent and the fixed-seed Random arm use
the exact same envelope, input hashes, budget, evaluator and resource policy.

## Recommendation adopted for the next migration slice

Implement Option B as a narrow analysis/protocol change, with a fresh formal
output root.  Do not alter the pinned ORFS-Agent source, the completed
preflight report, benchmark RTL, SDC, PDK, protected evaluator, or historical
directories.  A new protocol must explicitly distinguish `verified_values`
from `execution_values`; it must never describe the latter as guaranteed
feasible.  If its independent formal campaign yields too few feasible warm-up
points, preserve that failure and stop rather than widening the envelope in
place.
