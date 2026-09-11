# Slice 022 — L1 managed AES/Sky130HD reference design

## Intended architectural change

Replace the mux-only assumption in the real L1 composition path with an
explicit operator-selected reference-design mode for the paper ORFS
`ce8d36a7fef0ab9c47d183bcf078bce0f60f5a54`. The managed mode binds the full
multi-file AES RTL bundle, its byte-identical 4.5 ns SDC, Sky130HD, the paper
toolchain, fixed baseline settings, and the `finish` target before a language
provider is called. Natural language may describe intent and choose only the
allowlisted L1 actions; it cannot choose or replace these protected inputs.

This slice changes L1 only. It does not alter the upstream ORFS-Agent domain,
initializer, GP/EI, objective definitions, candidate clock, or campaign
budget.

## Planned file boundary

- `packages/execution/src/openroad_platform_execution/orfs_reference_designs.py`
- `packages/contracts/src/openroad_platform_contracts/models.py`
- `packages/execution/src/openroad_platform_execution/orfs_config.py`
- `packages/execution/src/openroad_platform_execution/orfs_adapter.py`
- `packages/execution/src/openroad_platform_execution/orfs_task_factory.py`
- `packages/execution/src/openroad_platform_execution/orfs_plugin.py`
- `packages/execution/src/openroad_platform_execution/orfs_runner.py`
- `packages/execution/src/openroad_platform_execution/__init__.py`
- `apps/l1_workbench/tutorial_profile.py`
- `apps/l1_workbench/tutorial_semantic.py`
- `apps/l1_workbench/service.py`
- `apps/l1_workbench/server.py`
- `apps/l1_workbench/README.md`
- `scripts/run_l1_managed_reference_acceptance.py`
- focused reference, task-factory, profile, and workbench tests
- this evidence record

## Before and after dependency edge

Before: the Workbench accepts one caller-supplied RTL path and hard-codes mux,
Nangate45, a 10 ns clock, 10% utilization, and 0.45 density. That design cannot
legitimately authorize the AES/Sky130HD L2 campaign.

After: the composition root may select one reviewed reference recipe. The
execution package resolves and hashes the complete pinned source bundle; the
generic task-factory port transports it into the existing bounded ORFS
adapter; Runtime still owns execution, evidence, terminal status, and
protected evaluation.

## Acceptance evidence

Focused boundary regression after the final headless-finish compatibility
adaptation reports `52 passed in 17.61s` across the reference resolver,
TaskSpec factory, runner, plugin, semantic compiler, profile, planner,
Workbench API, and protected evaluator boundary suites.

The first real attempt is retained at
`var/evidence/l1-managed-aes-reference-20260904-r1`. Runtime run
`ac22a5167e3340b3954ad4273453de6b` failed after successful Yosys synthesis
because the generic runner required `1_synth.odb`, while the admitted paper
ORFS `make synth` contract ends with a non-empty `1_synth.v`; floorplan is the
first stage that produces an ODB. The runner now treats those two named files
as explicit synthesis-artifact alternatives, registers the netlist, and still
fails when neither exists. No assertion, RTL, SDC, or tool input was weakened.
Its summary SHA-256 is
`9a760e6880bbb9829991de7989bd8f1f8de7b00d67845252c9346fe58dad48af`.

The second real attempt is retained at
`var/evidence/l1-managed-aes-reference-20260904-r2`, summary SHA-256
`d2c6fe0f566d92f3e0d1a62e1e6b33cc47347dbe613d02991395b01efc7b962a`.
Run `96fa3610be994415a2fbf18e981a5566` passed synth, floorplan, place, and CTS
and entered detailed route. Source review then established that its generated
config inherited the platform FastRoute recipe (adjustment 0.2) instead of
the paper AES recipe (0.4). Runtime's controlled cancellation port terminated
it with terminal status `cancelled`; all partial artifacts remain registered.
This run is integration evidence only and is not paper-reference acceptance.
The paper `fastroute.tcl` is now a hash-bound TaskSpec input staged into the
attempt rather than an untracked path or approximate scalar.

The third attempt is retained at
`var/evidence/l1-managed-aes-reference-20260904-r3`, Runtime run
`dd7b7213b22f409489dfbad056782079`, summary SHA-256
`93693fcc63a4f05d3a3c332893c4f64884bc482c697a373a597b033054b94876`.
It used the byte-identical paper FastRoute recipe
`0e7b93c568df6a0894eae5f14fe05b1a47dc766caaa017e50985f06b6770fc85`
and detailed route converged to zero DRC errors, but Runtime correctly kept
the run `failed`: the paper ORFS `final_report.tcl` tested for `save_image`
and then called the unavailable `gui::show` command in the admitted headless
OpenROAD build. This occurred after final implementation reports and physical
files were written, but an artifact's presence does not override the failed
process status.

