# L1 M1 real QoR closed-loop acceptance

## Migration boundary

This slice adds one bounded M1 comparison path to the L1 workbench:

    natural-language mux request
    → attributed semantic draft and two required clarifications
    → frozen Goal IR
    → Runtime ORFS baseline
    → Policy-approved registered place_density proposal
    → Runtime ORFS candidate
    → typed Runtime comparison
    → evidence-backed stop decision

It does not add an optimizer, LLM, UI state, or L2 campaign. The only
candidate control is the finalized Goal's existing registered
place_density allowlist. RTL, SDC, PDK, evaluator, and toolchain are not
modified.

## Real acceptance

Command:

    PYTHONPATH=packages/contracts/src:packages/scheduler/src:packages/execution/src:. \
      .tools/venvs/orfs-agent/bin/python scripts/run_l1_tutorial_acceptance.py \
      --output-root /tmp/openroad-l1-m1-http-verified-20260903

Terminal result: exit code 0; the acceptance summary has accepted true.

| role | Runtime run | terminal status | canonical QoR |
| --- | --- | --- | --- |
| baseline | b94874d3c6244718a6b22084f8f94908 | succeeded | WNS 5.90111 ns; area 6.118 um²; DRC 0 |
| candidate | 2e7c522cc409457cad721695fd5ccb5a | succeeded | WNS 5.90111 ns; area 6.118 um²; DRC 0 |

The candidate Runtime TaskSpec contains place_density 0.5; the frozen
baseline is 0.45. Its measured area ratio is 1.0, so the area and DRC
constraints hold. WNS did not improve, and the durable decision is stop;
the platform does not invent a further change.

Artifact evidence:

- acceptance summary:
  /tmp/openroad-l1-m1-http-verified-20260903/l1_tutorial_acceptance_summary.json
  SHA-256 2fc86da6157fb87aef3dd80a8e72aab1d71cce64dd8f24f50c72eb8fde663c6f
- baseline native 6_report.json SHA-256
  fe6c95ff0b67bdf739c8818072e19ff320d75e9b4c7fcf19ba4603cbc26bea00
- candidate native 6_report.json SHA-256
  fe6c95ff0b67bdf739c8818072e19ff320d75e9b4c7fcf19ba4603cbc26bea00

The complete durable sequence is:

    goal_drafted → goal_finalized
    → run_full_flow baseline → state_transition
    → set_flow_params proposal
    → run_full_flow candidate → state_transition
    → compare_runs → reflection_recorded(stop)

## Tests and rollback

Focused contract/API tests:

    PYTHONPATH=packages/contracts/src:packages/scheduler/src:packages/execution/src:. \
      .tools/venvs/orfs-agent/bin/python -m pytest -q \
      tests/test_l1_m1_planner.py tests/test_l1_runtime_bridge.py \
      tests/test_l1_tutorial_semantic.py tests/test_l1_tutorial_profile.py \
      tests/test_l1_workbench_api.py

Result: 22 passed.

The acceptance script is an HTTP client: it starts the L1 server and calls
only the published Session, answers, execute, M1 proposal, candidate, compare,
and events routes. It never imports or calls WorkbenchService directly.

Rollback: revert the M1 slice commits. Runtime evidence is under /tmp and is
not part of the repository; no protected input was changed.
