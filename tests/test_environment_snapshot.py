import sys

from openroad_platform_analysis.environment_snapshot import (
    combined_python_environment, current_python_environment,
    external_python_environment,
)


def test_python_environment_snapshots_are_deterministic_and_versioned():
    current = current_python_environment(("pytest", "definitely-absent-package"))
    assert current == current_python_environment(("pytest", "definitely-absent-package"))
    assert current["distributions"]["pytest"] is not None
    assert current["distributions"]["definitely-absent-package"] is None
    external = external_python_environment(
        sys.executable, ("pytest", "definitely-absent-package"))
    assert external["distributions"] == current["distributions"]
    combined = combined_python_environment(controller=current, external=external)
    assert len(combined["fingerprint"]) == 64
    assert combined["controller"]["fingerprint"] == current["fingerprint"]
