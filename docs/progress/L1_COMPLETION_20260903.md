# L1 workbench completion slice record (2026-09-03)

Status: delivered on `main`, working tree clean.
Purpose: handoff record for the L1 completion pass; the open decisions below
belong to the operator / codex, not to this slice.

## Delivered (commits on main, oldest → newest)

| # | Commit | Slice | Evidence |
|---|---|---|---|
| 1 | `2c0e42f` | checkpoint of the prior 178-item WIP tree | clean reversible baseline |
| 2 | `792b707` | Policy denials become visible `policy_decided(deny)` trace events before the raised error (budget/allowlist rejection) | `tests/test_l1_policy_denial_trace.py` |
| 3 | `19ad76a` | Managed Codex CLI `GoalDraft` provider behind `--goal-provider` (`apps/l1_workbench/codex_goal_provider.py`) | `tests/test_l1_codex_goal_provider.py` |
| 4 | `402f358` | Read-only per-event teaching replay (`teaching.py`, `GET .../teaching`) and terminal `:explain` | `tests/test_l1_teaching.py`; HTTP smoke OK |
| 5 | `5d89152` | Visible L1→L2 escalation gate `:l2` (durable `escalate` reflection → `L2HandoffAuthorization` + frozen `OptimizationRequest`; never auto-submits ORFS-Agent) | `tests/test_l1_escalation_gate.py` |
| 6 | `dbad1f2` | Real-ORFS gate acceptance (baseline `26b84120…` + candidate `f168a3a2…`, authorization `l2-auth-4e4754c0…`) | `scripts/run_l1_l2_gate_acceptance.py`; `docs/evidence/l1_l2_gate_smoke-20260903/` + `docs/evidence/L1_L2_GATE_ACCEPTANCE.md` |
| 7 | `6d15f81` | Codex provider decodes stdout JSON; initial drafts emit blocking-only questions (end-to-end codex smoke passed after relay recovered) | same unit tests; smoke result `clarification_required` |
| 8 | `129ca98` | Terminal replay rhythm controls `:pause` / `:resume` (with `:advance` single-step) | `tests/test_l1_terminal_controls.py` |
| 9 | `a2d2e08` | `apps/l1_workbench/README.md` documents goal-provider, teaching and L2 gate surfaces | — |

## Test status

`pytest tests/test_l1_*.py` → **130 passed, 0 failed** (after `6e01288`
retired the `PROPOSE_SEARCH_POLICY` tool and aligned the two affected tests).

## Claim boundaries (deliberate)

- The L1→L2 gate authorizes and freezes an `OptimizationRequest` with real
  ORFS evidence; it does **not** run ORFS-Agent search — execution belongs to
  the durable external campaign controller (consistent with `ba88043`).
- The codex goal provider end-to-end smoke verified the *initial draft +
  clarification* stage. The full clarify→freeze loop over the relay should be
  re-verified once the relay is stable.
- `needs_clarification` is expressed as blocking questions before Goal
  freeze (`goal_drafted` + session status `clarification_required`), not as a
  `policy_decided` event after Goal freeze; that is a contract-level
  property, not an omission fixable in this slice.

## Decisions resolved (2026-09-03)

1. `PROPOSE_SEARCH_POLICY` retired (`6e01288`): removed from `ToolName`, the
   read-only set, the scheduler policy, and the L1 ORFS registry; the
   `state_tuning` historical decoder keeps a string guard for old records;
   the two red tests are fixed and the suite is fully green.

## Open decision for the operator / codex

1. Accept "clarification-before-freeze = needs_clarification visibility"
   (recommended for the MVP), or request a contract change for a post-freeze
   `policy_decided(needs_clarification)` event.
2. Optionally: wire the frozen `OptimizationRequest` into a real ORFS-Agent
   campaign run and produce a full search acceptance (long real-EDA run).
