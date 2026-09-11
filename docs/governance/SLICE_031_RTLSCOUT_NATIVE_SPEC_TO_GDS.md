# Slice 031: native RTLScout SpecIR-to-GDS restoration

Status: **complete**

Date: 2026-09-05

## Boundary and intended change

Replace the platform-authored Codex candidate loop on the active SpecIR path
with a provider-only adapter for the pinned RTLScout native Agent:

```text
frozen SpecIR + independent oracle
  -> Runtime rtlscout TaskSpec
  -> upstream run_benchmark.py / core.agent.RTLAgent
  -> native create/edit/evaluate/feedback/best-design loop
  -> Runtime compile/lint + simulation + mutation gates
  -> typed L1 promotion
  -> Runtime ORFS finish
  -> protected evaluator + GDS
```

The platform-managed Codex client returns one typed RTLScout tool call.  It has
no workspace write or shell authority.  RTLScout's native ReAct implementation
executes its bounded file tools and evaluator, chooses the best correct design,
and decides when to stop.  Runtime remains the only owner of processes, terminal
state and registered artifacts.

## External admission

- upstream: `https://github.com/huawei-csl/rtlscout.git`;
- commit: `87a00edf6b9208f657dd9ffdda170004024c08ae`;
- license: BSD-3-Clause-Clear, Green with notice retention;
- native entrypoint: `run_benchmark.py`;
- native Agent: `core.agent.RTLAgent`, Python ReAct backend;
- submodule: `deps/spire-hdl` at
  `448f3935bd78ac96edb1d941d1c18b82cc319963`;
- isolated Python: 3.12.4;
- Verilator: 5.040;
- model authority: platform-managed `codex-cli:gpt-5.6-terra`, with no API key
  in `TaskSpec` or plugin environment.

The clean upstream source was unchanged before and after acceptance.  The
adapter invokes upstream by absolute path and patches only its documented
`build_client` seam in the child process.  It does not modify or vendor the
checkout.

## Compatibility and evidence decisions

1. Codex structured output uses a closed, flat tool envelope.  It is projected
   back into the exact selected upstream tool schema; unknown tools, missing
   required fields and extra fields fail closed.
2. The acceptance uses RTLScout's native `transistors` metric.  The pinned
   commit's `yosys_cells` parser does not understand the server's Yosys 0.63
   output; no pass or cost is synthesized to bypass that upstream gate.
3. Every evaluated source is located through upstream
   `all_evals[].design_file`, copied into a registered candidate artifact and
   hash-linked from `candidate_history.json`.  Alternate filenames are not
   silently replaced by `design.sv`.
4. A registered native provenance receipt records upstream commit, entrypoint,
   Agent/backend identity, oracle hash, provider-trace hash, upstream-result
   hash, candidate-history hash and selected RTL hash.
5. The frozen oracle is protected by RTLScout and is content addressed by the
   platform.  Verification evidence remains a bounded test claim, not a proof
   of arbitrary natural-language correctness.

The former `_codex_cli_candidates` implementation is retained as LEGACY for
historical tests/evidence but is not called by the active `codex-cli` branch.

## Changed files

- `packages/execution/src/openroad_platform_execution/rtlscout_adapter.py`
- `packages/execution/src/openroad_platform_execution/rtlscout_plugin.py`
- `packages/execution/src/openroad_platform_execution/rtlscout_managed_provider.py`
- `packages/execution/src/openroad_platform_execution/rtlscout_native_driver.py`
- `integrations/rtlscout/rtlscout.plugin.json`
- `integrations/plugins.lock.json`
- `integrations/PLUGIN_INVENTORY.md`
- `scripts/run_rtlscout_native_spec_to_gds_acceptance.py`
- `tests/test_rtlscout_native_provider.py`
- `docs/governance/LEGACY_CLEANUP_INVENTORY.md`
- `docs/governance/SLICE_031_RTLSCOUT_NATIVE_SPEC_TO_GDS.md`

## Before and after dependency edge

Before: the production Codex path implemented candidate generation, iteration
and evaluation control inside `rtlscout_adapter.py`, using only upstream
`run_eval.py`.  It was a platform algorithm with RTLScout-shaped evidence, not
the native RTLScout Agent.

After: the platform adapts the LLM client protocol only.  The exact pinned
`run_benchmark.py -> PythonReactBackend -> RTLAgent` path owns the research
loop, while Runtime and the existing verification/promotion services own the
control plane and protected backend evidence.

## Tests and real evidence

Focused regression:

```text
python -m pytest -q tests/test_rtlscout_native_provider.py \
  tests/test_rtlscout_plugin.py tests/test_rtlscout_spec_v2.py
25 passed
```

Canonical acceptance:

- summary:
  `var/evidence/rtlscout-native-spec-to-gds-20260905-r8/summary.json`;
- summary SHA-256:
  `602a13dc56145ab3b3e3f7c290b92c269fe4f137b54e6e14b3185f8b075f4cb0`;
- elapsed: 234.722 seconds;
- RTLScout run: `a8c1f3dc74e14713a928cded6ebeb193`;
- compile/lint run: `8a5c8118d30448198b094504d4d77e08`;
- simulation run: `cf44881b08424592adee249f826b6ae3`;
- mutation run: `95d6b57626b946faaa887235bf463b8b`;
- ORFS finish run: `faf8167596b84c00928b4382e4954227`.

The native Agent measured two correct candidates against all 65,536 input
pairs: `design.sv` at 310 transistors and `design_ripple.sv` at 352.  It chose
the former.  The selected RTL SHA-256 is
`bc06e926eb3b9df99c1455ebb78d04a5f618bda623f261c4437c5a5ed50de69a`.
Independent compile/lint and simulation passed.  The mutation gate killed all
4 executable mutants (score 1.0, threshold 0.8).

ORFS completed synth, floorplan, place, CTS, route and finish.  The registered
GDS is 164,304 bytes with SHA-256
`75caaa20ff2cf4ccc7d1d12efbc6a2ec223a2d3213cb6e0641aed77c3806bcdc`.
Protected evaluation ID
`b37be4df6cc84d53fa66246860554bb3c0e5c3fef1e92eaa904a3b10d997659d`
is feasible: setup WNS 5.65128 ns, hold WNS 4.05748 ns, area 93.1 um²,
power 8.214e-06 W and zero DRC.

Retained attempts:

- `r1`/`r2`: child-environment import failures before model or EDA execution;
- `r3`/`r4`: ambiguous provider schema selected the wrong native file tool;
- `r5`: real 65,536-vector pass, but unsupported `yosys_cells` cost parser
  correctly prevented best-design admission;
- `r6`: complete functional chain and GDS, but acceptance script queried two
  registered facts under the wrong keys;
- `r7`: accepted full chain before alternate-filename candidate archival was
  exercised;
- `r8`: ACTIVE canonical evidence with complete multi-file candidate lineage.

This proves one bounded integration path, not general RTL synthesis quality or
PPA superiority.

## Protected and unrelated behavior

No protected RTL input, PDK, SDC, evaluator rule, RTLScout source, ORFS source,
A2-ORFO plugin or running legacy ORFS-Agent campaign was modified.  The SpecIR,
reference oracle, selected RTL and backend artifacts are hash-linked.  DSE was
not invoked in this slice.

## Rollback

Stop selecting `rtlscout_native_driver.py` for the `codex-cli` provider and
disable that product submission path.  Do not reactivate the legacy local
candidate loop as a native-RTLScout claim.  Preserve all source locks, Runtime
databases, failed attempts, candidate traces and canonical summary as historical
evidence.  The fake provider remains available only for isolated tests.

