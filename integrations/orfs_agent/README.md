# ORFS-Agent integration

This directory is an adapter, not a second implementation of ORFS-Agent.
The product-authoritative L2 policy mode is `upstream_full_policy`.  It uses
the clean detached checkout and exact commit recorded in
`environment.lock.json`; the `.external-src` tree is a source-audit cache and
is never an executable plugin source.

`upstream_full_policy` preserves all twelve upstream parameters, including
variable `CLK`, `PIN_ADJ`, `UP_ADJ`, and `HIER_SYNTH`; all three objectives
`ECP`, `DWL`, and `COMBO`; and the pinned upstream scikit-optimize GP/EI
implementation.  The platform validates the hash-bound domain and measured
observations, but it neither freezes dimensions nor generates numeric
candidates itself.  The managed model may select measured training rows only.

The first supported operation is `materialize_dataset`.  It converts the
platform's immutable observations into the exact row-oriented dataset shape
consumed by ORFS-Agent's `parser.py` / `analyst_agent_workbench.py`, while
retaining the original observation identifiers and artifact references.  It
does **not** silently substitute our previous `stateful-l2-portfolio-v1`
optimizer.

`native_agent` is the historical eight-field, fixed-timing comparison profile.
It was admitted through a deliberately narrow provider shim.
The platform-managed `codex-cli:gpt-5.6-terra` selects only a measured training
subset.  The pinned upstream `scikit-optimize` GP/EI implementation generates
the numeric candidates.  The transcript policy, candidate list, source lock,
and Runtime evaluator receipts are retained as artifacts.  The shim never
reintroduces browser API keys, upstream SSH, shell execution, or model-written
numeric parameter vectors.

That fixed-timing profile is retained so old evidence remains decodable; it is
not the complete ORFS-Agent product capability.  In particular, it must fail
closed when its fixed clock or reduced parameter partition is incompatible
with upstream constraints.  No snapping, nearest-value projection, or frozen
subset may be presented as a successful ORFS-Agent run.

The downstream Runtime, not ORFS-Agent, owns OpenROAD process execution,
workspaces, cancellation, seeds, and QoR measurements.  Variable-clock
upstream results are labeled as model-substituted reproduction results and
must be shown beside, never confused with, protected fixed-protocol signoff.
