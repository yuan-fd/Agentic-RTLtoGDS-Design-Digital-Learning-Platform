# Frozen industrial DSE protocols

These files are append-only preregistrations. A protocol is never edited after
an experiment cell is bound to its digest.

- `v2-industrial-dse-20260829.protocol.json` is retained for audit history. It
  separated the official-common domain from the portfolio's full domain, but
  did not include a random or Sobol control on that same full domain. No formal
  superiority claim may compare its full-domain portfolio against common-domain
  baselines.
- `v2-industrial-dse-20260829-r2.protocol.json` added equal-domain controls but
  is retained as a pre-formal draft. Numerical review then replaced legacy
  qNEHVI evaluation with the more stable log-domain qLogNEHVI acquisition.
- `v2-industrial-dse-20260829-r3.protocol.json` added equal-budget
  `random_full` and `sobol_full` controls. The
  portfolio may only be compared with those controls; official AutoTuner,
  Random, Sobol, TPE and qLogNEHVI remain a separate common-domain comparison.
- `v2-industrial-dse-20260829-r4.protocol.json` froze the GP initialization rule
  (`max(32, 4 × dimensions)`), full controller/evaluator source snapshot,
  parameter-caused quick-failure learning boundary, and a strict rule that an
  incomplete or controller-failed fixed-budget cell is invalid rather than a
  zero-scoring optimizer result.
- `v2-industrial-dse-20260829-r5.protocol.json` added a content-addressed
  external-optimizer design adapter,
  so logical reference designs and Official AutoTuner execute byte-identical
  RTL/include/SDC recipes, and freezes the exact baseline-improvement and
  empirical-attainment endpoint definitions.
- `v2-industrial-dse-20260829-r6.protocol.json` resolved the statistical-unit
  ambiguity conservatively:
  all 18 optimizer-seed cells are reported, but the primary paired inference
  first takes the preregistered median across three optimizer seeds inside
  each of the six design-PDK blocks. This prevents seeds from being treated as
  independent design samples.
- `v2-industrial-dse-20260829-r7.protocol.json` closed the external-baseline
  budget asymmetry: Official
  AutoTuner runs one uncharged baseline warm-start plus the complete logical
  candidate budget, so its baseline does not consume one of its candidate
  evaluations.
- `v2-industrial-dse-20260829-r8.protocol.json` gave every Official run a
  digest- and budget-scoped artifact
  namespace, and records restart attempts while resuming only the matching Ray
  experiment. Preflight, protocol revisions and formal cells therefore cannot
  silently share logs.
- `v2-industrial-dse-20260829-r9.protocol.json` binds the actual controller and external AutoTuner Python
  package versions at campaign and cell level, rather than treating minimum
  versions in `pyproject.toml` as execution evidence.
- `v2-industrial-dse-20260829-r10.protocol.json` through `r12` are retained
  preflight revisions. They successively freeze positive runtime evidence,
  safe anchored initialization, and isolation of infrastructure failures from
  surrogate fitting while retaining those failures in the immutable budget
  ledger.
- `v2-industrial-dse-20260829-r13.protocol.json` additionally removes dependent variables that pinned
  Official AutoTuner Hyperopt cannot condition from *every* common-domain arm,
  fixing them at the same calibrated baseline. This prevents an external
  baseline from being charged for illegal Cartesian combinations that native
  optimizers project away.
- `v2-industrial-dse-20260829-r14.protocol.json` makes a safe cold-start anchor require every required
  finish-fidelity OR_SEED replica to satisfy all hard constraints; a lucky
  single seed cannot conceal an unstable configuration.
- `v2-industrial-dse-20260829-r15.protocol.json` applies the same replicated-eligibility rule to
  incumbent utility, stagnation routing and trust-region centers, while each
  failed replica remains available to the probabilistic feasibility model.
- `v2-industrial-dse-20260829-r16.protocol.json` makes the TPE control genuinely hard-constraint-aware:
  frozen observations enter through Optuna's ask/tell lifecycle and signed
  residuals reach `TPESampler.constraints_func`.
