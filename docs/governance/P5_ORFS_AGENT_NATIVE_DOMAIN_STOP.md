# P5 native ORFS-Agent domain stop

## Status

**SUPERSEDED on 2026-09-02 by product direction:** the previous eight-field
domain was historical scope error, not a protected product policy. ORFS-Agent
L2 reproduction uses its complete upstream 12-field protocol. This record is
retained as historical evidence; it must not constrain the active path.

## Historical problem

The admitted upstream ORFS-Agent GP/EI workbench searches its published,
continuous 12-field domain. The product dataset bridge admits a frozen-clock,
complete 8-field platform domain with explicit discrete allowlists.

## Evidence

On 2026-09-02, the bounded native adapter invoked the unmodified upstream
`suggest_bayesian_optimization_configs()` from clean detached commit
`730f1fa11f9c17c0aaac332412af2b2538f42e9b`. It returned a proposal, but the
adapter rejected it with:

`upstream GP/EI proposal is outside the frozen platform allowlist`

The source remained clean. This proves the upstream invocation boundary, but
not a compatible product proposal path.

## Why the current plan fails

Silently rounding, clamping, resampling, or projecting upstream proposals into
the discrete product domain would create a platform-owned optimizer policy.
It would no longer be an unmodified ORFS-Agent GP/EI suggestion, and would
weaken the frozen-protocol guarantee.

## Option A

Freeze a product protocol whose native domain is exactly the upstream 12-field
domain, including an explicit fixed timing policy for comparative evaluation.
This needs an approved protocol change because the present product policy
forbids candidate-specific clock changes.

## Option B

Keep the current frozen 8-field product domain. Admit ORFS-Agent only as a
dataset/analysis bridge until upstream provides a native entrypoint that can
receive the exact constrained domain without local proposal projection.

## Recommendation

Keep the dataset bridge as the active P5 product capability and select Option
A or B explicitly before making GP/EI proposal execution a product path. Do
not commit the experimental native adapter as an admitted plugin.
