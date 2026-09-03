# Slice 013 — ORFS-Agent Codex/NVM environment stop record

Date: 2026-09-01

## Problem

The first native ORFS-Agent policy invocation in the frozen v5 formal campaign
failed before the pinned upstream GP/EI routine could run. The user-systemd
service launched the absolute platform-managed Codex executable, but that
executable is an NVM-installed Node script and the service's minimal `PATH`
does not contain the corresponding NVM `bin` directory.

## Evidence preserved

The immutable campaign remains at
`var/orfs-agent-paper-campaign-20260831-v5-telemetry-isolation-7200`.

* 49 of 50 warm-up runs succeeded; one genuine routability failure is retained
  as a failed observation (`aac69b4616434ce6b86719d51eb446d2`, GRT-0116).
* The first optimiser Runtime run (`3daa248a5efb495b9aae8254e3dbb470`) failed
  at `2026-08-31T13:49:21Z` with
  `/usr/bin/env: ‘node’: No such file or directory`.
* Its original `adapter_request.json`, `adapter_result.json`, flat data bridge,
  and 19 distinct feasible observations remain in the attempt workspace.
* The normal platform executable is the symlink
  `~/.nvm/versions/node/v24.18.0/bin/codex` to
  `../lib/node_modules/@openai/codex/bin/codex.js`. Its Node runtime is the
  executable sibling `~/.nvm/versions/node/v24.18.0/bin/node`.
* With `PATH=/usr/bin:/bin`, direct execution of the absolute Codex launcher
  reproduces the error. Prepending its original `bin` directory makes
  `codex --version` succeed (`codex-cli 0.147.0`).

## Why the first bounded repair fails

The first local repair used `Path(executable).resolve()` and then looked for a
`node` sibling. Resolving the Codex symlink changed its parent directory from
NVM's `bin` to `lib/node_modules/@openai/codex/bin`; no Node binary exists
there. The focused fake-file regression passed but did not reproduce the
production symlink topology. That attempted code change and test were
reverted; the failure evidence above is retained.

This is the second observation of the same environment root cause. Per
`AGENTS.md`, no further functional patch is applied in this slice.

## Options

### Option A — one symlink-aware adapter repair (recommended)

For the already-admitted absolute Codex launcher, preserve its lexical launcher
directory (do not resolve the final symlink) when adding its executable `node`
sibling to the policy subprocess `PATH`. Add a regression that uses a real
symlinked `codex` launcher plus a sibling `node`, then repeat the minimal-PATH
native-policy smoke before starting a new frozen campaign.

This changes only the adapter's child-process environment. It does not alter
the upstream ORFS-Agent source, GP/EI code, evaluator, design, PDK, search
domain, or Runtime authority.

### Option B — explicit per-plugin Node launcher contract

Extend the plugin environment lock with a pinned absolute Node executable and
invoke the Codex JavaScript entrypoint through that executable. This is more
explicit but expands the plugin environment contract and requires a new lock
fingerprint and additional admission evidence.

## Recommendation

Adopt Option A as exactly one new migration slice after review. Its acceptance
gate is a real minimal-PATH native-policy invocation using the existing measured
dataset. Do not resume, overwrite, or count v5 as an optimisation comparison:
it contains valid warm-up evidence but no executed GP/EI candidates or
random-control arm.
