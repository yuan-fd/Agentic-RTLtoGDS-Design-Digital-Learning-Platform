"""Execution-plane primitives for isolated EDA runs."""

from .adapter import AdapterExecution, ProcessAdapter
from .orfs_runner import ORFSRunner
from .orfs_generated_design import (
    generated_design_from_platform_plan, generated_design_from_reference_design,
    install_generated_design_adapter, validate_generated_design_adapter,
)
from .orfs_reference_designs import (
    ORFS_AGENT_PAPER_ORFS_COMMIT, ORFSReferenceDesign,
    load_orfs_agent_paper_reference_design, load_orfs_reference_design,
)
from .orfs_plugin import (
    ORFS_PLUGIN_ID,
    ORFS_PLUGIN_VERSION,
    build_orfs_task,
    orfs_plugin_manifest,
)
from .orfs_task_factory import ORFSRTLToGDSFactory
from .orfs_agent_plugin import (
    ORFS_AGENT_PLUGIN_ID, ORFS_AGENT_PLUGIN_VERSION, ORFS_AGENT_UPSTREAM_COMMIT,
    build_orfs_agent_initial_warmup_recipes,
    orfs_agent_full_protocol_receipts, orfs_agent_plugin_manifest,
)
from .orfs_agent_domain import ORFSAgentDomain, ORFSAgentFullDomain
from .a2_orfo_plugin import (
    A2_ORFO_MODEL_COMMIT, A2_ORFO_OBJECTIVES, A2_ORFO_PARAMETERS,
    A2_ORFO_PLUGIN_ID, A2_ORFO_PLUGIN_VERSION, A2_ORFO_UPSTREAM_COMMIT,
    A2ORFODomain, a2_orfo_plugin_manifest, build_a2_orfo_initialization_task,
    build_a2_orfo_policy_task,
)
from .orassistant_plugin import (
    ORAssistantKnowledgeTaskFactory,
    ORASSISTANT_CAPABILITY, ORASSISTANT_CORPUS_ID, ORASSISTANT_PLUGIN_ID,
    ORASSISTANT_PLUGIN_VERSION, build_orassistant_task,
    orassistant_plugin_manifest,
)
from .posteda_bench_plugin import (
    POSTEDA_ADMITTED_TASKS, POSTEDA_BENCH_EVALUATE_CAPABILITY,
    POSTEDA_BENCH_ID, POSTEDA_BENCH_PLUGIN_ID, POSTEDA_BENCH_PLUGIN_VERSION,
    POSTEDA_BENCH_PUBLIC_CAPABILITY, POSTEDA_BENCH_UPSTREAM_COMMIT,
    build_posteda_evaluation_task, build_posteda_public_case_task,
    posteda_bench_plugin_manifest,
)
from .orfs_agent_task import (
    build_orfs_agent_dataset_task, build_orfs_agent_native_task,
    build_orfs_agent_full_policy_task, build_orfs_agent_full_initialization_task,
    build_orfs_agent_full_candidate_task,
)
from .orfs_agent_reproduction_plugin import (
    ORFS_AGENT_REPRODUCTION_PLUGIN_ID, ORFS_AGENT_REPRODUCTION_VERSION,
    ORFS_AGENT_COMMIT as ORFS_AGENT_REPRODUCTION_UPSTREAM_COMMIT,
    ORFS_PAPER_COMMIT as ORFS_AGENT_REPRODUCTION_ORFS_COMMIT,
    UPSTREAM_PARAMETERS as ORFS_AGENT_REPRODUCTION_PARAMETERS,
    build_orfs_agent_reproduction_task, orfs_agent_reproduction_manifest,
)
from .seeded_random_control_plugin import (
    SEEDED_RANDOM_CONTROL_PLUGIN_ID, SEEDED_RANDOM_CONTROL_PLUGIN_VERSION,
    build_seeded_random_control_task, seeded_random_control_plugin_manifest,
)
from .orfs_parameters import (
    ORFS_PARAMETERS, apply_parameter_calibration, apply_parameter_search_allowlist,
    effective_configuration_id, official_autotuner_common_parameter_names,
    official_autotuner_independent_parameter_names,
    orfs_optimization_profile,
    orfs_parameter_schema, validate_orfs_parameters,
)
from .process_guardian import ProcessGuardian, ProcessOutcome
from .registry import PluginRegistry
from .toolchain import ToolchainCatalog, ToolchainConfig, load_toolchain
from .pinned_toolchain import validate_pinned_orfs_toolchain
from .rtlscout_plugin import (
    RTLSCOUT_PLUGIN_ID,
    RTLSCOUT_PLUGIN_VERSION,
    RTLSCOUT_UPSTREAM_COMMIT,
    build_rtlscout_task,
    build_rtlscout_spec_task,
    rtlscout_plugin_manifest,
)
from .rtl_verify_plugin import (
    RTL_VERIFY_PLUGIN_ID, RTL_VERIFY_PLUGIN_VERSION, build_rtl_verify_task,
    rtl_verify_plugin_manifest,
)
from .rtl_sim_plugin import (
    RTL_SIM_PLUGIN_ID, RTL_SIM_PLUGIN_VERSION, build_rtl_sim_task,
    rtl_sim_plugin_manifest,
)
from .rtl_mutation_plugin import (
    RTL_MUTATION_PLUGIN_ID, RTL_MUTATION_PLUGIN_VERSION, build_rtl_mutation_task,
    rtl_mutation_plugin_manifest,
)
from .rtl_formal_plugin import RTL_FORMAL_PLUGIN_ID, RTL_FORMAL_PLUGIN_VERSION, build_rtl_formal_task, rtl_formal_plugin_manifest
from .agenticpd_plugin import (
    AGENTICPD_PLUGIN_ID, AGENTICPD_PLUGIN_VERSION, AGENTICPD_UPSTREAM_COMMIT,
    agenticpd_plugin_manifest, build_agenticpd_task,
)
from .taiwei_plugin import (
    TAIWEI_3D_PLATFORMS, TAIWEI_OFFICIAL_CASES, TAIWEI_OPENROAD_COMMIT,
    TAIWEI_ORFS_COMMIT, TAIWEI_PLUGIN_ID,
    TAIWEI_PLUGIN_VERSION, TAIWEI_UPSTREAM_COMMIT, TaiWeiToolchainProfile,
    build_taiwei_task, taiwei_plugin_manifest, taiwei_technology_profiles,
)
from .implcraft_plugin import (
    IMPLCRAFT_PLUGIN_ID, IMPLCRAFT_PLUGIN_VERSION, IMPLCRAFT_UPSTREAM_COMMIT,
    build_implcraft_task, implcraft_plugin_manifest,
)
from .dplevolve_plugin import (
    DPLEVOLVE_LICENSE, DPLEVOLVE_PLUGIN_ID, DPLEVOLVE_PLUGIN_VERSION,
    DPLEVOLVE_UPSTREAM_COMMIT, build_dplevolve_audit_task,
    dplevolve_plugin_manifest, source_tree_digest,
)
from .coding_agent import (
    CandidateEvaluation, IsolatedCodingAgent, PatchProposal, PromotionGate,
    VerificationPolicy,
)
from .protected_whitebox import (
    ProtectedWhiteBoxEvaluation,
    ProtectedWhiteBoxEvaluator,
    ProtectedWhiteBoxPromotionGate,
    WhiteBoxPolicy,
)
from .craft_flow import (
    BackendNeutralFlowPlan, build_craft_flow_plan, craft_capability_matrix,
    craft_plan_to_task,
)
from .edacraft_extension import (
    EDACRAFT_COMPONENTS, EDACRAFT_PLUGIN_VERSION, EDACRAFT_UPSTREAM_COMMIT,
    EDACraftComponent, build_edacraft_task, edacraft_catalog,
    edacraft_component, edacraft_plugin_manifest,
)