- `v2-industrial-dse-20260829-r17.protocol.json` retains a complete fixed-budget
  cell with no feasible point as a completed nonattainment result, rather than being excluded as
  an unfinished diagnosis; its failure diagnosis remains available.
- `v2-industrial-dse-20260829-r18.protocol.json` reconciles the platform's inclusive quantized upper
  bounds with pinned AutoTuner's exclusive `randint`/`arange` bounds by
  encoding one extra step and testing exact value-set equality.
- `v2-industrial-dse-20260829-r19.protocol.json` makes TPE share the typed relational projection used by all
  other plugins and represents parallel pending candidates through Optuna's
  real constant-liar lifecycle, never as value-less pruned observations.
- `v2-industrial-dse-20260829-r20.protocol.json` is retained as
  the corrected exact-enumeration audit step. With six paired design-PDK blocks, its primary sign-flip
  test now reports the exact 64-state tail fraction; Monte Carlo plus-one
  correction is used only when enumeration is not exact.
- `v2-industrial-dse-20260829-r21.protocol.json` is retained as
  the strong-control statistical audit. It rejects cross-arm baseline QoR drift before normalization
  and replaces the mathematically underpowered six-contrast primary family with
  two co-primary, equal-domain strong-control tests. qLogNEHVI must beat the
  per-cell best of Random, Sobol, constrained TPE and Official Hyperopt;
  Portfolio must beat the per-cell best of full-domain Random and Sobol. Holm
  correction applies to exactly those two claims; all pairwise results remain a
  separately labelled secondary family.
- `v2-industrial-dse-20260829-r22.protocol.json` is retained as the
  single-density-policy and cross-aggregation binding audit. It additionally makes generated ORFS adapters emit exactly
  one placement-density policy and content-addresses that configuration rule,
  while native and Official aggregation artifacts must bind both the study ID
  and protocol digest before any statistic is computed.
- `v2-industrial-dse-20260829-r23.protocol.json` is retained as the external-domain
  evidence audit. It freezes the five exact common-domain parameter names and
  makes Official aggregation recompute the domain ID, parameter mapping,
  quantized config digest, domain fingerprint and fairness-manifest fingerprint.
- `v2-industrial-dse-20260829-r24.protocol.json` is retained as the corrected
  ablation inference-unit audit. It corrects the ablation inference unit: three optimizer
  seeds are aggregated inside each design-PDK block, so the six physical blocks
  drive inference and the 18 seed cells remain descriptive rather than
  pseudoreplicated samples.
- `v2-industrial-dse-20260829-r25.protocol.json` is retained as the corrected
  confirmatory-ablation audit. To keep confirmatory inference attainable without
  pseudoreplication, Holm correction covers three co-primary mechanism
  ablations (`no_gp`, `no_memory`, `no_edair`). Other ablations remain complete
  secondary paired estimates; multifidelity is interpreted with compute cost.
- `v2-industrial-dse-20260829-r26.protocol.json` is retained as the crash-safe
  storage audit. A real r12 preflight controller exited with
  SIGBUS while its SQLite WAL databases were live on `fuse.glusterfs`. The
  exact faulting instruction could not be proven without a core dump or kernel
  journal access, so r26 freezes the conservative storage gate: live SQLite is
  node-local; every controller boundary publishes a content-verified SQLite
  backup into one of two alternating shared-filesystem slots; restore requires
  the cell binding and every database hash to match.
- `v2-industrial-dse-20260829-r27.protocol.json` is the current protocol for
  new preflight and formal cells. An r26 Official preflight proved that a
  developer-shell `FLOW_HOME` could redirect upstream AutoTuner from the
  validated worktree. r27 binds every ORFS path-valued environment variable to
  the pinned worktree and records those bindings in the invocation manifest.

Preflight cells bound to an older digest remain engineering evidence and are
never silently merged into a newer formal study.
