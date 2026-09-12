# P12 v2 RTLScout acceptance — 2026-09-13

The new `scripts/run_p12_v2_acceptance.py` entrypoint successfully completed:

- Codex SpecIR generation with complete one-bit `and2` ports;
- explicit SpecIR freeze;
- independent verification-agent oracle generation;
- RTLScout-v2 Runtime invocation;
- multiple candidate evaluations with lint and simulation pass evidence (4/4 checks, 6-transistor AND implementation).

The bounded acceptance run reached a terminal stop at the mutation-quality gate: the minimal combinational AND design produced zero executable mutants, so its mutation score was 0 against the generic 0.8 threshold. No candidate was promoted to ORFS/GDS. A separate retry also encountered an external provider/API error during revision. These are recorded failures, not evidence of a successful P12 flow.

## Follow-up evidence

After the mutation adapter was extended to handle bitwise `&`/`|` substitutions, the preserved RTLScout candidate passed the mutation gate:

- mutation run: `90b025d43e0747cea56ad83f3ccb6a8f`
- status: `passed`

The candidate was then promoted through the real ORFS Runtime with a bounded `nangate45/and2` configuration (core utilization 50%, placement density 0.55, minimum die size 100 um, seed 101):

- ORFS run: `909786433f0d4f4ea13b467f43027389`
- status: `succeeded`
- finish artifacts: GDS, final ODB, DEF, netlist, reports and flow log
- area: `33.516`
- setup WNS: `5.92914`
- total power: `2.62426e-07`
- detailed-route DRC errors: `0`

This closes the RTLScout → mutation → ORFS → GDS promotion path for the bounded `and2` acceptance design. The earlier zero-mutant and PDN/IFP failures remain documented as historical negative evidence.
