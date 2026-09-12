# LLM Teaching Platform audit

Audit date: 2026-09-12  
Branch: `feat/llm-teaching-platform`

This report scores the current repository state using committed code, Runtime
records, immutable evidence directories, and the full regression suite. A
feature is scored as delivered only when its current route and evidence support
the claim; replay, historical artifacts, and unit-only projections are marked
separately.

## Scorecard

| Area | Score | Current evidence | Remaining gap |
| --- | ---: | --- | --- |
| Runtime and environment | 9/10 | Doctor passes; Runtime owns runs, attempts, artifacts and leases; full suite passes (`857 passed, 1 deselected`). | Real EDA load and worker sizing still need a multi-user acceptance. |
| Teaching modes and guided workflow | 9/10 | Guided/Open/Challenge routes, owner-scoped sessions, clarification, Runtime execution and history are implemented and tested. | Browser acceptance should be repeated against a deployed operator configuration. |
| Dashboard and evidence projection | 8/10 | Unified dashboard, campaign detail, live A2 polling, evidence pointers and promotion gate are present. | A2 live UI needs a successful fresh campaign to display a complete trajectory. |
| RTL generation | 8/10 | Native RTLScout SpecIR→RTL→verification→ORFS/GDS evidence is active; Direct LLM registration and shared verification/comparison are implemented. | A fresh dual-path Direct LLM vs RTLScout QoR acceptance is still missing. |
| DSE comparison | 8/10 | Baseline, Rule Batch (1–6), BO/GP, and A2 routes plus campaign read models are implemented. | Full A2 fresh campaign is not complete; no superiority claim is made. |
| A2-ORFO native protocol | 6/10 | Correct r3 checkpoint has 75 historical observations; real runs reach MODEL/SELECTION and real ORFS observation. | Provider capacity errors prevent completion of the fresh policy→candidate→feedback loop. |
| Evidence learning | 8/10 | Evidence references, hashes, Runtime success gate and `eligible_for_review` projection are implemented; no automatic public promotion. | A successful fresh A2 learning cycle remains unavailable. |
| Legacy cleanup and boundaries | 8/10 | Legacy writes fail closed; inventory classifies retained assets; old routes are read-only or retired. | Remaining historical assets require staged archival decisions, not deletion. |

Overall current score: **8.0/10**. The platform is a functional teaching
vertical slice with real Runtime and RTL evidence. It is not yet a complete
release candidate because fresh A2 and dual-path Direct LLM evidence are
incomplete.

## Explicit claim boundaries

- The A2 durable-controller replay proves controller invariants only; it is not
  a new EDA campaign.
- `real-r13` reached native A2 Selection and produced a real Runtime record,
  but provider capacity stopped the run; it is not a successful campaign.
- Existing RTLScout GDS evidence proves the native path for its accepted
  design, not arbitrary-spec generalization.
- Historical local optimizers and old campaign directories remain provenance;
  they are not supported product modes.

## Required next acceptance gates

1. Run one fresh A2 bounded campaign to terminal policy/candidate/feedback
   state with the pinned 12-D protocol and protected evaluator.
2. Run a fresh Direct LLM and RTLScout pair from one frozen SpecIR and
   verification package, then compare measured QoR in the shared read model.
3. Exercise the configured Web server with multiple authenticated,
   owner-scoped sessions and record a bounded 5–10-user concurrency result.
   The current smoke proves 8 concurrent Session creation, L1 execution
   requests, and `observed` terminal snapshots in one isolated local workspace;
   a credential-separated EDA load result is still required.
4. Update this scorecard only from those new evidence records; do not promote
   replay or historical artifacts into current capability claims.
