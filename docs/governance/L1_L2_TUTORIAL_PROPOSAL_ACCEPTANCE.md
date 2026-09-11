# L1/L2 acceptance against the ASP-DAC 2027 tutorial proposal

reviewed_at: 2026-09-05

Source of truth: `/share/home/yuanwenjie/tool-interact/ASPDAC27-AgenticEDA-Tutorial-zhiangwang-submitted.pdf`.
This report covers only the current L1/L2 scope. Source-level bounded engine
changes and algorithm evolution in proposal sections 4-6 are later L3/L4 work
and are not counted as missing L1/L2 functionality.

## Proposal requirements and current evidence

| Proposal L1/L2 requirement | Current implementation | Status and evidence |
| --- | --- | --- |
| Natural-language request becomes a structured design goal | Managed Codex/Spec conversation produces validated `SpecIR` or `GoalDraft`; unknown required fields become typed clarification questions; model output cannot become shell | Accepted for bounded schemas; Slices 023, 029 and 031 |
| Natural-language requests become structured tool calls | `SemanticToolCall` is validated by Policy before Runtime creates a `TaskSpec`; path/tool/parameter allowlists apply | Accepted; Slices 019, 029 and L1 tutorial evidence |
| Agent queries timing and physical-design results | Typed timing/congestion/DRC/power/metrics queries and allowlisted artifact excerpts return stored Runtime facts | Accepted for registered designs and supported parsers; Slices 034 and 036 |
| Metrics/reports are returned as feedback | Raw logs/artifacts remain canonical; protected QoR and four-domain analyses cite artifact/run hashes | Accepted; Slices 019, 034, 036 and 042 |
| Tool selection, validation, design state and memory are explicit | PDAgent-style Planner/Analyzer/Debugger state, Runtime authority, EDATracer-style artifact graph, convergence and evidence-gated recovery are durable | Accepted for current typed state machine; Slices 035-038 |
| User can run selected physical-design steps and inspect status | L1 terminal workbench exposes Goal/IR, Tool/Policy, Runtime state/evidence and reflection/replay; Runtime executes ORFS stages and preserves cancellation/recovery | Accepted for registered managed profiles; workbench tutorial acceptance |
| Natural-language Spec can reach generated RTL and physical implementation | One real Chinese-language Spec produced native RTLScout RTL, passed independent exhaustive simulation/mutation gates, and reached registered Nangate45 GDS | Accepted for one bounded 8-bit adder, not arbitrary-spec generalization; Slice 031 |
| Feedback can drive a next action, including failure recovery | Real backend failure produced a no-fake-QoR `DiagnosisReport`, typed checkpoint restore, re-verification and successful GDS/protected QoR | Accepted for one frozen failure class; Slice 044 |
| Knowledge/error explanation reuses OpenROAD knowledge | ORAssistant native BM25 retrieval is exposed as a typed, cited, read-only Runtime tool | Accepted retrieval boundary; Slices 032-033 |
| Black-box flow optimization preserves the upstream research algorithm | A2-ORFO is the sole product optimizer; ORFS-Agent is its complete 12-D variable-clock EDA executor; Runtime/protected evaluator own execution/QoR | Architecture and complete-domain admission accepted; Slices 030, 040-041 |
| Previous measured result guides the next optimizer proposal | One real A2 proposal→ORFS→protected evaluator→feedback→next native A2 proposal loop passed; failures are retained | Accepted single-feedback loop; Slice 030 |
| Campaign is durable and independent of the chat/UI process | OS worker owns execution; HTTP is scheduling-only; checkpoints prevent duplicate submission and retain candidate failures | Accepted controller/worker behavior without launching full budget; Slices 039-041 |
| Full optimization campaign demonstrates sustained closed-loop behavior | Frozen native budget is 26 bootstrap + 5×25 feedback = 151 real EDA measurements | **Not yet executed**; no campaign-level PPA or robustness claim |

## What a user can actually do now

For a registered managed design, the terminal workbench accepts a request such
as “improve setup timing without more than 3% area growth; do not modify RTL or
SDC.” It displays the parsed Goal/IR, only unresolved clarification questions,
Policy decisions, typed calls, Runtime stage/attempt state, registered metrics
and artifact references, headroom/blockers, and the final reflection or L2
handoff. It never exposes hidden chain-of-thought, provider credentials, an
arbitrary shell box or unverified QoR.

The Spec-to-RTL path also accepts a natural-language hardware specification,
freezes an independent oracle, invokes native RTLScout, records every
candidate, runs compile/lint, simulation and mutation quality gates, and only
then promotes the exact verified RTL to ORFS/GDS.

These capabilities are both real, but their current usability boundary must be
stated precisely: the browser/terminal does not yet present every SpecIR,
RTLScout, diagnosis, recovery and A2 campaign operation as one polished single
screen. Some Spec-to-RTL operations remain on the API workspace while the L1
terminal is the clearest Goal/Tool/Runtime trace surface. This is a product
composition/usability gap, not an EDA execution gap.

## Remaining L1 gaps

1. General diagnosis is still bounded. Timing/congestion/DRC/power analyzers
   compute cited facts, headroom, blockers and conservative hypotheses, but do
   not yet prove broad root-cause localization across designs and tool
   versions.
2. ORAssistant provides cited OpenROAD knowledge/error explanation, not a
   complete run-aware autonomous debugger.
3. Flexible tool orchestration is typed and safe but intentionally constrained
   to registered capabilities. Broad multi-step planning needs benchmarked
   expansion, not arbitrary shell access.
4. The single user surface should compose Spec conversation, RTLScout
   candidate lineage, backend diagnostics/recovery and A2 monitoring without
   duplicating authority in UI/API code.
5. PostEDA evidence covers one DRC task. Broader DRC/PPA task sampling and
   repair outcomes are still needed before an accuracy claim.

## Remaining L2 gaps

1. The complete 151-measurement A2 campaign has not run. Current evidence proves
   the exact feedback boundary and full domain, not long-horizon performance.
2. Multi-round restart/failure behavior has controller tests and bounded
   acceptance, but needs evidence from the actual full campaign.
3. No optimizer superiority claim is licensed until the frozen campaign and
   fair comparator protocol are completed.

## External evaluation status

- PostEDA-Bench: admitted at pinned commit and passed one two-stage diagnostic
  integration; the score is explicitly non-official.
- CLOSER-Bench: official execution is blocked because the paper has no
  verifiable released source/tasks/license/hidden oracle. A non-official
  alignment audit now reports 5 met, 2 partial and 3 missing after the real
  internal recovery acceptance. It must not be presented as a CLOSER result.

## Reviewer conclusion

The platform now meets the tutorial's L1/L2 **architecture and bounded
functional-loop** target: typed natural-language interaction, real tools,
artifact-backed feedback, an upstream optimizer feedback step, and one
executed cross-stage recovery are demonstrated. It does not yet meet a claim
of broad intelligent diagnosis, arbitrary-spec usability, or complete
long-horizon DSE campaign performance. The next evidence-bearing priority is
the frozen 151-run A2 campaign; the next product priority is composing existing
L1 capabilities into one coherent user surface without moving authority into
the UI.
