"""Preregistered industrial DSE study schema and immutable protocol builder."""

from __future__ import annotations

import hashlib
import json
import copy
from pathlib import Path
from typing import Any, Mapping


PRIMARY_BLOCKS = tuple(
    {"platform": platform, "design": design, "role": "primary"}
    for platform in ("asap7", "sky130hd")
    for design in ("aes", "jpeg", "ibex")
)
EXTERNAL_BLOCKS = (
    {"platform": "asap7", "design": "gcd", "role": "external"},
    {"platform": "sky130hd", "design": "gcd", "role": "external"},
    {"platform": "asap7", "design": "riscv32i", "role": "external"},
    {"platform": "sky130hd", "design": "riscv32i", "role": "external"},
    {"platform": "asap7", "design": "uart", "role": "external"},
    {"platform": "asap7", "design": "cva6", "role": "external"},
)


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def build_industrial_dse_protocol(
    *, calibration_report: Mapping[str, Any], orfs_commit: str,
    toolchain_fingerprint: str, source_snapshot: Mapping[str, str],
    common_evaluator_schema: int = 3,
) -> dict[str, Any]:
    if calibration_report.get("protocol") != \
            "single-knob-low-mid-high-three-paired-seeds-v1":
        raise ValueError("industrial study requires the controlled parameter calibration")
    platforms = {str(row.get("platform")) for row in calibration_report.get("parameters", [])}
    if not {"asap7", "sky130hd", "nangate45"} <= platforms:
        raise ValueError("parameter calibration must cover all three production PDKs")
    unresolved = [row for row in calibration_report.get("parameters", [])
                  if not row.get("search_eligible")]
    value = {
        "schema_version": 28,
        "study_id": "v2-industrial-dse-20260829-r27",
        "title": "Calibrated multi-objective design-space exploration in OpenROAD",
        "freeze_policy": "append-only; any change creates a new study_id and digest",
        "primary_blocks": list(PRIMARY_BLOCKS),
        "external_validation_blocks": list(EXTERNAL_BLOCKS),
        "common_domain_arms": [
            {"arm_id": "random", "optimizer": "seeded-random-mixed-v1"},
            {"arm_id": "sobol", "optimizer": "sobol-scrambled-mixed-v1"},
            {"arm_id": "tpe", "optimizer": "optuna-motpe-mixed-v1"},
            {"arm_id": "qlognehvi", "optimizer": "botorch-ard-matern-qlognehvi-mixed-v2"},
            {"arm_id": "official_autotuner_hyperopt",
             "optimizer": "official-openroad-autotuner-hyperopt"},
        ],
        "full_domain_arm": {
            "arm_id": "industrial_portfolio",
            "optimizer": "industrial-dse-portfolio-v1",
            "search_domain": "calibrated_full",
        },
        "full_domain_arms": [
            {"arm_id": "random_full", "optimizer": "seeded-random-mixed-v1",
             "search_domain": "calibrated_full"},
            {"arm_id": "sobol_full", "optimizer": "sobol-scrambled-mixed-v1",
             "search_domain": "calibrated_full"},
            {"arm_id": "industrial_portfolio", "optimizer": "industrial-dse-portfolio-v1",
             "search_domain": "calibrated_full"},
        ],
        "search_domains": {
            "common": (
                "intersection of controlled-liveness calibration and pinned official "
                "AutoTuner variables.yaml tunable=1, restricted to an independent "
                "Cartesian domain representable by every compared optimizer"),
            "common_domain_id": "official_autotuner_independent_v2",
            "common_parameter_names": [
                "core_utilization_pct", "place_density_lb_addon",
                "global_placement_padding", "cts_cluster_size",
                "cts_cluster_diameter",
            ],
            "relational_parameter_policy": (
                "a dependent variable that upstream Hyperopt cannot condition is removed "
                "from every common-domain arm and fixed at its calibrated baseline; its "
                "independent target may remain tunable only when the fixed value is legal "
                "across the target's full range"
            ),
            "quantized_bound_parity": (
                "platform numeric bounds are inclusive; pinned AutoTuner randint/arange "
                "upper bounds are exclusive, so its generated configuration encodes one "
                "additional quantization step and the enumerated value sets must match"
            ),
            "placement_density_policy": (
                "generated ORFS configurations emit exactly one active placement-density "
                "policy: PLACE_DENSITY_LB_ADDON when that calibrated parameter is present, "
                "otherwise direct PLACE_DENSITY; inactive contradictory assignments are "
                "forbidden and adapter identity binds exclusive-placement-density-v1"
            ),
            "full": "all controlled-liveness-eligible platform parameters",
            "fixed_nonsearch_policy": "server baseline values; never omitted or optimizer-selected",
            "clock_sdc_policy": "frozen per design-PDK block and excluded from every search arm",
            "external_optimizer_design_adapter": (
                "content-addressed execution namespace copies the exact reference RTL, "
                "include files, SDC, HDL frontend, design options and baseline flow "
                "parameters; reports retain the logical design and source fingerprint"
            ),
        },
        "optimization_policy": {
            "batch_size": 8,
            "initialization": (
                "before surrogate fitting, expand from a hard-constraint-feasible "
                "observed anchor with one-factor-at-a-time scrambled Sobol points; "
                "defer high-order combinations, retain every failure in budget, and "
                "fall back to global Sobol when no feasible anchor exists"
            ),
            "safe_anchor_replication": (
                "an anchor is eligible only after all required finish-fidelity OR_SEED "
                "replicas are observed and every replica satisfies every hard constraint; "
                "quick-fidelity, infrastructure-failure and single lucky-seed evidence "
                "cannot establish safety"
            ),
            "replicated_incumbent_policy": (
                "incumbent utility, stagnation routing and trust-region centers use only "
                "configurations with all required finish-fidelity replicas present and "
                "hard-constraint-feasible; infeasible replicas remain individual labels "
                "for the probabilistic feasibility model"
            ),
            "tpe_constraint_handling": (
                "the Optuna multi-objective TPE control imports frozen history through "
                "the ask/tell lifecycle and supplies signed hard-constraint residuals "
                "through TPESampler constraints_func; infrastructure failures are excluded"
            ),
            "tpe_batch_domain_policy": (
                "TPE proposals pass through the same relational typed-domain projection as "
                "Random, Sobol and qLogNEHVI; parallel proposals use Optuna constant_liar=True "
                "and remain RUNNING rather than fabricating value-less pruned observations"
            ),
            "surrogate_minimum_unique_configurations": "max(32, 4 * search_dimensions)",
            "qlognehvi_candidate_pool": 4096,
            "surrogate": "independent ARD Matern-5/2 SingleTaskGP per objective",
            "acquisition": "constrained qLogNEHVI over a deduplicated mixed candidate pool",
            "objective_noise": "replica-derived mean variance with a positive floor",
            "feasibility_model": (
                "configuration-caused ORFS quick/full failures and final hard-constraint "
                "violations; infrastructure failures are retained but excluded from GP fitting"
            ),
            "infrastructure_failure_policy": (
                "lost, cancelled, worker, runtime, adapter, protocol and transient-I/O "
                "failures remain in the immutable budget ledger and deduplication set, "
                "but are excluded from surrogate fitting, feasibility labels and "
                "portfolio failure-rate routing"
            ),
            "stall_route": (
                "after initialization, three non-improving full configurations switch "
                "the portfolio route without ending the fixed budget"
            ),
            "external_baseline_warm_start": (
                "Official AutoTuner receives the same frozen baseline as one explicit "
                "points_to_evaluate observation; the upstream controller runs budget+1 "
                "samples, while the baseline is labeled uncharged and only the remaining "
                "budget candidates enter optimizer endpoints"
            ),
        },
        "metric_contract": {
            "common_evaluator_schema": common_evaluator_schema,
            "canonical_units": {
                "setup_wns_ns": "ns", "setup_tns_ns": "ns",
                "hold_wns_ns": "ns", "area_um2": "um^2",
                "power_W": "W", "drc_errors": "count",
                "runtime_seconds": "s",
            },
            "time_unit_rule": (
                "read run__flow__platform__time_units from ORFS JSON and reject "
                "missing, conflicting, or unsupported unit evidence"
            ),
            "asap7_rule": "public period/slack values are ns; official SDC ps literals remain byte-identical",
            "runtime_evidence_policy": (
                "every formal finish evaluation records finite positive wall time; "
                "native Runtime uses summed stage duration, upstream AutoTuner uses "
                "Ray time_total_s, and paired replay uses controller monotonic time"
            ),
        },
        "optimizer_seeds": [1103, 2207, 3301],
        "paired_or_seeds": [101, 211, 307],
        "budget_checkpoints": [50, 100, 200, 375, 600],
        "budget_unit": "unique proposed effective configuration",
        "execution": {
            "quick_fidelity": "CTS proxy, one OR_SEED",
            "full_fidelity": "finish, three paired OR_SEED replicas",
            "promotion_fraction": 0.30,
            "minimum_full_per_batch": 4,
            "proxy_activation_gate": {
                "minimum_pairs": 12, "minimum_spearman": 0.60,
                "fallback": "promote without trusting proxy ranking",
            },
            "final_replay": (
                "all reported incumbents/Pareto points are replayed at finish with the "
                "same three paired OR_SEED values"),
            "source_freeze": (
                "campaign-wide digest over runner plus all local Python evaluator, "
                "contract, execution and scheduler sources"),
            "state_storage_policy": (
                "live SQLite WAL databases reside only on a node-local filesystem; "
                "every controller boundary publishes a content-verified SQLite backup "
                "to one of two alternating durable shared-filesystem mirror slots; "
                "resume validates the cell binding and every database hash before restore"
            ),
            "external_environment_policy": (
                "Official AutoTuner binds FLOW_HOME, DESIGN_HOME, PLATFORM_HOME, "
                "UTILS_DIR, SCRIPTS_DIR and TEST_DIR to the validated pinned ORFS "
                "worktree; inherited developer-shell paths cannot redirect execution"
            ),
            "completion_gate": (
                "controller/protocol failure invalidates the cell; only a complete fixed "
                "logical budget may enter aggregation"),
            "external_artifact_namespace": (
                "Official AutoTuner experiment names include study mode, protocol digest, "
                "design-PDK, optimizer seed, OR_SEED and logical budget; interrupted cells "
                "resume only that immutable Ray experiment and append controller attempts"
            ),
        },
        "objectives": [
            {"metric": "setup_wns_ns", "direction": "max", "weight": 0.40},
            {"metric": "area_um2", "direction": "min", "weight": 0.35},
            {"metric": "power_W", "direction": "min", "weight": 0.25},
        ],
        "hard_constraints": [
            {"metric": "setup_wns_ns", "operator": ">=", "threshold": 0.0},
            {"metric": "drc_errors", "operator": "<=", "threshold": 0.0},
            {"rule": "NaN, missing final metrics, timeout and tool failure are infeasible"},
        ],
        "primary_endpoints": [
            "observed feasible hypervolume at every budget checkpoint",
            "anytime feasible-hypervolume area under the evaluation curve",
            "evaluations to first feasible baseline-improving point",
        ],
        "endpoint_definitions": {
            "first_baseline_improvement": (
                "first logical round whose repeated finish evaluation is hard-constraint "
                "eligible and whose observed balanced relative utility is strictly greater "
                "than zero; positive hypervolume alone is not improvement"
            ),
            "empirical_attainment": (
                "at each frozen checkpoint, fraction of design-PDK by optimizer-seed "
                "cells that reached first_baseline_improvement, with Wilson 95% interval; "
                "nonattainment remains right-censored at budget"
            ),
        },
        "secondary_endpoints": [
            "area, WNS, TNS, power, DRC, wall time and failure rate",
            "median, IQR, paired bootstrap 95% CI and empirical attainment",
        ],
        "statistics": {
            "unit": "design-PDK block after median aggregation across optimizer seeds",
            "primary_test": (
                "two co-primary one-sided paired sign-flip tests across six design-PDK "
                "blocks on median-over-seeds anytime-HV AUC: qLogNEHVI versus the "
                "per-cell best of equal-budget Random, Sobol, constrained TPE and "
                "Official Hyperopt in the common domain; Portfolio versus the per-cell "
                "best of equal-budget Random and Sobol in the calibrated full domain"
            ),
            "familywise_control": (
                "Holm correction over exactly the two co-primary strong-control tests; "
                "pairwise arm contrasts form a separately labelled secondary family"
            ),
            "strong_control_policy": (
                "within each optimizer-seed cell the composite baseline is the maximum "
                "observed anytime-HV AUC among its equal-budget, equal-domain control "
                "arms; this gives controls more aggregate compute and is conservative "
                "for the candidate, while retaining every component arm in the report"
            ),
            "baseline_parity_policy": (
                "before normalization or inference, every optimizer cell for a given "
                "design-PDK must have an identical content fingerprint over replicated "
                "baseline objective summaries, hard constraints, replica counts and "
                "eligibility; run IDs, runtime and scheduling timestamps are excluded"
            ),
            "effect_sizes": [
                "paired median difference", "paired win-tie-loss",
                "paired bootstrap CI", "unpaired descriptive Cliff delta"],
            "aggregation_rule": (
                "never pool EDA replicas or optimizer seeds as independent primary "
                "samples; report all 18 seed cells descriptively, aggregate their "
                "three seeds within each design-PDK block for inference"
            ),
            "ablation_inference_unit": (
                "mechanism ablations use the same six design-PDK blocks as primary "
                "inference after median aggregation across the three optimizer seeds; "
                "the 18 seed cells are descriptive and are never treated as independent"
            ),
            "ablation_co_primary_ids": ["no_gp", "no_memory", "no_edair"],
            "ablation_family_policy": (
                "Holm familywise control applies to exactly three co-primary mechanism "
                "claims aligned with parameter exploration, evolution memory and EDAIR; "
                "remaining ablations are secondary paired effect estimates without "
                "confirmatory rejection labels, and no_multifidelity is interpreted with "
                "runtime and compute cost rather than QoR alone"
            ),
            "reporting_rule": "report every seed, failure, exclusion, timeout and checkpoint",
            "exact_small_sample_policy": (
                "with six design-PDK blocks, enumerate all 2^6 paired sign flips and "
                "report the exact tail fraction without a Monte Carlo plus-one correction; "
                "the analysis unit label is the block after median-over-seeds aggregation"
            ),
        },
        "ablations": [
            {"ablation_id": "no_gp", "removed": "surrogate/acquisition",
             "replacement": "scrambled Sobol with equal budget"},
            {"ablation_id": "no_multifidelity", "removed": "CTS screening",
             "replacement": "every proposal receives finish evaluation"},
            {"ablation_id": "no_feasibility", "removed": "failure probability constraint"},
            {"ablation_id": "no_trust_region", "removed": "stall-localized TuRBO-style route"},
            {"ablation_id": "no_memory", "removed": "validated numeric priors and routing hints"},
            {"ablation_id": "no_stage_focus", "removed": "diagnosis-guided local dimensions"},
            {"ablation_id": "no_edair", "removed": "typed loss-aware EDA evidence packet"},
            {"ablation_id": "no_safe_initialization",
             "removed": "feasible-anchor one-factor-at-a-time Sobol cold start",
             "replacement": "global scrambled Sobol with equal candidate budget"},
            {"ablation_id": "single_replica_error_control",
             "removed": "replicated final replay", "interpretation": "variance/claim error only"},
        ],
        "ablation_budget": 200,
        "stopping": {
            "algorithmic": "fixed maximum budget; checkpoints do not stop a losing arm",
            "engineering": "only explicit timeout, disk guard, cancellation or toolchain invalidation",
            "stall_routing": "three non-improving full configurations change optimizer route, not study budget",
            "nonattainment_completion": (
                "a cell that exhausts the complete fixed logical budget without a feasible "
                "configuration is a valid completed nonattainment outcome, not an incomplete "
                "or excluded controller failure; its diagnosis is retained"
            ),
        },
        "reproducibility": {
            "orfs_commit": orfs_commit,
            "toolchain_fingerprint": toolchain_fingerprint,
            "source_snapshot": dict(sorted(source_snapshot.items())),
            "python_environment_policy": (
                "campaign and every cell bind a canonical fingerprint of the actual "
                "controller Python plus numpy, scipy, torch, gpytorch, botorch, optuna, "
                "ray and hyperopt versions; Official cells additionally fingerprint the "
                "external AutoTuner virtual environment"
            ),
            "aggregation_binding_policy": (
                "native and Official evidence-aggregation artifacts carry both study_id "
                "and protocol_digest, and the paired statistics layer rejects any mismatch "
                "before normalization, endpoint construction or hypothesis testing"
            ),
            "external_domain_binding_policy": (
                "Official fairness evidence binds the common domain ID, exact sorted "
                "platform-parameter names, inclusive value mappings, generated config "
                "digest and semantic manifest fingerprint; aggregation recomputes all "
                "bindings instead of trusting a self-declared config hash"
            ),
            "calibration_report_fingerprint": _digest(calibration_report),
            "unresolved_parameters_excluded": [
                {"platform": row.get("platform"), "parameter": row.get("parameter"),
                 "classification": row.get("classification")}
                for row in unresolved
            ],
        },
        "claim_boundaries": [
            "No optimizer-superiority claim is made before all paired primary cells finish.",
            "Official AutoTuner is compared on the common domain; the full-domain portfolio is compared only with full-domain random and Sobol controls.",
            "A successful run proves execution only; optimization requires repeated common-evaluator statistics.",
            "The six primary blocks provide moderate power for large effects, not universal EDA generalization.",
        ],
    }
    value["protocol_digest"] = _digest(value)
    validate_industrial_dse_protocol(value)
    return value


