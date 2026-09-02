"""Evidence boundary with an explicitly lazy legacy research surface.

The product path imports this package for evidence readers and the protected
ORFS evaluator.  It must not import BO/GP, evolution, or other optional
research implementations merely as an import side effect.
"""

from __future__ import annotations

from importlib import import_module

from .common_evaluator import evaluate_orfs_run, write_immutable_evaluation
from .orfs_protected_evaluator import ORFSProtectedEvaluator


__all__ = ("evaluate_orfs_run", "write_immutable_evaluation", "ORFSProtectedEvaluator")

_LEGACY_MODULES = (
    "diagnosis", "pipeline", "reporter", "knowledge_base", "evolve_agent",
    "evidence_rag", "learning_data", "optimization", "optimizer_plugins",
    "iterative_agent", "lessons", "skills", "feedback_loop", "offline_policy",
    "open_knowledge", "learning_collector", "recommendations", "research_methods",
    "calibration", "design_ir", "runtime_ir", "design_suite", "replication",
    "causal_evidence", "causal_learning", "native_orfs_evidence",
    "verification_evidence", "edair", "circuitops_ir", "hypothesis_ledger",
    "closed_loop", "paper_harness", "optimization_memory", "state_tuning",
    "official_autotuner", "industrial_dse_protocol", "paper_statistics",
)


def __getattr__(name: str):
    """Resolve historical research exports only when a legacy caller asks."""
    for module_name in _LEGACY_MODULES:
        module = import_module(f"{__name__}.{module_name}")
        if hasattr(module, name):
            value = getattr(module, name)
            globals()[name] = value
            return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
