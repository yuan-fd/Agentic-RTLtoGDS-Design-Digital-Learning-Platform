# ORFS-Agent integration

This directory is an adapter, not a second implementation of ORFS-Agent.
The pinned upstream source is cached at `.external-src/ORFS-Agent` and is
recorded in `source.lock.json`.

The first supported operation is `materialize_dataset`.  It converts the
platform's immutable observations into the exact row-oriented dataset shape
consumed by ORFS-Agent's `parser.py` / `analyst_agent_workbench.py`, while
retaining the original observation identifiers and artifact references.  It
does **not** silently substitute our previous `stateful-l2-portfolio-v1`
optimizer.

`native_agent` is now admitted through a deliberately narrow provider shim.
The platform-managed `codex-cli:gpt-5.6-terra` selects only a measured training
subset.  The pinned upstream `scikit-optimize` GP/EI implementation generates
the numeric candidates.  The transcript policy, candidate list, source lock,
and Runtime evaluator receipts are retained as artifacts.  The shim never
reintroduces browser API keys, upstream SSH, shell execution, or model-written
numeric parameter vectors.

Only the shared, live ORFS parameter intersection is transportable.  Clock,
pin and routing adjustments and hierarchy synthesis are frozen because they
would change the implementation contract or make a PPA comparison unfair.

The downstream Runtime, not ORFS-Agent, owns OpenROAD process execution,
workspaces, cancellation, seeds, and QoR measurements.
