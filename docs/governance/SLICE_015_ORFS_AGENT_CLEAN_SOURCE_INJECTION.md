# Slice 015 — clean pinned ORFS-Agent source injection

Date: 2026-09-01

## Problem

The v6 supervisor correctly failed before creating any Runtime task because its
default admitted ORFS-Agent checkout was no longer clean. Its only difference
was an untracked Python bytecode file created when a direct smoke imported the
upstream workbench without `PYTHONDONTWRITEBYTECODE=1`.

The controller's `git status --porcelain` gate is intentionally preserved. A
dirty upstream source must never be silently accepted, reset, or cleaned in
place just to continue an experiment.

## Isolated source admission

A new local clone was made without hardlinks at:

`var/external-sources/orfs-agent-730f1fa-clean-20260901`

It is detached at `730f1fa11f9c17c0aaac332412af2b2538f42e9b` with an empty
status. Its BSD-3-Clause license hash is
`243601633b171278cd98f9ea495cbfc74aad9d7fc062c6e7c81e20d1fc44a22f`; its
upstream GP/EI workbench hash is
`be44cdc27ab106ded5b2a0661c283da06a5a7908f4ee2296dd36e1669e840738`.

The original source is preserved untouched as historical evidence.

## Change boundary

`run_orfs_agent_systemd_campaign.py` now accepts an optional
`--orfs-agent-source` and forwards it only to the formal GP/EI controller. It
records that explicit path in the supervisor receipt. The random-control arm
does not consume it. This makes source selection an explicit supervisor input,
not a hidden environment dependency.

## Verification and rollback

The relevant plugin, scheduler, lifecycle, aggregation, and supervisor tests
passed (`26 passed in 17.41s`), and the new checkout's commit/status were
checked directly.

Rollback reverts only the optional supervisor argument and test. It does not
modify or delete either source checkout or any failed campaign evidence.