def build_stateful_l2_protocol(
    *, calibration_report: Mapping[str, Any], orfs_commit: str,
    toolchain_fingerprint: str, source_snapshot: Mapping[str, str],
    common_evaluator_schema: int = 3,
) -> dict[str, Any]:
    """Freeze a new study for the L1-guided, stateful L2 controller.

    Earlier r27 artifacts remain immutable engineering/preflight evidence for
    the static portfolio.  This function creates a distinct protocol identity
    rather than silently relabelling those results as evidence for the new
    algorithm.
    """
    value = copy.deepcopy(build_industrial_dse_protocol(
        calibration_report=calibration_report, orfs_commit=orfs_commit,
        toolchain_fingerprint=toolchain_fingerprint, source_snapshot=source_snapshot,
        common_evaluator_schema=common_evaluator_schema,
    ))
    # r28 was an engineering preflight made before the final EDAIR failure
    # degradation and evidence-compaction fixes; r29 exposed and fixed a
    # campaign namespace bug; r30 preceded formal source-freeze enforcement.
    # Keep all immutable and bind every claim about the repaired controller to
    # this new protocol identity.
    value["schema_version"] = 32
    value["study_id"] = "v2-industrial-dse-20260830-r31-stateful-l2"
    value["title"] = "Stateful L1-guided constrained multi-objective OpenROAD exploration"
    stateful = {"arm_id": "stateful_l2_portfolio",
                "optimizer": "stateful-l2-portfolio-v1",
                "search_domain": "calibrated_full"}
    value["full_domain_arm"] = stateful
    value["full_domain_arms"] = [
        {"arm_id": "random_full", "optimizer": "seeded-random-mixed-v1",
         "search_domain": "calibrated_full"},
        {"arm_id": "sobol_full", "optimizer": "sobol-scrambled-mixed-v1",
         "search_domain": "calibrated_full"}, stateful,
    ]
    value["optimization_policy"]["stateful_l2_policy"] = (
        "L1 may select only feasibility_recovery, global_exploration, "
        "interaction_screening, local_trust_region, cost_aware_promotion or "
        "replicated_confirmation with evidence references and an allowlisted "
        "parameter subset; it cannot emit numeric candidates. The L2 controller "
        "projects observed configurations into that legal conditional subspace and "
        "BO/GP generates the numerical vector. When no admissible L1 policy exists, "
        "the deterministic evidence-bound fallback is labelled as such."
    )
    value["optimization_policy"]["constraint_surrogate"] = (
        "one signed GP residual per hard constraint, including configuration-caused "
        "failures as positive residuals; qLogNEHVI treats every residual <= 0 as feasible"
    )
    value["optimization_policy"]["edair_context_policy"] = (
        "L1 state policy consumes provenance-linked EDAIR when available. It passes at "
        "most eight ranked handles (EDAIR before run, study and artifact handles) to the "
        "policy context, while Runtime retains every raw artifact and its hash. If an "
        "optional netlist projection cannot be parsed, the run report, QoR, artifact "
        "index and loss manifest remain available; the controller must label that view "
        "missing rather than inventing an object graph. The no_edair ablation blocks "
        "all runtime EDAIR reads by the state policy as well as the older portfolio."
    )
    value["execution"]["l1_semantic_tool_policy"] = (
        "L1 submits only typed, allowlisted semantic calls: create_experiment, "
        "set_flow_params, run_stage, timing/congestion/DRC/power queries, comparison, "
        "policy proposal, stop and escalation. No generic shell command, script path, "
        "environment variable, credential, unregistered stage or unregistered parameter "
        "is accepted. run_stage acknowledgement means queued/accepted only; QoR becomes "
        "visible solely after the protected Runtime records a completed evaluation."
    )
    value["execution"]["campaign_namespace_policy"] = (
        "Runner exclusively owns each cell output directory and creates the cell manifest "
        "before any other writer. Campaign diagnostics are written under controller-logs, "
        "outside the cell namespace; a pre-existing unbound cell remains rejected instead "
        "of being silently reused."
    )
    value["execution"]["frozen_controller_binding_policy"] = (
        "In paper mode, Campaign and Runner independently recompute the controller "
        "source content digest and reject execution unless it equals the controller digest "
        "stored in this frozen protocol. A campaign-local manifest hash is additional "
        "evidence, never a replacement for the protocol binding."
    )
    value["ablations"].append({
        "ablation_id": "no_state_policy",
        "removed": "L1 evidence-bound strategy/subspace selector; retain the same BO, "
                   "parameter domain, budget and Runtime evaluator",
    })
    value["claim_boundaries"].append(
        "r27 static-portfolio results are not pooled with this stateful-L2 study; "
        "only r31 cells sharing this digest support a state-policy claim.")
    value.pop("protocol_digest", None)
    value["protocol_digest"] = _digest(value)
    validate_industrial_dse_protocol(value)
    return value


