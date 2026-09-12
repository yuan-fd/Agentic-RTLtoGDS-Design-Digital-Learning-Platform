# P12 v2 RTLScout acceptance — 2026-09-13

The new `scripts/run_p12_v2_acceptance.py` entrypoint successfully completed:

- Codex SpecIR generation with complete one-bit `and2` ports;
- explicit SpecIR freeze;
- independent verification-agent oracle generation;
- RTLScout-v2 Runtime invocation;
- multiple candidate evaluations with lint and simulation pass evidence (4/4 checks, 6-transistor AND implementation).

The acceptance run did not reach a terminal success because a later bounded RTLScout revision received an external provider/API error. The failure was recorded by the Runtime adapter as `rtl_validation_failed`; no candidate was promoted to ORFS/GDS. This is an external execution blocker, not evidence of a successful P12 flow.
