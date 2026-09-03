# L1 M1 mux Hands-on protocol

Status: ACTIVE — frozen acceptance protocol; Runtime metric admission is the
next implementation slice.

## Scope and success claim

This protocol is the only M1 product claim:

```text
user language → semantic draft → required clarification → frozen Goal IR
→ Runtime baseline observation → typed evidence queries → visible proposal
→ Policy → registered parameter plan → Runtime candidate observation
→ artifact-backed comparison → continue or stop
```

It is an L1 mux teaching flow.  It is not an L2 campaign, an ORFS-Agent
optimization result, a PPA-improvement claim, or permission to modify RTL,
SDC, PDK, evaluator, ORFS source, or toolchain source.

## Frozen operator-owned context

| Field | Value | Authority |
| --- | --- | --- |
| Project/design/top | `tutorial_mux` / `mux_2to1` / `mux_2to1` | operator profile |
| RTL | `tests/fixtures/p2_mux_2to1.v`, SHA-256 `ac316a63050a0047533ec6cf5f0a4daa5e4dc135c407bf868eddd6f27439d263` | protected input |
| Platform | `nangate45` | operator profile |
| Clock | 10 ns, protected SDC | operator profile |
| Toolchain | admitted local ORFS/OpenROAD profile | operator profile |
| Baseline | Runtime `run_full_flow` with the frozen default profile | Runtime only |
| Candidate scope | one approved registered parameter plan; no source/SDC edits | Goal + Policy |
| Budget | at most three Runtime EDA submissions | frozen Goal |

## User case and required semantic result

Input:

> Help improve mux setup timing, but area must not increase more than 3% from
> baseline. Do not modify RTL or SDC. Use at most three runs.

The M1 semantic draft must preserve these facts with their source:

```text
intent: optimize
entity: mux / setup timing
preference: maximize setup WNS
constraint: area_baseline_ratio <= 1.03
constraint: drc_errors == 0
protected: RTL, SDC, PDK, evaluator, toolchain
budget: 3
```

Timing corner, baseline identity, and allowed parameter scope are blocking
only when absent from the operator profile or user text.  An operator-owned
default must be visible as such; it is not a user answer.

## Canonical M1 metric mapping

Only these metrics may decide the M1 result.

| Canonical metric | ORFS source | Required Runtime evidence |
| --- | --- | --- |
| `setup_wns_ns` | `logs/nangate45/mux_2to1/base/6_report.json`, key `finish__timing__setup__ws` | registered non-empty report artifact, source artifact id/hash, parser id/version |
| `area_um2` | same report, key `finish__design__instance__area` | same requirements |
| `drc_errors` | `logs/nangate45/mux_2to1/base/5_2_route.json`, key `detailedroute__route__drc_errors` | registered non-empty report artifact, source artifact id/hash, parser id/version |

`congestion` is auxiliary in M1.  If it has no admitted parser/evidence it is
explicitly `unknown`, never zero.

`area_baseline_ratio` is derived only after both baseline and candidate have
canonical `area_um2` observations.  Missing DRC is an `unknown` constraint
result, not `drc_errors = 0` and not a successful closure claim.

## Current evidence and admission gap

The real 2026-09-03 M1 precursor at
`/tmp/openroad-l1-tutorial-acceptance-20260903` proves local ORFS execution:

- Runtime baseline run `8290675dc65940ffb3c611e451e9bd3e` succeeded, exit 0;
- its `6_report.json` contains `finish__timing__setup__ws = 5.90111` and
  `finish__design__instance__area = 6.118`; and
- its `5_2_route.json` contains `detailedroute__route__drc_errors = 0`.

It does **not** yet satisfy this protocol: the runner does not register the
two JSON reports as source artifacts, runtime metrics use the label
`ORFS finish JSON fallback` with no source artifact id/parser identity, and
the separately collected `5_route_drc.rpt` is empty.  The next slice must
admit the two JSON reports through Runtime and bind the three metrics to those
registered artifacts.  Until then no M1 QoR/closure assertion is allowed.

## M1 acceptance and stop conditions

M1 passes only when a new empty Runtime root records both baseline and
candidate observations with all three canonical metrics, each metric has a
registered source artifact, candidate area is compared against baseline,
Policy approves the only mutation, and the final decision has evidence refs.

Stop and report rather than weaken the protocol if a metric cannot be bound to
a registered artifact, the candidate requires source/SDC edits, an action
bypasses Policy/Runtime, or an unchanged protected component would need
modification to improve the result.

## Rollback

This protocol is documentation only.  Revert its commit; it changes no
Runtime, plugin, evaluator, input, toolchain, or historical evidence.