That failure is part of the condition fixed upstream by ORFS commit
`e7a0725758c0abde2b69e2cdba783435238748ef` ("Correctly check for OR compiled
w/o the GUI enabled.", Fixes upstream issue 3050). The adapter now applies
that one-line upstream backport only when the attempt-private copy of
`scripts/final_report.tcl` has the admitted source SHA-256
`431bbf48065fa534369e78fb846390e8b32226800311c2c927afe27e63f8e7b2`.
The r4 retry is retained at
`var/evidence/l1-managed-aes-reference-20260904-r4`, Runtime run
`79b89623c8754d92a678eed466fa09a4`, summary SHA-256
`1ae8a36beb0df73e4e9bb81cc60c42f0b9a7b474c3a9e18fe6570324d520b044`.
It proved that the ORFS-only half of the
upstream fix is insufficient for the exact paper toolchain: paper OpenROAD
commit `4ee14b488230e046c2e52d9094df85ccf299ac80` was built with
`BUILD_GUI=OFF`, but its build system unconditionally defined `BUILD_GUI`, so
`ord::openroad_gui_compiled` returned true while `gui::show` was absent.
OpenROAD upstream commit
`4630b597e7da45019e0e17f19bc58f9128bdbc03` later fixed precisely this bug
("ord: correct the setting of BUILD_PYTHON & BUILD_GUI": "They were always
defined previously."). Runtime again retained terminal status `failed`; the
route and finish files present in the workspace do not override it.

The final adapter guard therefore composes both upstream fixes: it retains
`ord::openroad_gui_compiled` and requires discovery of the actual `gui::show`
command before optional image generation. It verifies the resulting script
SHA-256
`19e52ae48ac8116a4c451973561e3103b537a330f4e7a5cc14c40d2278708204`
and registers both upstream commits plus both source hashes in
`flow_compatibility.json`. An unrecognized source is left untouched. This
backport changes only the optional visualization guard; RTL, PDK, SDC,
FastRoute settings, extraction, STA, IR analysis, metrics, evaluator, and
optimizer semantics are not changed.

The accepted r5 run is retained at
`var/evidence/l1-managed-aes-reference-20260904-r5`:

- Runtime run `4934a4baebe74ac0bb5943a37a24942a`, attempt
  `7c4eb3691f454cd2b1dafa8d2bbc95e4`, terminal status `succeeded`, exit code 0;
- all six tool stages succeeded: synth 76.202 s, floorplan 49.765 s, place
  190.750 s, CTS 35.949 s, route 868.348 s, finish 74.898 s;
- 25 registered artifacts have 25 unique store keys; every file was reread
  and its size and SHA-256 recomputed with zero mismatches;
- final ODB
  `3ede12460a98314caae2f78fb0659ecc1b62b0933fad27ed3b5568563afabb47`,
  DEF `17e261461fe2aff1fd1bdf43dcce05e1c59e25b8c1b82dd45eeb935cb2f52985`,
  netlist
  `abf55d79f1e456e09b37cf85071ea54802746478f1fc07caa5724956e12212e9`,
  and GDS
  `e0ffd93fc9597eb40cce81e831569a1fabd60bffbe2d3149123a6ca8af6df3b4`;
- the TaskSpec binds all seven RTL files through bundle identity
  `d5c87023d12199cd3d28b815979b7611b0986091fef59abc4e591f18edfc2fc0`,
  the 4.5 ns SDC
  `aa675a0a1ce100a655b230f623a5fb3bdc4e32be92994844abce7243ad9c9d5f`,
  and paper FastRoute recipe
  `0e7b93c568df6a0894eae5f14fe05b1a47dc766caaa017e50985f06b6770fc85`;
- the one and only `official_qor=true` artifact is protected evaluation
  `3c6a24480ccd636f4ef1fdd95ce28fcafeecadca15cca7c1a6ed919c80f731b7`,
  evaluation id
  `5bb95b48990883bbb41abedfdcbf388fe4e6928fee511498426dcb66201b6219`,
  with `runtime_authority=protected_evaluator`;
- summary SHA-256 is
  `636f595490036abfdc5fc585a766de5a3610b703cbce3256f27a3b6273a62cc9`
  and matches the separately written `summary.sha256`.

Runtime success means the bounded implementation lifecycle completed; it is
not a claim that this baseline meets the optimization Goal. The protected
evaluator correctly reports `feasible=false`: DRC is zero, but finish setup
WNS is -0.240581 ns. It also reports `incomplete_stage_json` because this
paper ORFS revision does not emit the stage JSON expected for synthesis even
though Runtime has the successful synth process event and `1_synth.v`. That
normalization mismatch remains visible and must not be erased or used to
promote a QoR claim.

## Protected components and unrelated behavior

The paper RTL, PDK, SDC, ORFS source checkout, evaluator, and L2 optimizer are
not modified. The reviewed backport is applied only to the Runtime-owned flow
copy and is fully receipt-bound. The current mux mode remains available only
as an explicitly named legacy/smoke-compatible L1 profile and cannot be handed
to AES L2.

## Rollback

Revert only the files listed above. Preserve any Runtime database and attempt
workspace produced by the real acceptance run as historical evidence. A
rollback must make the managed AES profile unavailable; it must not silently
substitute mux or the current 3.6 ns ORFS AES recipe.
