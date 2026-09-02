# P0 Product-boundary freeze

Status: proposed for independent merge-gate review
Date: 2026-09-01

## Intent

Freeze the supported product surface before implementation work resumes.  This
is a governance-only migration slice: it changes no executable behavior,
benchmark, evaluator, protocol, artifact, source lock, or external project.

## Product boundary

The supported product path is deliberately singular at each decision point:

```text
natural-language specification -> SpecIR -> platform-managed RTLScout
-> independent verification -> verified RTL artifact -> DesignGoal / typed policy
-> admitted ORFS-Agent DSE plugin -> immutable TaskSpec -> Runtime
-> raw artifacts -> protected QoR
```

L1 will be the typed interaction and trace layer around the approved path.  It
does not create a second RTL generator, numerical optimizer, shell surface, or
QoR authority.

The following are not product paths:

| Scope | Classification | Permitted use |
| --- | --- | --- |
| Local BO/GP, stateful portfolios, offline policy and local evolution algorithms | `LEGACY` | Frozen reproduction or preregistered comparison only. |
| ORFS official AutoTuner and seeded random control | `LEGACY` | Research comparators for frozen, equal-budget arms only. |
| Existing RTL import | `LEGACY` | A legacy route remains reachable pending P2; it is not a supported product RTL creation path and must be isolated to research/fixture intake. |
| TaiWei 3D | `UNKNOWN` | Independently scoped 3D plugin; its admission evidence, not the 2D L1/L2 state machine, determines availability. |
| EDACraft, Craft plans and future specialty integrations | `UNKNOWN` | Separately admitted developer/plugin surfaces, never implicit product fallback. |
| L3/L4 white-box/coding/evolution code | `LEGACY` | Preserve for evidence and future contract work; no L1/L2 product exposure. |
| Existing Web workspace | `LEGACY` | Frozen historical/developer presentation; it still exposes legacy behavior pending P3 and is not the authoritative product surface. |

StateTune and AgenticPD remain source-audit-only because their pinned sources
do not provide a qualifying license record.

## Known transitional bypass (P2 owner)

P0 does not claim that the intended RTL provenance is already enforced.  At
this baseline, an ordinary authenticated caller can use the legacy
`POST /api/designs/import` route and then pass that registered design to
`POST /api/v2/closed-loops`.  The current legacy L2 service checks design
ownership and reads its RTL path, but does not yet require RTLScout provenance
or an independent verification record.  This is a documented legacy bypass,
not an approved second product path.

P2 acceptance must isolate direct import to an explicit research/fixture
surface and make the L2 product service reject any design that lacks verified
RTL provenance.  P0 deliberately does not change that behavior.

## Before and after dependency/ownership statement

There is no code dependency change in P0.

```text
Before: product documentation could describe local BO/GP, 3D, and direct RTL
        intake as peer product paths.
After:  documentation declares one RTL path, one L2 plugin path, an independent
        3D plugin path, and explicit research/legacy boundaries.
```

## Canonical scope and changed files

P0 governs the canonical architecture/contract documents below.  Existing
tutorials, self-evolution reports and specialty-extension pages are retained
as historical material and are classified in the cleanup inventory; they are
not a current product menu and P0 does not rewrite their evidence claims.

- `docs/L1_L2_EXECUTION_CONTRACT.md`
- `docs/governance/LEGACY_CLEANUP_INVENTORY.md`
- `docs/governance/P0_PRODUCT_BOUNDARY_FREEZE.md`
- `docs/governance/ARCHITECTURE_AUDIT.md`
- `tests/test_p0_boundary_docs.py`

## Acceptance

1. The canonical P0 documents name RTLScout as the only RTL creation route and
   ORFS-Agent as the only L2 product optimizer.
2. The inventory classifies local BO/GP, TaiWei and unresolved-license projects
   without presenting them as peer product paths.  Existing direct RTL intake
   is described honestly as transitional legacy behavior pending P2.
3. Historical documents with older product language are explicitly retained as
   `HISTORICAL_EVIDENCE` or `LEGACY`; they cannot be used as current product
   authority.
4. The inventory retains historical code and artifacts; no deletion occurs.
5. `git diff --check` and focused documentation/architecture tests pass.
6. An independent merge-gate audit approves this declaration before P1 begins.

Reproducible focused check (repository-local Python environment):
`PYTHONPATH=packages/contracts/src /share/home/yuanwenjie/.local/bin/pytest -q tests/test_p0_boundary_docs.py`.

## Rollback

Revert only this documentation commit.  P0 has no database, runtime,
toolchain, benchmark, evaluator, protocol, or artifact migration.
