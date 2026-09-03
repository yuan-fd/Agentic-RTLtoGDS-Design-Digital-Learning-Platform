# Slice 008: Controller-loss historical evidence classification

Status: terminal historical recovery; not an experiment result.

## What happened

The controller for
`var/orfs-agent-target-feasibility-20260831-sky130hd-aes-v4-verified-anchor/`
disappeared while child `orfs_adapter` and OpenROAD detailed-route processes
were alive.  Because the controller did not return, it never wrote
`runtime-execution-receipt.json`, `outcomes.json`, or the required
`target-feasibility-report.json`.  The original formal supervisor correctly
failed closed and did not start the formal campaign.

## Recovery evidence

All remaining child processes were first observed absent from both the
OpenROAD and Adapter process lists.  Only then, on 2026-08-31, the Runtime
Store's public `expire_leases()` operation marked the eight stale attempts
`lost` with failure category `worker_lost`.  No SQL was edited and no attempt
was restarted.  The terminal database counts became:

```text
runs:     failed 10, queued 27, succeeded 8
attempts: failed 2, lost 8, succeeded 8
```

The remaining queued runs were never started and are retained as part of the
invalid lifecycle evidence.  This classification says nothing about QoR or
the feasibility of any configuration.

## Consequence

This directory is `HISTORICAL_EVIDENCE / INVALID_EXECUTION_LIFECYCLE`.
Its raw artifacts can be inspected to diagnose the controller failure, but it
must not be used as the target-domain preflight for a new campaign, be
aggregated with a formal study, or be presented as a PPA result.  The next
campaign starts from fresh output roots under the user-systemd cgroup
supervisor.
