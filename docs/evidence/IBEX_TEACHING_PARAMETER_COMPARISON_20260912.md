# Ibex teaching parameter comparison evidence

Date: 2026-09-12

This is the second real teaching run. It reuses the exact server-pinned
`sky130hd/ibex` source bundle, SDC, toolchain and ORFS revision from the
[baseline evidence](IBEX_TEACHING_RUNTIME_BASELINE_20260912.md), and changes
only placement density from `0.55` to `0.60`.

## Runs

| Run | Role | Status | Placement density |
| --- | --- | --- | ---: |
| `fbfbb60abfae43a8aa1a922567f96af4` | baseline | succeeded | 0.55 |
| `5ffcbb58de464496ba8e046f1bfeb171` | comparison | succeeded | 0.60 |

Both runs use top `ibex_core`, bundle fingerprint
`a0d446365e9be5984fec45b258027c08b3b070c31b17e616d2700d30a75ac15`, and the
same fixed clock (`clk_i`, 10 ns).

## Parsed Runtime metrics

| Metric | Baseline | Comparison | Difference (comparison - baseline) |
| --- | ---: | ---: | ---: |
| Finish instance area | 155774 | 154456 | -1318 (-0.85%) |
| Finish setup WNS | -0.0469225 | 0.0508722 | +0.0977947 ns |
| Finish total power | 0.0505765 | 0.0493283 | -0.0012482 |
| Detailed-route DRC errors | 0 | 0 | 0 |

The comparison improved the recorded setup WNS and slightly reduced area and
power for this seed and fixed flow. It is one controlled observation, not a
general claim that density 0.60 is always better; further teaching material
should show the evidence and invite additional runs.

Both Runtime attempts produced the normal finish artifacts, including ODB,
DEF, netlist, GDS, reports and logs. The records remain retrievable through
the Runtime run and artifact APIs.
