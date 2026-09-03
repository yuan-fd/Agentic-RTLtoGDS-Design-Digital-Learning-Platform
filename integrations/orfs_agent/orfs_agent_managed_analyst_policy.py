"""Typed managed-model boundary for the ORFS-Agent analyst role.

This module deliberately contains no EDA execution or numerical optimisation.
The managed model may select a subset of already measured 12-D observations;
the pinned upstream ORFS-Agent workbench remains the sole generator of GP/EI
numeric candidates.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence


ORFS_AGENT_PARAMETERS = (
    "CLK", "UTIL", "TNS_End_Percent", "GP_PAD", "DP_PAD", "DPO",
    "PIN_ADJ", "UP_ADJ", "LB_ADDON", "HIER_SYNTH", "CTS_CSIZE", "CTS_CDIA",
)


def _write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")


def select_training_rows(rows: Sequence[Mapping[str, Any]], *, objective: str,
                         suggestions: int) -> dict[str, Any]:
    """Ask the managed analyst for row ids only, never numeric candidates.

    ``ORFS_AGENT_CODEX_EXECUTABLE`` is set by the admitted plugin environment,
    rather than by a browser task.  The subprocess receives a read-only
    sandbox and a compact, evidence-backed observation table.
    """
    executable = os.environ.get("ORFS_AGENT_CODEX_EXECUTABLE")
    if not executable or not Path(executable).is_file():
        raise ValueError("ORFS-Agent paper policy requires the managed Codex executable")
    if len(rows) < 2:
        raise ValueError("ORFS-Agent paper policy needs at least two measured rows")
    compact = [
        {
            "row_id": index,
            "objective": row.get(objective),
            "drc": row.get("detailedroute__route__drc_errors"),
            "parameters": {key: row.get(key) for key in ORFS_AGENT_PARAMETERS},
        }
        for index, row in enumerate(rows)
    ]
    schema = {
        "type": "object", "additionalProperties": False,
        "required": ["training_row_ids", "rationale", "uncertainty"],
        "properties": {
            "training_row_ids": {
                "type": "array", "minItems": 2, "maxItems": len(compact),
                "items": {"type": "integer", "minimum": 0, "maximum": len(compact) - 1},
            },
            "rationale": {"type": "string", "maxLength": 2000},
            "uncertainty": {"type": "string", "maxLength": 1200},
        },
    }
    prompt = (
        "You are the analyst-policy component of the published ORFS-Agent L2 optimizer. "
        "Select at least two measured row_id values that form a defensible training subset for "
        "the upstream GP/EI optimizer. Favor DRC-clean rows and a useful mix of strong and "
        "boundary observations. Do not invent metrics or parameters; do not propose numeric "
        "candidates, shell commands, source edits, or claims of improvement. Return only JSON "
        "matching the supplied schema.\n\n"
        f"OBJECTIVE_TO_MINIMIZE={objective}\nREQUESTED_SUGGESTIONS={suggestions}\n"
        f"MEASURED_ROWS={json.dumps(compact, ensure_ascii=False)}"
    )
    launcher = Path(executable).expanduser()
    launcher_dir = launcher.parent.absolute()
    node = launcher_dir / "node"
    environment = {
        key: os.environ[key]
        for key in ("HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "TZ", "CODEX_HOME")
        if key in os.environ
    }
    inherited_path = os.environ.get("PATH", os.defpath)
    environment["PATH"] = (
        f"{launcher_dir}{os.pathsep}{inherited_path}"
        if node.is_file() and os.access(node, os.X_OK) else inherited_path
    )
    with tempfile.TemporaryDirectory(prefix="orfs-agent-paper-policy-") as raw:
        root = Path(raw)
        schema_path, output_path = root / "schema.json", root / "policy.json"
        _write(schema_path, schema)
        completed = subprocess.run(
            [executable, "exec", "--ephemeral", "--ignore-rules", "--skip-git-repo-check",
             "--sandbox", "read-only", "--model", "gpt-5.6-terra", "--output-schema",
             str(schema_path), "--output-last-message", str(output_path), "--color", "never", "-"],
            input=prompt, cwd=root, env=environment, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, timeout=180, check=False,
        )
        if completed.returncode != 0 or not output_path.is_file():
            detail = "\n".join((completed.stderr or completed.stdout).splitlines()[-10:])
            raise RuntimeError(detail or "managed ORFS-Agent analyst returned no policy")
        policy = json.loads(output_path.read_text(encoding="utf-8"))
    ids = policy.get("training_row_ids") if isinstance(policy, Mapping) else None
    if (not isinstance(ids, list) or len(ids) < 2
            or any(not isinstance(item, int) or item < 0 or item >= len(rows) for item in ids)):
        raise ValueError("managed ORFS-Agent analyst returned invalid training row ids")
    unique_ids = list(dict.fromkeys(ids))
    if len(unique_ids) < 2:
        raise ValueError("managed ORFS-Agent analyst returned fewer than two distinct rows")
    return {**policy, "training_row_ids": unique_ids}
