# L1 M1-B deterministic semantic draft

The managed mux Hands-on now accepts the tutorial request directly:

> 帮我改善 mux 的 setup timing，但面积不能比 baseline 增加超过 3%，不许修改 RTL/SDC，最多跑 3 次。

The deterministic, non-executing parser records typed interpretation and
field source attribution.  It extracts optimize intent, mux entity, setup WNS
preference, area cap, RTL/SDC protection, and budget `3` from user language.
`drc_zero` is explicitly attributed to the operator-owned M1 profile.

It asks only for the unprovided managed timing-corner/baseline confirmation
and registered parameter scope.  After answers
`managed_mux_default_corner_baseline` and `registered_parameters_only`, the
existing trusted finalizer freezes WNS, DRC and area-ratio constraints.

The provider has no Runtime, tool, path, shell, Tcl, or task construction
access.  A future structured LLM must produce this same `GoalDraft` contract.
Rollback: revert the M1-B commit; no protected input or Runtime behavior is
changed.
