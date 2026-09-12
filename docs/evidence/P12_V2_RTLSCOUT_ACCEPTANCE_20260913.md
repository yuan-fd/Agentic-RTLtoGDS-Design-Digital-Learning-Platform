# P12 v2 RTLScout acceptance — 2026-09-13

The new `scripts/run_p12_v2_acceptance.py` entrypoint successfully completed:

- Codex SpecIR generation with complete one-bit `and2` ports;
- explicit SpecIR freeze;
- independent verification-agent oracle generation;
- RTLScout-v2 Runtime invocation;
- multiple candidate evaluations with lint and simulation pass evidence (4/4 checks, 6-transistor AND implementation).

The bounded acceptance run reached a terminal stop at the mutation-quality gate: the minimal combinational AND design produced zero executable mutants, so its mutation score was 0 against the generic 0.8 threshold. No candidate was promoted to ORFS/GDS. A separate retry also encountered an external provider/API error during revision. These are recorded failures, not evidence of a successful P12 flow.
