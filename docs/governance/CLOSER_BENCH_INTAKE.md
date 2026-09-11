# CLOSER-Bench external-project intake stop record

status: **Red / source-audit only; no executable benchmark artifact available**

reviewed_at: 2026-09-05

## Identity that can be verified

- Title: *CLOSER-Bench: Evaluating Budgeted Cross-Stage Design Closure for
  Hardware Agents*.
- Canonical publication: `https://arxiv.org/abs/2607.16632v1`.
- arXiv identifier/version: `2607.16632v1`, published
  `2026-07-18T04:28:47Z`.
- Authors/maintainers named by the paper: Peilong Zhou, Zhirong Chen, Cangyuan
  Li, Haoyu Gao, Kaiyan Chang, Ziming Qu and Ying Wang.
- Paper PDF SHA-256:
  `84280d8b1a79924c5742fa1536fd1c48622cf93b7dd407d348b02c5b4750ac28`.
- Paper license shown by arXiv: arXiv.org perpetual non-exclusive license.

The paper describes a Harbor-based benchmark over Verilator, Yosys,
OpenSTA/OpenROAD-flow-scripts, KLayout, Sky130HD and pinned image
`openroad/orfs:26Q3-52-gc90beac09`. It describes stage-paired tasks A
(spec-to-RTL), B (RTL-to-GDS) and C (spec-to-GDS), hidden conditions, pristine
verification, trajectory records, multiple budgets and cross-stage recovery.

## Problem

No canonical CLOSER-Bench source/data repository, exact source commit, source
license, task checksum manifest, container digest, native entrypoint or hidden
oracle package is linked from the paper or discoverable through exact-title,
arXiv-ID, author, `firdma`, Harbor and repository searches performed during
intake. GitHub code search requires authentication and supplied no public
candidate; unauthenticated repository search found no matching official
project.

## Evidence

The paper itself states that the full stage-paired model comparison still
requires the macro-based `firdma` flow to close through DRC/LVS and multi-corner
STA, Tasks A-C and the trajectory schema to be frozen, repeated valid trials,
task checksums, containers, raw trajectories and an invalid-run manifest. It
calls the central matrix future evaluation and says the current vertical slice
has one primary design, one PDK and an incomplete final signoff package.

The source-audit lock at `integrations/closer_bench/source.lock.json` records
every verified bibliographic/tool fact and every unavailable execution field.

## Why the current plan fails

The repository charter requires a canonical URL, exact commit, source/data
license, native entrypoint, dependency/security review, native smoke and
bounded platform smoke before execution or registration. None can be derived
from a paper description without recreating the benchmark. Calling a local
fault injection “CLOSER-Bench” would violate both the external intake gate and
`Reuse > Adapt > Reimplement`, and would falsely imply use of its hidden
conditions and scorer.

## Option A

Wait for the authors to publish a canonical repository/release containing an
exact commit, license, task/oracle checksums, Harbor entrypoint and frozen
stage-paired protocol. Then repeat intake, run its smallest native smoke, and
adapt the task/evaluator boundary through Runtime.

## Option B

Immediately perform a platform-owned, CLOSER-inspired readiness audit over the
existing real RTLScout Spec-to-RTL-to-GDS trace and typed recovery evidence.
This can identify missing stage pairs, hidden perturbations, executed rollback,
anytime/cost trajectory fields and oracle parity. It must be labelled
`protocol_alignment_only`, not a CLOSER-Bench result. A separate internally
frozen fault-injection acceptance may test real cross-stage recovery, again
without using the benchmark name.

## Recommendation

Adopt both in order: record the Red intake now, run the non-claiming protocol
alignment audit to make the platform gap actionable, and keep official
CLOSER-Bench execution gated on Option A. Do not create a plugin manifest or
download/execute guessed artifacts.

## Prospective smallest adapter boundary

When a release exists:

```text
frozen task A/B/C + public loop + hidden-oracle handle + budget
  -> Runtime workspace and tool-call accounting
  -> RTLScout/L1/ORFS candidate trajectory
  -> pristine CLOSER verifier process
  -> final reward + AUC + first-feasible + PnR calls
     + public/private gap + recovery confusion matrix + validity
```

Hidden workloads/corners/floorplan seeds must remain scorer-only. The adapter
may map Runtime events to the published trajectory schema but may not invent
the oracle, task pair, rewards or recovery labels.

## Dependencies, environment and security pending review

Paper-declared dependencies are listed above, but their exact versions,
container digest, Harbor task configuration, write set, network/credential
needs, cleanup behavior and allowed edit surfaces cannot be audited without
source. Native smoke and bounded platform smoke are therefore **not
available**, not failed.

## Rollback

This record and lock are audit evidence and should remain. If an official
release appears, supersede them with a new dated intake; do not rewrite this
record to imply that source was available on 2026-09-05.
