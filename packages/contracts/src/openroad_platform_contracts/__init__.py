"""Stable contracts shared by the platform control and execution planes."""

from .models import (
    Artifact,
    ArtifactKind,
    ExecutionPlan,
    Metric,
    RunRequest,
    RunResult,
    RunStage,
    RunStatus,
    StageResult,
)
from .platform import (
    SCHEMA_VERSION,
    ActionProposal,
    ExperimentCandidate,
    ExperimentPlan,
    Event,
    PluginManifest,
    PluginResult,
    RuntimeStatus,
    RepairAction,
    TaskSpec,
    TERMINAL_RUNTIME_STATUSES,
)
from .learning import (
    EvidencePointer,
    LearningContext,
    LearningObservation,
    MechanismEvidence,
    ObjectiveSpec,
    OptimizationStudy,
    OptimizerProposal,
    ParameterSpec,
    Prediction,
    ShadowPolicyProposal,
    TrajectoryStep,
)
from .experiment_graph import (
    ActionKind,
    ActionSpec,
    ExperimentEdge,
    ExperimentNode,
    ExperimentNodeKind,
)
from .rtl_frontend import PortSpec, RTLCandidate, SpecIR, VerificationPackage
from .agent_control import (
    AgentBudget,
    DesignGoal,
    DesignState,
    GoalPreference,
    QoRConstraint,
    READ_ONLY_TOOLS,
    SemanticToolCall,
    ToolName,
    ToolReceipt,
)
from .task_factory import (
    OPENROAD_KNOWLEDGE_CAPABILITY,
    KnowledgeQueryRequest,
    KnowledgeTaskFactory,
    RTL_TO_GDS_CAPABILITY,
    RTLToGDSFactory,
    RTLToGDSRequest,
)
from .protected_evaluation import ProtectedEvaluator
from .l2_optimization import OptimizationRequest, L2HandoffAuthorization
from .product_surface import (
    DEFAULT_PRODUCT_SURFACE, ProductCapabilityRule, ProductRole, ProductSurface,
)
from .diagnostics import (
    AnalysisCompleteness, AnalysisDomain, AnalysisTarget, DiagnosisReport,
    DiagnosticStatement, Headroom, MetricFact, StageAnalysis,
)
from .l1_control_state import (
    AnalyzerState, ConvergenceState, DebuggerState, PlannerPhase, PlannerState,
    RecoveryAction, RecoveryBudget, RecoveryClass,
)
from .artifact_index import (
    ArtifactEntityKind, ArtifactIndexEdge, ArtifactIndexNode,
    ArtifactRelation, CrossArtifactIndex,
)
from .convergence import (
    ConvergenceAssessment, ConvergencePolicy, MetricTrajectory,
    MetricTrajectoryPoint, ObjectiveDirection,
)
from .recovery import (
    RecoveryDecision, RollbackCheckpoint, RTLCheckpointRestorePlan,
    RuntimeFailureClass,
)
from .benchmark_evaluation import (
    DiagnosticDecision, PostEDADiagnosisPrediction, PostEDADiagnosisScore,
)

__all__ = [
    "Artifact",
    "ArtifactKind",
    "ExecutionPlan",
    "Metric",
    "RunRequest",
    "RunResult",
    "RunStage",
    "RunStatus",
    "StageResult",
    "SCHEMA_VERSION",
    "ActionProposal",
    "ExperimentCandidate",
    "ExperimentPlan",
    "Event",
    "PluginManifest",
    "PluginResult",
    "RuntimeStatus",
    "RepairAction",
    "TaskSpec",
    "TERMINAL_RUNTIME_STATUSES",
    "EvidencePointer",
    "LearningContext",
    "LearningObservation",
    "MechanismEvidence",
    "ObjectiveSpec",
    "OptimizationStudy",
    "OptimizerProposal",
    "ParameterSpec",
    "Prediction",
    "ShadowPolicyProposal",
    "TrajectoryStep",
    "ActionKind",
    "ActionSpec",
    "ExperimentEdge",
    "ExperimentNode",
    "ExperimentNodeKind",
    "PortSpec",
    "RTLCandidate",
    "SpecIR",
    "VerificationPackage",
    "AgentBudget",
    "DesignGoal",
    "DesignState",
    "GoalPreference",
    "QoRConstraint",
    "READ_ONLY_TOOLS",
    "SemanticToolCall",
    "ToolName",
    "ToolReceipt",
    "RTL_TO_GDS_CAPABILITY",
    "OPENROAD_KNOWLEDGE_CAPABILITY",
    "KnowledgeQueryRequest",
    "KnowledgeTaskFactory",
    "RTLToGDSFactory",
    "RTLToGDSRequest",
    "ProtectedEvaluator",
    "OptimizationRequest", "L2HandoffAuthorization",
    "DEFAULT_PRODUCT_SURFACE", "ProductCapabilityRule", "ProductRole", "ProductSurface",
    "AnalysisCompleteness", "AnalysisDomain", "AnalysisTarget",
    "DiagnosisReport", "DiagnosticStatement", "Headroom", "MetricFact",
    "StageAnalysis",
    "AnalyzerState", "ConvergenceState", "DebuggerState", "PlannerPhase",
    "PlannerState", "RecoveryAction", "RecoveryBudget", "RecoveryClass",
    "ArtifactEntityKind", "ArtifactIndexEdge", "ArtifactIndexNode",
    "ArtifactRelation", "CrossArtifactIndex",
    "ConvergenceAssessment", "ConvergencePolicy", "MetricTrajectory",
    "MetricTrajectoryPoint", "ObjectiveDirection",
    "RecoveryDecision", "RollbackCheckpoint", "RTLCheckpointRestorePlan",
    "RuntimeFailureClass",
    "DiagnosticDecision", "PostEDADiagnosisPrediction", "PostEDADiagnosisScore",
]
