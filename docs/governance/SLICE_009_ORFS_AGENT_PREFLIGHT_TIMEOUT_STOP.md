# Slice 009: ORFS-Agent target-feasibility preflight timeout stop

Status: stopped by the governed failure rule; not a QoR or optimizer result.

## Problem

The fresh user-systemd preflight
`var/orfs-agent-target-feasibility-20260831-systemd-v2/` encountered the same
terminal failure in two independently seeded measurements of the same
one-factor perturbation:

```text
Stage exceeded 3600s timeout
```

The 3,600-second detailed-route limit is a frozen part of this preflight's
resource policy.  It is not a value to increase after seeing an inconvenient
configuration.

## Evidence preserved

- Supervisor: `orfs-agent-formal-comparison-20260831-v2.service`.
- Failed task IDs:
  - `orfs-agent-feasibility-anchor-002-s101-dbed08e17c5c`
  - `orfs-agent-feasibility-anchor-002-s211-dbed08e17c5c`
- Runtime attempt failure category/message: `orfs_failure` / `Stage exceeded
  3600s timeout` (exit code 2 for both).
- Before the stop, six measurements completed and produced protected-evaluator
  artifacts; the three anchor replicas were feasible.  This partial fact does
  **not** constitute a completed feasibility report or a PPA claim.
- The controller was stopped with `systemctl --user stop`; its `KillMode` was
  `control-group`.  No OpenROAD child process remained afterwards.  No SQLite
  rows, RTL, SDC, PDK, evaluator, time limit, or raw artifact was edited.

## Terminal lifecycle recovery

After every child process was confirmed absent and every worker lease had
expired, the public `RuntimeStore.expire_leases()` API recorded the eight
controller-killed attempts as `lost` with `worker_lost / Worker lease
expired`.  No direct SQL was used.  The terminal database counts are:

```text
runs:     failed 10, queued 29, succeeded 6
attempts: failed 2, lost 8, succeeded 6
```

The queued rows were never started.  This output root is therefore
`HISTORICAL_EVIDENCE / STOPPED_PROTOCOL`, not a completed target-domain report.

## Why the current plan stops here

Continuing the remaining queued measurements would accumulate the same
resource-policy failure.  Raising the limit or changing the parameter domain
mid-campaign would produce a different preflight protocol and make this
particular campaign incomparable with its already completed cases.  Either
action would violate the protected-evaluator and frozen-protocol boundary.

## Options

### Option A — retain the 3,600-second resource policy

Classify this output root as stopped historical evidence.  Use the partial
artifacts only to diagnose the timeout and never as a target-domain report or
an ORFS-Agent-vs-control result.

### Option B — start a new, explicitly versioned preflight protocol

Before any execution, choose and record a revised resource policy and rerun a
fresh preflight output root from zero.  The new protocol must use that same
policy for every preflight case and for both later formal comparison arms.  It
must not reuse this root's partial measurements as baseline or warm-up data.

## Recommendation

Do not patch the adapter or modify the running campaign.  Preserve this root
as stopped evidence and require an explicit, new protocol decision before a
fresh campaign is launched.  The formal GP/EI and seeded-random arms remain
unstarted and therefore have no result to report.
