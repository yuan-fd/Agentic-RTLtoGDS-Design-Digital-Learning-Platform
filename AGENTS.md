# Repository Governance for OpenROAD Platform

This repository is governed as a **thin platform for external research
plugins**.  It is not a place to reimplement every EDA or AI algorithm.

## North-star architecture

The platform owns the shared, deterministic control plane:

- versioned contracts and capability discovery;
- Runtime lifecycle: workspace isolation, resource limits, timeout,
  cancellation, retry/recovery, seeds, events, and artifacts;
- a protected QoR evaluator and frozen experiment protocol;
- path, parameter, permission, and artifact allowlists; and
- durable provenance, audit records, and fair comparison across plugins.

An upstream project owns its research algorithm.  The default order of work is
**Reuse > Adapt > Reimplement**.  Do not create a local "equivalent" of an
upstream optimizer, RTL generator, repair policy, or source optimizer merely
because an adapter is inconvenient.

## Working rules

1. Treat `packages/contracts` as dependency-free public types.  It must not
   import applications, Runtime, execution, analysis, or a concrete plugin.
2. A capability enters the platform only through `PluginManifest`, `TaskSpec`,
   a bounded adapter process, and `PluginResult`.  Capability domains must not
   reach into each other's internals.
3. Keep the API and web layers thin.  They validate transport input, assemble
   approved services, and render stored facts; they do not own EDA processes,
   optimizer algorithms, or authoritative experiment state.
4. Runtime is the sole authority for a run's state, attempt lifecycle,
   artifacts, metrics, cancellation, and recovery.  A plugin or LLM may
   propose work but may not declare its own success.
5. The evaluator, benchmark inputs, RTL, PDK, SDC/timing target, statistics,
   protocol, and provenance are protected.  Never change them to improve an
   optimization claim.
6. Preserve raw logs and artifacts.  LLM summaries and derived EDA/AI views
   are indexes with references, never replacements for source evidence.
7. Do not use an LLM to turn natural language into shell text.  Natural
   language must become a typed `DesignGoal` / `SemanticToolCall`; a policy
   layer validates it before Runtime creates a `TaskSpec`.

## External-project intake gate

Before installing, executing, copying, or registering an external project or
skill, record all of the following in a reviewed lock or intake document:

1. canonical upstream URL and exact commit;
2. license file and redistribution conclusion (Green / Yellow / Red);
3. maintainer/project identity and native entrypoint;
4. dependency, environment, architecture, credential, and network needs;
5. security review of scripts and any write/remote-execution behavior;
6. the smallest adapter boundary and its input/output mapping; and
7. native smoke evidence followed by bounded platform smoke evidence.

No license or permission means **source-audit only**.  Do not vendor, modify,
redistribute, or make such a project an executable plugin.  Pin commits; never
integrate an unpinned branch tip.  Never execute a downloaded script before
inspection.

## Research and evaluation discipline

- Freeze design, RTL hash, PDK/toolchain, SDC, seed policy, search space,
  budget, objectives, constraints, evaluator version, and statistics before a
  comparative campaign starts.
- Compare optimizer arms under the same frozen protocol.  Retain failures and
  repeated runs; never report only a lucky best seed.
- Label a smoke as a smoke.  It proves integration, not PPA superiority.
- Separate prediction from measured QoR.  Only the protected evaluator's
  artifact-backed result is canonical.
- A learning or memory record needs evidence references, scope, conditions,
  counter-evidence/failure handling, and a promotion gate.  A prose success
  note is not learned knowledge.

## Change budget and stop conditions

Perform architectural changes as one migration slice at a time.  A slice has
one stated boundary, a small file list, tests, acceptance evidence, and a
rollback path.  Do not combine API, UI, Runtime, scheduler, evaluator, and
optimizer refactors in one change.

Stop and document `Problem`, `Evidence`, `Why the current plan fails`,
`Option A`, `Option B`, and `Recommendation` when any of these occurs:

- the work crosses unrelated subsystems;
- a thin adapter would require reimplementing upstream research logic;
- a license, commit, dependency, or protocol cannot be verified;
- a protected component would need modification;
- an abstraction only preserves a legacy path;
- assertions would need weakening to make a test pass; or
- a real acceptance artifact is missing.

## Historical material and deletion

Do not delete old code, plans, memory, or experiments simply to make the tree
look clean.  First classify them as `ACTIVE`, `LEGACY`, `INVALID`,
`HISTORICAL_EVIDENCE`, or `UNKNOWN` in
`docs/governance/LEGACY_CLEANUP_INVENTORY.md`.

Deletion requires proof that the active path and published/claimed provenance
do not depend on the item, no external reference needs it, Git can restore it,
and a concrete removal rationale has been reviewed.  Prefer quarantine or an
archive marker to deletion.

## Definition of done for a migration slice

Every completed slice records:

- intended architectural change and every changed file;
- before/after dependency edge;
- focused tests and a real bounded smoke when a tool is involved;
- artifact location, hashes, and terminal status;
- confirmation that protected components and unrelated behavior did not change;
- upstream/commit/license/native-smoke evidence for an external plugin; and
- a precise rollback method.

