"""Static dependency gates that keep product packages plugin-friendly."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOTS = {
    "contracts": ROOT / "packages/contracts/src/openroad_platform_contracts",
    "analysis": ROOT / "packages/analysis/src/openroad_platform_analysis",
    "execution": ROOT / "packages/execution/src/openroad_platform_execution",
    "scheduler": ROOT / "packages/scheduler/src/openroad_platform_scheduler",
    "visualization": ROOT / "packages/visualization/src/openroad_platform_visualization",
}
FORBIDDEN_PREFIXES = {
    "contracts": ("openroad_platform_analysis", "openroad_platform_execution",
                  "openroad_platform_scheduler", "apps"),
    "analysis": ("openroad_platform_execution", "openroad_platform_scheduler", "apps"),
    # Infrastructure may call the inward, data-only analysis policy to emit
    # immutable reports.  Broader Scheduler/Runtime ownership is migrated in a
    # later slice; this static gate continues to protect the established
    # package-level acyclic direction only.
    "execution": ("openroad_platform_scheduler", "apps"),
    "scheduler": ("openroad_platform_analysis", "apps"),
    "visualization": ("openroad_platform_analysis", "openroad_platform_execution",
                      "openroad_platform_scheduler", "apps"),
}


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.add(node.module)
    return result


def test_packages_do_not_reverse_control_plane_dependency_direction():
    violations = []
    for package, root in PACKAGE_ROOTS.items():
        for path in sorted(root.rglob("*.py")):
            for imported in _imports(path):
                if any(imported == prefix or imported.startswith(prefix + ".")
                       for prefix in FORBIDDEN_PREFIXES[package]):
                    violations.append({
                        "package": package, "path": str(path.relative_to(ROOT)),
                        "forbidden_import": imported,
                    })
    assert violations == []


def test_slice_one_scheduler_task_paths_do_not_import_concrete_execution():
    """Slice 1 is intentionally narrow: task construction, not all Runtime IO."""
    paths = (
        PACKAGE_ROOTS["scheduler"] / "nl_control.py",
        PACKAGE_ROOTS["scheduler"] / "composition.py",
        PACKAGE_ROOTS["scheduler"] / "l1_orfs_service.py",
    )
    violations = []
    for path in paths:
        for imported in _imports(path):
            if (imported == "openroad_platform_execution"
                    or imported.startswith("openroad_platform_execution.")):
                violations.append({
                    "path": str(path.relative_to(ROOT)),
                    "forbidden_import": imported,
                })
    assert violations == []


def test_api_services_do_not_own_external_optimizer_orchestration():
    """The API composes Scheduler services but must not define their lifecycle.

    Keeping this check structural prevents a future external optimiser adapter
    from placing campaign state transitions back in the HTTP service layer.
    """
    api_services = ROOT / "apps/api/services"
    misplaced = sorted(path.relative_to(ROOT) for path in api_services.glob("*l2*.py"))
    assert misplaced == []
