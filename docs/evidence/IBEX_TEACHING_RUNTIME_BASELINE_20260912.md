# Ibex teaching Runtime baseline evidence

Date: 2026-09-12

This record proves the first fixed Ibex lesson baseline was submitted through
the teaching API and completed in the platform Runtime. It is separate from
the earlier native ORFS baseline record.

## Identity

- Runtime run: `fbfbb60abfae43a8aa1a922567f96af4`
- Runtime status: `succeeded`
- Top: `ibex_core`
- Reference: `sky130hd/ibex`
- Design bundle fingerprint: `a0d446365e9be5984fec45b258027c08b3b070c31b17e616d2700d30a75ac15`
- ORFS commit: `51ad1231a231ee85234c06db807688d029b85c35`
- Runtime worker: `master-b53f37f5`
- Started: `2026-09-12T10:15:37.056615+00:00`
- Finished: `2026-09-12T10:47:42.277403+00:00`

## Inputs

The request came from `POST /api/teaching/reference-baseline` with the
server-pinned `sky130hd/ibex` selector. It carried the complete 21-file RTL
bundle, the fixed `constraint.sdc`, the pinned include directory, Slang
frontend, and the reference flow options. No browser path or shell command
was accepted.

Baseline parameters were core utilization 50%, placement density 0.55,
clock `clk_i`, 10 ns period, OpenROAD seed 101, and target stage `finish`.

## Runtime results

| Metric | Value | Evidence parser |
| --- | ---: | --- |
| Finish instance area | 155774 | `orfs-finish-report-json-v1` |
| Finish setup WNS | -0.0469225 | `orfs-finish-report-json-v1` |
| Finish total power | 0.0505765 | `orfs-finish-report-json-v1` |
| Detailed-route DRC errors | 0 | `orfs-route-report-json-v1` |

The run produced the Runtime artifact set including stage reports and logs,
`6_final.odb`, `6_final.def`, `6_final.v`, and `6_final.gds`. The result is a
valid completed teaching baseline, while the negative setup WNS is shown as a
timing issue for the lesson rather than presented as signoff success.

Raw Runtime evidence is retained under the validation workspace
`/tmp/teaching-ibex-baseline` and can be retrieved through the Runtime run and
artifact APIs.