def validate_industrial_dse_protocol(value: Mapping[str, Any]) -> None:
    checkpoints = list(value.get("budget_checkpoints") or ())
    if (not checkpoints or checkpoints != sorted(set(checkpoints))
            or checkpoints[-1] != 600):
        raise ValueError("budget checkpoints must be unique, increasing, and end at 600")
    if len(value.get("primary_blocks") or ()) < 6:
        raise ValueError("industrial DSE protocol requires at least six primary blocks")
    if len(value.get("optimizer_seeds") or ()) < 3 or len(value.get("paired_or_seeds") or ()) < 3:
        raise ValueError("industrial DSE protocol requires three optimizer and ORFS seeds")
    if any("clock" in str(row.get("metric", "")).lower()
           for row in value.get("objectives") or ()):
        raise ValueError("clock target cannot be an objective or search proxy")
    if int(value.get("schema_version") or 0) >= 2:
        contract = value.get("metric_contract") or {}
        if contract.get("common_evaluator_schema") != 3:
            raise ValueError("industrial DSE requires common evaluator schema 3")
        if (contract.get("canonical_units") or {}).get("setup_wns_ns") != "ns":
            raise ValueError("industrial DSE timing must use canonical ns")
    if int(value.get("schema_version") or 0) >= 27:
        storage = str((value.get("execution") or {}).get("state_storage_policy", ""))
        if not all(term in storage for term in (
                "node-local", "content-verified", "two alternating", "cell binding")):
            raise ValueError("industrial DSE requires crash-safe local SQLite mirroring")
    if int(value.get("schema_version") or 0) >= 28:
        environment = str((value.get("execution") or {}).get(
            "external_environment_policy", ""))
        if not all(term in environment for term in (
                "FLOW_HOME", "DESIGN_HOME", "PLATFORM_HOME", "SCRIPTS_DIR",
                "validated pinned ORFS")):
            raise ValueError("industrial DSE requires pinned external flow paths")
    if int(value.get("schema_version") or 0) >= 5:
        policy = value.get("optimization_policy") or {}
        if (policy.get("batch_size") != 8
                or "max(32, 4 * search_dimensions)" !=
                policy.get("surrogate_minimum_unique_configurations")):
            raise ValueError("industrial DSE optimizer initialization policy is missing")
        execution = value.get("execution") or {}
        if "complete fixed" not in str(execution.get("completion_gate") or ""):
            raise ValueError("industrial DSE fixed-budget completion gate is missing")
    if int(value.get("schema_version") or 0) >= 6:
        adapter = str((value.get("search_domains") or {}).get(
            "external_optimizer_design_adapter") or "")
        if "exact reference RTL" not in adapter or "SDC" not in adapter:
            raise ValueError("industrial DSE external optimizer design parity is missing")
        endpoints = value.get("endpoint_definitions") or {}
        if ("strictly greater than zero" not in str(
                endpoints.get("first_baseline_improvement") or "")
                or "Wilson 95%" not in str(
                    endpoints.get("empirical_attainment") or "")):
            raise ValueError("industrial DSE attainment endpoints are underspecified")
    if int(value.get("schema_version") or 0) >= 7:
        statistics = value.get("statistics") or {}
        if ("median aggregation across optimizer seeds" not in str(
                statistics.get("unit") or "")
                or "never pool EDA replicas or optimizer seeds" not in str(
                    statistics.get("aggregation_rule") or "")):
            raise ValueError("industrial DSE hierarchical primary unit is missing")
    if int(value.get("schema_version") or 0) >= 8:
        warm = str((value.get("optimization_policy") or {}).get(
            "external_baseline_warm_start") or "")
        if "budget+1" not in warm or "uncharged" not in warm:
            raise ValueError("industrial DSE external warm-start budget parity is missing")
    if int(value.get("schema_version") or 0) >= 9:
        namespace = str((value.get("execution") or {}).get(
            "external_artifact_namespace") or "")
        if "protocol digest" not in namespace or "append controller attempts" not in namespace:
            raise ValueError("industrial DSE external artifact isolation is missing")
    if int(value.get("schema_version") or 0) >= 10:
        environment = str((value.get("reproducibility") or {}).get(
            "python_environment_policy") or "")
        if "botorch" not in environment or "external AutoTuner" not in environment:
            raise ValueError("industrial DSE Python environment evidence is missing")
    if int(value.get("schema_version") or 0) >= 11:
        runtime = str((value.get("metric_contract") or {}).get(
            "runtime_evidence_policy") or "")
        if ("finite positive wall time" not in runtime
                or "Ray time_total_s" not in runtime
                or "monotonic" not in runtime):
            raise ValueError("industrial DSE runtime evidence policy is missing")
    if int(value.get("schema_version") or 0) >= 12:
        initialization = str((value.get("optimization_policy") or {}).get(
            "initialization") or "")
        registered = {row.get("ablation_id") for row in value.get("ablations") or ()}
        if ("one-factor-at-a-time" not in initialization
                or "retain every failure in budget" not in initialization
                or "no_safe_initialization" not in registered):
            raise ValueError("industrial DSE safe initialization policy is missing")
    if int(value.get("schema_version") or 0) >= 13:
        infrastructure = str((value.get("optimization_policy") or {}).get(
            "infrastructure_failure_policy") or "")
        if ("immutable budget ledger" not in infrastructure
                or "excluded from surrogate fitting" not in infrastructure
                or "portfolio failure-rate routing" not in infrastructure):
            raise ValueError("industrial DSE infrastructure-failure isolation is missing")
    if int(value.get("schema_version") or 0) >= 14:
        domains = value.get("search_domains") or {}
        if (domains.get("common_domain_id") != "official_autotuner_independent_v2"
                or "dependent variable" not in str(
                    domains.get("relational_parameter_policy") or "")
                or "every common-domain arm" not in str(
                    domains.get("relational_parameter_policy") or "")):
            raise ValueError("industrial DSE relational-domain parity policy is missing")
    if int(value.get("schema_version") or 0) >= 15:
        anchor = str((value.get("optimization_policy") or {}).get(
            "safe_anchor_replication") or "")
        if ("all required finish-fidelity OR_SEED replicas" not in anchor
                or "every replica" not in anchor
                or "single lucky-seed" not in anchor):
            raise ValueError("industrial DSE replicated safe-anchor policy is missing")
    if int(value.get("schema_version") or 0) >= 16:
        incumbent = str((value.get("optimization_policy") or {}).get(
            "replicated_incumbent_policy") or "")
        if ("stagnation routing" not in incumbent
                or "trust-region centers" not in incumbent
                or "all required finish-fidelity replicas" not in incumbent):
            raise ValueError("industrial DSE replicated incumbent policy is missing")
    if int(value.get("schema_version") or 0) >= 17:
        tpe = str((value.get("optimization_policy") or {}).get(
            "tpe_constraint_handling") or "")
        if ("ask/tell lifecycle" not in tpe
                or "signed hard-constraint residuals" not in tpe
                or "constraints_func" not in tpe):
            raise ValueError("industrial DSE constrained-TPE policy is missing")
    if int(value.get("schema_version") or 0) >= 18:
        nonattainment = str((value.get("stopping") or {}).get(
            "nonattainment_completion") or "")
        if ("valid completed nonattainment" not in nonattainment
                or "complete fixed logical budget" not in nonattainment
                or "diagnosis is retained" not in nonattainment):
            raise ValueError("industrial DSE nonattainment completion policy is missing")
    if int(value.get("schema_version") or 0) >= 19:
        bounds = str((value.get("search_domains") or {}).get(
            "quantized_bound_parity") or "")
        if ("platform numeric bounds are inclusive" not in bounds
                or "upper bounds are exclusive" not in bounds
                or "enumerated value sets must match" not in bounds):
            raise ValueError("industrial DSE quantized-bound parity policy is missing")
    if int(value.get("schema_version") or 0) >= 20:
        batch = str((value.get("optimization_policy") or {}).get(
            "tpe_batch_domain_policy") or "")
        if ("same relational typed-domain projection" not in batch
                or "constant_liar=True" not in batch
                or "value-less pruned observations" not in batch):
            raise ValueError("industrial DSE TPE batch/domain policy is missing")
    if int(value.get("schema_version") or 0) >= 21:
        exact = str((value.get("statistics") or {}).get(
            "exact_small_sample_policy") or "")
        if ("all 2^6 paired sign flips" not in exact
                or "without a Monte Carlo plus-one correction" not in exact
                or "median-over-seeds" not in exact):
            raise ValueError("industrial DSE exact small-sample policy is missing")
    if int(value.get("schema_version") or 0) >= 22:
        statistics = value.get("statistics") or {}
        primary = str(statistics.get("primary_test") or "")
        family = str(statistics.get("familywise_control") or "")
        strong = str(statistics.get("strong_control_policy") or "")
        parity = str(statistics.get("baseline_parity_policy") or "")
        if ("two co-primary" not in primary
                or "qLogNEHVI" not in primary
                or "Official Hyperopt" not in primary
                or "Portfolio" not in primary
                or "exactly the two co-primary" not in family
                or "separately labelled secondary" not in family
                or "maximum observed anytime-HV AUC" not in strong
                or "more aggregate compute" not in strong
                or "identical content fingerprint" not in parity
                or "run IDs" not in parity):
            raise ValueError("industrial DSE strong-control statistics policy is missing")
    if int(value.get("schema_version") or 0) >= 23:
        density = str((value.get("search_domains") or {}).get(
            "placement_density_policy") or "")
        aggregation = str((value.get("reproducibility") or {}).get(
            "aggregation_binding_policy") or "")
        if ("exactly one active placement-density policy" not in density
                or "PLACE_DENSITY_LB_ADDON" not in density
                or "exclusive-placement-density-v1" not in density
                or "both study_id and protocol_digest" not in aggregation
                or "rejects any mismatch" not in aggregation):
            raise ValueError("industrial DSE density/aggregation identity policy is missing")
    if int(value.get("schema_version") or 0) >= 24:
        domains = value.get("search_domains") or {}
        names = domains.get("common_parameter_names") or []
        external = str((value.get("reproducibility") or {}).get(
            "external_domain_binding_policy") or "")
        if (names != ["core_utilization_pct", "place_density_lb_addon",
                      "global_placement_padding", "cts_cluster_size",
                      "cts_cluster_diameter"]
                or "exact sorted platform-parameter names" not in external
                or "semantic manifest fingerprint" not in external
                or "recomputes all bindings" not in external):
            raise ValueError("industrial DSE external common-domain binding is missing")
    if int(value.get("schema_version") or 0) >= 25:
        ablation_unit = str((value.get("statistics") or {}).get(
            "ablation_inference_unit") or "")
        if ("same six design-PDK blocks" not in ablation_unit
                or "median aggregation" not in ablation_unit
                or "18 seed cells are descriptive" not in ablation_unit
                or "never treated as independent" not in ablation_unit):
            raise ValueError("industrial DSE ablation inference unit is missing")
    if int(value.get("schema_version") or 0) >= 26:
        statistics = value.get("statistics") or {}
        ids = statistics.get("ablation_co_primary_ids") or []
        policy = str(statistics.get("ablation_family_policy") or "")
        if (ids != ["no_gp", "no_memory", "no_edair"]
                or "exactly three co-primary" not in policy
                or "secondary paired effect estimates" not in policy
                or "no_multifidelity" not in policy
                or "runtime and compute cost" not in policy):
            raise ValueError("industrial DSE attainable ablation family is missing")
    if int(value.get("schema_version") or 0) >= 30:
        policy = value.get("optimization_policy") or {}
        edair = str(policy.get("edair_context_policy") or "")
        tools = str((value.get("execution") or {}).get(
            "l1_semantic_tool_policy") or "")
        if ("at most eight" not in edair or "no_edair ablation blocks" not in edair
                or "loss manifest" not in edair):
            raise ValueError("stateful L2 EDAIR boundary is missing")
        if ("No generic shell command" not in tools
                or "run_stage acknowledgement" not in tools
                or "protected Runtime" not in tools):
            raise ValueError("L1 semantic execution boundary is missing")
    if int(value.get("schema_version") or 0) >= 31:
        campaign = str((value.get("execution") or {}).get(
            "campaign_namespace_policy") or "")
        if ("Runner exclusively owns" not in campaign
                or "controller-logs" not in campaign
                or "cell manifest" not in campaign):
            raise ValueError("campaign and runner namespace ownership is missing")
    if int(value.get("schema_version") or 0) >= 32:
        binding = str((value.get("execution") or {}).get(
            "frozen_controller_binding_policy") or "")
        if ("Campaign and Runner independently recompute" not in binding
                or "reject execution" not in binding
                or "protocol binding" not in binding):
            raise ValueError("formal controller-source binding is missing")
    expected = _digest({key: item for key, item in value.items()
                        if key != "protocol_digest"})
    if value.get("protocol_digest") != expected:
        raise ValueError("industrial DSE protocol digest mismatch")


def write_frozen_protocol(path: str | Path, value: Mapping[str, Any]) -> Path:
    validate_industrial_dse_protocol(value)
    destination = Path(path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, indent=2, sort_keys=True) + "\n"
    if destination.exists() and destination.read_text(encoding="utf-8") != encoded:
        raise ValueError("refusing to overwrite a different frozen industrial protocol")
    if not destination.exists():
        destination.write_text(encoded, encoding="utf-8")
    return destination
