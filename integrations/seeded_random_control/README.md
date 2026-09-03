# Seeded Random Control integration

This is an internal evaluation-control plugin, not an external optimizer and
not a fallback for ORFS-Agent.  It produces a deterministic, fixed-seed,
without-replacement sample from a finite domain that has already passed the
target-feasibility gate.

It receives no QoR observation, cannot invoke OpenROAD, and cannot modify a
benchmark.  Runtime invokes it in its own attempt workspace, then uses its
candidate artifact to schedule ordinary ORFS runs.  The protected evaluator is
the only component that can create QoR evidence.

The campaign launcher uses `.tools/venvs/seeded-random-control`.  The
environment is standard-library-only and recorded in `environment.lock.json`.
If fewer unseen legal coordinates than the requested batch remain, the plugin
fails instead of sampling with replacement or changing the frozen domain.