__all__ = [
    "AdapterExecution", "ProcessAdapter", "ORFSRunner", "ProcessGuardian",
    "generated_design_from_platform_plan", "generated_design_from_reference_design",
    "install_generated_design_adapter",
    "validate_generated_design_adapter",
    "ORFSReferenceDesign", "load_orfs_reference_design",
    "ORFS_AGENT_PAPER_ORFS_COMMIT", "load_orfs_agent_paper_reference_design",
    "ProcessOutcome", "PluginRegistry", "ORFS_PLUGIN_ID", "ORFS_PLUGIN_VERSION",
    "build_orfs_task", "orfs_plugin_manifest", "ToolchainCatalog",
    "ORFSRTLToGDSFactory",
    "ORFS_AGENT_PLUGIN_ID", "ORFS_AGENT_PLUGIN_VERSION", "ORFS_AGENT_UPSTREAM_COMMIT",
    "build_orfs_agent_dataset_task", "build_orfs_agent_native_task",
    "build_orfs_agent_full_policy_task", "ORFSAgentDomain", "ORFSAgentFullDomain",
    "build_orfs_agent_full_initialization_task", "build_orfs_agent_full_candidate_task",
    "build_orfs_agent_initial_warmup_recipes",
    "orfs_agent_plugin_manifest",
    "orfs_agent_full_protocol_receipts",
    "A2_ORFO_MODEL_COMMIT", "A2_ORFO_OBJECTIVES", "A2_ORFO_PARAMETERS",
    "A2_ORFO_PLUGIN_ID", "A2_ORFO_PLUGIN_VERSION", "A2_ORFO_UPSTREAM_COMMIT",
    "A2ORFODomain", "a2_orfo_plugin_manifest", "build_a2_orfo_policy_task",
    "build_a2_orfo_initialization_task",
    "ORASSISTANT_CAPABILITY", "ORASSISTANT_CORPUS_ID", "ORASSISTANT_PLUGIN_ID",
    "ORAssistantKnowledgeTaskFactory",
    "ORASSISTANT_PLUGIN_VERSION", "build_orassistant_task",
    "orassistant_plugin_manifest",
    "POSTEDA_ADMITTED_TASKS", "POSTEDA_BENCH_EVALUATE_CAPABILITY",
    "POSTEDA_BENCH_ID", "POSTEDA_BENCH_PLUGIN_ID", "POSTEDA_BENCH_PLUGIN_VERSION",
    "POSTEDA_BENCH_PUBLIC_CAPABILITY", "POSTEDA_BENCH_UPSTREAM_COMMIT",
    "build_posteda_evaluation_task", "build_posteda_public_case_task",
    "posteda_bench_plugin_manifest",
    "ORFS_AGENT_REPRODUCTION_PLUGIN_ID", "ORFS_AGENT_REPRODUCTION_VERSION",
    "ORFS_AGENT_REPRODUCTION_UPSTREAM_COMMIT", "ORFS_AGENT_REPRODUCTION_ORFS_COMMIT",
    "ORFS_AGENT_REPRODUCTION_PARAMETERS", "build_orfs_agent_reproduction_task",
    "orfs_agent_reproduction_manifest",
    "SEEDED_RANDOM_CONTROL_PLUGIN_ID", "SEEDED_RANDOM_CONTROL_PLUGIN_VERSION",
    "build_seeded_random_control_task", "seeded_random_control_plugin_manifest",
    "ORFS_PARAMETERS", "apply_parameter_calibration", "apply_parameter_search_allowlist",
    "effective_configuration_id", "official_autotuner_common_parameter_names",
    "official_autotuner_independent_parameter_names",
    "orfs_optimization_profile",
    "orfs_parameter_schema", "validate_orfs_parameters",
    "ToolchainConfig", "load_toolchain", "validate_pinned_orfs_toolchain",
    "RTLSCOUT_PLUGIN_ID", "RTLSCOUT_PLUGIN_VERSION", "RTLSCOUT_UPSTREAM_COMMIT",
    "build_rtlscout_task", "build_rtlscout_spec_task", "rtlscout_plugin_manifest",
    "RTL_VERIFY_PLUGIN_ID", "RTL_VERIFY_PLUGIN_VERSION", "build_rtl_verify_task",
    "rtl_verify_plugin_manifest",
    "RTL_SIM_PLUGIN_ID", "RTL_SIM_PLUGIN_VERSION", "build_rtl_sim_task",
    "rtl_sim_plugin_manifest",
    "RTL_MUTATION_PLUGIN_ID", "RTL_MUTATION_PLUGIN_VERSION", "build_rtl_mutation_task",
    "rtl_mutation_plugin_manifest",
    "RTL_FORMAL_PLUGIN_ID", "RTL_FORMAL_PLUGIN_VERSION", "build_rtl_formal_task", "rtl_formal_plugin_manifest",
    "AGENTICPD_PLUGIN_ID", "AGENTICPD_PLUGIN_VERSION", "AGENTICPD_UPSTREAM_COMMIT",
    "agenticpd_plugin_manifest", "build_agenticpd_task",
    "TAIWEI_3D_PLATFORMS", "TAIWEI_OFFICIAL_CASES", "TAIWEI_OPENROAD_COMMIT",
    "TAIWEI_ORFS_COMMIT", "TAIWEI_PLUGIN_ID",
    "TAIWEI_PLUGIN_VERSION", "TAIWEI_UPSTREAM_COMMIT", "TaiWeiToolchainProfile",
    "build_taiwei_task", "taiwei_plugin_manifest", "taiwei_technology_profiles",
    "IMPLCRAFT_PLUGIN_ID", "IMPLCRAFT_PLUGIN_VERSION", "IMPLCRAFT_UPSTREAM_COMMIT",
    "build_implcraft_task", "implcraft_plugin_manifest",
    "DPLEVOLVE_LICENSE", "DPLEVOLVE_PLUGIN_ID", "DPLEVOLVE_PLUGIN_VERSION",
    "DPLEVOLVE_UPSTREAM_COMMIT", "build_dplevolve_audit_task",
    "dplevolve_plugin_manifest", "source_tree_digest",
    "CandidateEvaluation", "IsolatedCodingAgent", "PatchProposal", "PromotionGate",
    "VerificationPolicy",
    "ProtectedWhiteBoxEvaluation", "ProtectedWhiteBoxEvaluator",
    "ProtectedWhiteBoxPromotionGate", "WhiteBoxPolicy",
    "BackendNeutralFlowPlan", "build_craft_flow_plan", "craft_capability_matrix",
    "craft_plan_to_task",
    "EDACRAFT_COMPONENTS", "EDACRAFT_PLUGIN_VERSION", "EDACRAFT_UPSTREAM_COMMIT",
    "EDACraftComponent", "build_edacraft_task", "edacraft_catalog",
    "edacraft_component", "edacraft_plugin_manifest",
]
