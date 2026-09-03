# Slice 005: systemd-bound ORFS-Agent campaign supervision

Status: accepted before any replacement campaign is launched.

## Problem and evidence

The target-feasibility controller at
`var/orfs-agent-target-feasibility-20260831-sky130hd-aes-v4-verified-anchor/`
disappeared while independent `orfs_adapter` and OpenROAD child processes
continued to run. The Runtime database consequently still contains active
attempts, while the controller cannot produce its terminal receipt, outcomes,
or target-domain report. The formal supervisor correctly failed closed rather
than launching the formal campaign without those artifacts.

The disappearance is an execution-lifecycle failure, not a PPA result: the
still-running children retain their raw workspaces, while the parent controller
is absent. Kernel-log access revealed no OOM evidence; user systemd is
available and a no-op user-systemd probe returned `Result=success` and
`ExecMainStatus=0`.

## Intent and boundary

`scripts/run_orfs_agent_systemd_campaign.py` launches a **new** campaign under
one user-systemd cgroup with `KillMode=control-group`. Its worker is only a
sequencer:

```text
existing preflight script
  -> completed receipt + report SHA-256 gate
  -> admitted ORFS-Agent formal campaign
  -> equal-budget seeded-Random control campaign
  -> fail-closed paired aggregation
```

It does not implement, replace, configure, or score ORFS-Agent GP/EI; it does
not alter RTL, SDC, PDK, toolchain, evaluator, seed policy, search domain, or
statistics. The additional Random arm is a separately declared non-adaptive
control, never a fallback inside the ORFS-Agent adapter. A service loss now
terminates the controller's whole cgroup, rather than leaving unowned tool
children behind.

## Changed files

| File | Change |
| --- | --- |
| `scripts/run_orfs_agent_systemd_campaign.py` | Narrow user-systemd launcher and in-service, fail-closed sequencer for preflight, GP/EI arm, control arm, and aggregation. |
| `tests/test_orfs_agent_systemd_campaign.py` | Verifies controller command construction and receipt/report digest gate. |

## Verification

The user-systemd no-op probe completed with status zero. The focused suite then
passed without weakening an assertion:

```text
21 passed in 20.13s
tests/test_orfs_agent_systemd_campaign.py
tests/test_orfs_agent_plugin.py
tests/test_external_l2_service.py
tests/test_target_feasibility.py
tests/test_package_architecture_boundaries.py
```

`python3 -m py_compile scripts/run_orfs_agent_systemd_campaign.py` and
`git diff --check` also passed.

## Recovery boundary

The existing controller-loss directory is retained as invalid execution
evidence. Its orphaned adapter/OpenROAD processes are not killed, restarted,
or reclassified as successful. Once terminal, their raw files remain available
for diagnosis; they are not eligible for the new preflight report or formal
campaign. A later replacement campaign must use new output directories and
rerun the complete frozen protocol from the beginning.
