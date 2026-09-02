# P1 Product capability allowlist

Status: proposed for independent merge-gate review
Date: 2026-09-01

## Intent

Turn the P0 product-boundary declaration into a dependency-free contract.  An
installed manifest is not automatically a product default: a product caller
must select an explicitly approved role.

## Boundary change

```text
Before: installed PluginManifest -> caller-selected product behavior
After:  installed PluginManifest -> ProductRole allowlist -> product behavior
```

The approved roles are `rtlscout/agent.rtl.generate`,
`orfs-agent/optimizer.l2.propose`, and the separately scoped
`taiwei-pin-3d/eda.3d.pin3d`.  The third role is an extension role, not a 2D
L1/L2 dependency.  No local BO/GP, AutoTuner, seeded random, white-box or
unresolved-license plugin appears in this surface.

## Changed files

- `packages/contracts/src/openroad_platform_contracts/product_surface.py`
- `tests/test_product_surface.py`
- `docs/governance/P1_PRODUCT_CAPABILITY_ALLOWLIST.md`

`openroad_platform_contracts.product_surface` is the dependency-free stable
public submodule for this contract.  P1 deliberately does not alter the root
package re-export list, because that file is shared by unrelated contract
families and is not required to discover this namespaced public type.

## Explicitly out of scope

No API route, Runtime, scheduler, evaluator, benchmark, source lock, plugin
manifest, artifact, or existing registry behavior changes in P1.  P2 will
wire this contract into product HTTP composition and enforce verified RTL
provenance.

## Acceptance and rollback

Focused tests prove that only the approved identity/capability pairs authorize,
that local algorithms are rejected even when capability strings match, and that
TaiWei is an explicit independent role.  Roll back by reverting this small
contract-only change; no stored data or evidence migration is involved.
