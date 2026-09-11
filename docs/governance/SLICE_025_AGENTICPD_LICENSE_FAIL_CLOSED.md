# Slice 025 — AgenticPD license admission fails closed

## Intended architectural change

Make the existing AgenticPD license decision executable. The pinned upstream
revision has no LICENSE, COPYING, or verified permission record, so it may be
read for source audit but may not produce a `PluginManifest`, enter a
`PluginRegistry`, execute through Runtime, or be presented as an available
platform plugin.

This slice does not remove the source-audit adapter, typed historical task,
proposal decoder, source lock, tests of data conversion, or prior experiment
evidence.

## File boundary

- `packages/execution/src/openroad_platform_execution/agenticpd_plugin.py`
- `integrations/agenticpd/agenticpd.plugin.json`
- `integrations/plugins.lock.json`
- `integrations/PLUGIN_INVENTORY.md`
- `tests/test_agenticpd_plugin.py`
- current README/operations wording that still describes executable use
- this evidence record

## Before and after dependency edge

Before: caller or manifest-directory loader -> executable AgenticPD manifest
-> `PluginRegistry` -> Runtime -> unlicensed upstream process.

After: factory -> `PermissionError` before filesystem, Git, credential, or
process inspection. Static intake record -> rejected as a `PluginManifest`.
Source-audit code and historical evidence have no executable registry edge.

## Acceptance evidence

Focused tests:

```text
14 passed in 0.55s
```

They prove:

- the Python manifest factory raises `PermissionError` even when given paths
  that do not exist, so no source/Git/credential/process access precedes the
  license gate;
- the preserved static intake record is rejected by both
  `PluginManifest.from_dict` and `PluginRegistry.from_directory`;
- no Runtime or workspace is created; and
- historical typed task and candidate conversion tests remain intact.

Evidence:

- `var/evidence/agenticpd-license-fail-closed-20260904-r1`
- summary SHA-256:
  `ae47662e2f6cb98878e84123c06f4a7dc0f6e29812df1b637a91ce2d344aec08`
- Runtime runs created: `0`
- external source executed: `false`

## Protected components and unrelated behavior

No external checkout is executed, copied, modified, or deleted. No ORFS-Agent,
Runtime, evaluator, RTL, PDK, SDC, or campaign code changes in this slice.

## Rollback

Revert only the listed files. A rollback would reintroduce executable
admission without a qualifying license or permission record.
