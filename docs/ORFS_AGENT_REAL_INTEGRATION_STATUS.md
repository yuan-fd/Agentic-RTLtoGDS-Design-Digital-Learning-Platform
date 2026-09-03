# ORFS-Agent real integration status

Status: **real integration loop verified on 2026-09-03; not a paper QoR
superiority claim.**  The runs use the pinned upstream algorithm rather than
the local `evolution_campaign` implementation.

## Fixed identities and managed environment

- ORFS-Agent: `https://github.com/ABKGroup/ORFS-Agent.git` at
  `730f1fa11f9c17c0aaac332412af2b2538f42e9b`.
- Native candidate entrypoint:
  `AutoTuner-integration/ORFS-with-AutoTuner/analyst_agent_workbench.py:suggest_bayesian_optimization_configs`.
- Paper ORFS flow: `ce8d36a7fef0ab9c47d183bcf078bce0f60f5a54`.
- Host/tool evidence: [managed environment manifest](../runs/orfs-agent-environment-20260903T1040/managed-env-manifest.json).
- The activation script fixes admitted source/tool locations and clears
  inherited flow work directories.  Compatibility changes are applied only to
  an attempt-private flow copy; neither pinned source checkout is modified.

## Terminal evidence

| Run | Runtime terminal state | Evidence | Result |
|---|---|---|---|
| AES/Sky130HD baseline | succeeded | `runs/orfs-agent-managed/baseline-aes-sky130hd-gui-compat-tools-fixed-20260903T203716/` | area 122497 um²; WNS -0.0464784; TNS -0.0742184; power 0.434902 |
| Upstream candidate 3, native and ProcessAdapter | succeeded | `runs/orfs-agent-managed/upstream-candidate-3-native-and-runtime-20260903T210018/smoke_summary.json` | complete 12-D candidate, Runtime area 150184 um²; WNS -3.66362; TNS -1301.48; power 1.95287 |
| Upstream candidate 2 | failed | `runs/orfs-agent-managed/upstream-candidate-2-runtime-receipt-20260903T214022/runtime/adapter_result.json` | genuine global-route congestion: total overflow 5640 (met2 1834, met4 1885) |
| Candidate proposed after feedback | failed | `runs/orfs-agent-managed/upstream-feedback-candidate-runtime-20260903T214624/runtime/adapter_result.json` | genuine infeasible placement density (`FLW-0024`); candidate/config/log receipt retained |

The original candidate-2 failure directory remains preserved separately.  The
second candidate-2 run exists solely to prove the corrected Runtime failure
receipt; it does not overwrite the original raw failure.

## Parameter evidence terminology

- **Generated**: the field is present in the upstream GP/EI candidate JSON.
- **Transmitted**: it is present in `mapped_config.mk` and the actual `make`
  invocation.
- **Effective**: an ORFS Tcl command or tool log shows the value used by the
  EDA flow.  A transmitted value is not called effective without this extra
  evidence.

Candidate 3 is the complete upstream JSON at
`runs/orfs-agent-managed/upstream-candidate-3-20260903.json`; its materialized
input is `.../upstream-candidate-3-native-and-runtime-20260903T210018/native/mapped_config.mk`.

| Upstream field | Candidate-3 value | State | Actual evidence |
|---|---:|---|---|
| CLK | 0.5 | effective | Yosys log says `Setting clock period to 0.5`; final QoR is artifact-backed. |
| UTIL | 20 | effective | floorplan log says `Defining die area using utilization: 20.00%` and `Effective utilization: 0.200`. |
| TNS_End_Percent | 0 | effective | the executed private `scripts/util.tcl` appends `-repair_tns $::env(TNS_END_PERCENT)` to post-CTS repair; candidate-3 completed that later flow path. |
| GP_PAD | 3 | effective | global-placement log invokes `global_placement ... -pad_left 3 -pad_right 3`. |
| DP_PAD | 3 | effective | the executed private `detail_place.tcl`, `cts.tcl`, and `global_route.tcl` each call `set_placement_padding -left/-right $::env(CELL_PAD_IN_SITES_DETAIL_PLACEMENT)`; candidate-3 completed all three stages. |
| DPO | 1 | effective | the executed private `detail_place.tcl` checks `ENABLE_DPO=1` and invokes `improve_placement`; candidate-3 completed detail placement. |
| PIN_ADJ | 0.1 | effective | private FastRoute Tcl is the actual `FASTROUTE_TCL` input and sets the candidate pin-layer adjustment before global routing. |
| UP_ADJ | 0.1 | effective | the same actual FastRoute Tcl sets the candidate upper-layer adjustment before global routing. |
| LB_ADDON | 0.0 | effective | `set_place_density.tcl` consumes `PLACE_DENSITY_LB_ADDON`; the later feedback candidate demonstrates the resulting density guard (`FLW-0024`). |
| HIER_SYNTH | 1 | effective | candidate takes the hierarchical synthesis route; `1_1_yosys_hier_report.log` records the hierarchy analysis and preserved-module flow. |
| CTS_CSIZE | 10 | effective | CTS invokes `-sink_clustering_size 10`; tool reports groups of up to 10. |
| CTS_CDIA | 80 | effective | CTS invokes `-sink_clustering_max_diameter 80`; tool reports maximum diameter 80.0 um. |

The table is based on the exact copied private Tcl and mapped config inside the
successful attempt, plus the terminal logs for the corresponding stages.  No
parameter is frozen, deleted, or replaced.

## Upstream feedback and continuation

The successful Runtime candidate-3 `ECP_final=4.16362` was appended in memory
to the upstream AES/Sky130HD initialization data and passed directly to the
pinned upstream `suggest_bayesian_optimization_configs` entrypoint.  Its
artifact is
`runs/orfs-agent-managed/upstream-feedback-after-candidate-3-20260903T214526.json`.
It emitted the next complete 12-field candidate, which Runtime subsequently
executed and recorded as an infeasible placement-density failure.  Thus a
failed candidate leaves an evidence-backed terminal receipt and does not block
the next upstream suggestion or Runtime submission.

## Scope boundary

This establishes a bounded integration loop: pinned real upstream proposal,
complete 12-field mapping, baseline, successful Runtime candidate, preserved
infeasible Runtime candidate, and upstream feedback/next proposal.  It does
not claim a fair comparative campaign, paper-number reproduction, or QoR
superiority.
