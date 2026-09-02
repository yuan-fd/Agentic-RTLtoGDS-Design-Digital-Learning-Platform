from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_protected_evaluator_import_needs_no_optional_research_stack():
    code = (
        "import sys; "
        f"sys.path.insert(0, {str(ROOT / 'packages/contracts/src')!r}); "
        f"sys.path.insert(0, {str(ROOT / 'packages/analysis/src')!r}); "
        "from openroad_platform_analysis import ORFSProtectedEvaluator; "
        "assert ORFSProtectedEvaluator.__name__ == 'ORFSProtectedEvaluator'"
    )
    completed = subprocess.run(
        [sys.executable, "-I", "-c", code], text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    assert completed.returncode == 0, completed.stderr
