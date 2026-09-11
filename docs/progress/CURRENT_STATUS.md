# Current status

updated_at: 2026-09-05
phase: L1/L2 tutorial architecture recovery

Unified proposal audit and current claim boundary:
`docs/governance/L1_L2_TUTORIAL_PROPOSAL_ACCEPTANCE.md`.

## 2026-09-05 governed recovery status

- Product L2 is now A2-ORFO (`optimizer.l2.a2-orfo-feedback`). ORFS-Agent is
  retained as A2's complete 12-D variable-clock EDA executor, not as a second
  product optimizer.
- The durable product protocol is frozen at 26 native bootstrap measurements
  plus five rounds of 25 A2 feedback candidates: 151 EDA measurements, zero
  non-native confirmation runs. This full campaign is configured but has not
  been started.
- A real bounded A2 policy -> ORFS -> protected evaluator -> feedback -> next
  A2 candidate loop has passed. Product migration/restart separation has a
  separate no-execution acceptance; see Slice 041.
- Native RTLScout Spec->RTL->GDS, typed ORAssistant knowledge/error retrieval,
  four-domain StageAnalysis/DiagnosisReport, PDAgent-style control state,
  EDATracer-style artifact graph, convergence classification and typed
  recovery policy have bounded accepted evidence in Slices 031-040.
- PostEDA-Bench intake and one real public-case -> four-domain diagnosis ->
  sealed prediction -> private hidden-label scoring path passed in Slice 042.
  The derived 1.0 score is an integration diagnostic, not official SR/ERR/VRR.
- CLOSER-Bench remains Red/source-audit-only because no verifiable source/data
  release, license, frozen A/B/C tasks or hidden oracle is available. The
  platform completed a non-official paper-protocol audit in Slices 043/045.
- One platform-owned real backend-to-RTL recovery passed in Slice 044: a
  functionally correct, synthesis-only blackbox fault failed real ORFS; L1
  persisted a no-fake-QoR DiagnosisReport, typed restore plan and clean RTLScout
  checkpoint selection, then reverified it and reached GDS/protected QoR.

## Product boundary

- The former `POST /api/v2/external-optimizer-loops` create/advance path is
  retired because it represents a reduced-domain, fixed-clock ORFS-Agent
  protocol. Its owner-scoped GET routes remain only for historical evidence.
- The supported L1/L2 path is `apps/l1_workbench`: operator-owned GoalDraft,
  typed Policy and Runtime feedback, measured L1 baseline/candidate/reflection,
  durable L2 authorization, then A2-ORFO policy over the complete upstream
  12-D variable-clock ORFS-Agent executor with ECP/DWL/COMBO.
- Baseline is round 0 inside that loop. Sequential scan, grid/manual tuning,
  standalone baseline, recommendation approval, and manual campaign modes are
  not product routes. Seed, repetition count, search bounds, transition count,
  stall rule, and clock-search controls are rejected at the HTTP boundary.
  The legacy read-only `/api/optimization/studies` surface is also deleted;
  offline stores and comparison policies exist only for reproducible research
  and cannot be mistaken for a second user workflow.
- The browser never accepts a Provider profile or API key. Natural-language
  SpecIR, Verification Agent, and RTLScout use the platform-managed
  `gpt-5.6-terra` Codex service. External RTLScout credential providers were
  deleted from the execution plugin; `fake` is an isolated test fixture only.

## Implemented v2 chain

`natural language -> SpecIR -> independent Verification Agent -> frozen
testbench -> RTLScout candidate iteration -> lint/simulation/mutation -> ORFS
baseline -> A2-ORFO policy -> complete 12-D variable-clock ORFS-Agent execution
-> protected QoR feedback -> next native A2 proposal`

Workflow Runtime is the sole process and artifact authority. Models propose
structured specifications, tests, RTL candidates, diagnoses, or hypotheses;
they cannot register their own PPA numbers or bypass the Runtime.

## Real evidence snapshot

- Current governed product acceptance: native RTLScout Spec->RTL->GDS,
  A2-ORFO single feedback, PostEDA two-stage diagnostic scoring and executed
  backend-to-RTL checkpoint recovery all have immutable Runtime evidence under
  `var/evidence/`; see Slices 030-045. The configured 151-run A2 campaign has
  not been started and no campaign-level PPA claim is made.

- RTL fixed suite: four natural-language designs (gcd, FIFO, UART TX and the
  small `ibex_alu` block), one generation seed each, all reached registered GDS.
  Evidence: `artifacts/v2-real-rtl-suite-20260825/aggregate.json`.
- Multi-design loop: 48 full-flow runs, 3/4 designs reached the preregistered
  0.5% practical utility threshold.
  Evidence: `artifacts/v2-multidesign-closed-loop-20260825/aggregate.json`.
- BO vs seeded random: 144 full-flow runs per policy. Threshold events were
  7/12 for BO and 4/12 for random; per-design median winners were 2:2. This is
  descriptive evidence, not statistical or universal superiority.
  Evidence: `artifacts/v2-parameter-ablation-multiseed-20260825/aggregate.json`.
- Causal holdout: 24/24 full-flow runs. The GCD interaction did not replicate
  on FIFO, so the platform recorded `refuted` and blocked action eligibility.
  Evidence: `artifacts/v2-learning-ablation-20260825/aggregate.json`.
- EDAIR: four real designs expose timing paths, logical and physical objects,
  raw artifact hashes, loss manifests, and bounded Agent packets instead of a
  KPI-only summary. Evidence: `artifacts/v2-edair-ablation-20260825/aggregate.json`.
- Agent architecture: all four real traces contain the stable eight-phase
  protocol; interruption/resume and permission behavior are separately tested.
  Evidence: `artifacts/v2-agent-architecture-20260825/aggregate.json`.

## Claim boundaries

- The RTL experiment is a four-design, one-seed feasibility suite, not proof of
  arbitrary-spec generalization or a complete Ibex core.
- The parameter ablation is too small for a statistical-significance claim.
- The learning experiment blocked one observed false transfer; it is not a
  population estimate or universal causal law.
- EDAIR fidelity and eight-phase traces do not by themselves prove QoR gains.
- v3 repair executors (TimingECO, Resynth, EvoDRC and source evolution) remain
  outside this v2 goal.

The exact protocols and artifact-level boundaries are maintained in
`docs/V2_RESEARCH_ACCEPTANCE.md`. Historical P0-P22 evidence files describe
past prototypes and must not be used as the current product menu.
