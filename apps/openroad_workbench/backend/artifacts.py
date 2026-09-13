from __future__ import annotations

"""Artifact discovery.

The user's stated pain point was: "怎么找各类结果 怎么找可视化报告 我们统一存放
路径 而不是让用户自己查路径".  So the workbench indexes what ORFS actually
produces instead of inventing a parallel directory convention.

Layout understood (OpenROAD-flow-scripts):

    <design>/results/<platform>/<design>/<variant>/<N_stage>/...
    <design>/logs/<platform>/<design>/<variant>/<N_stage>/...

and the usual suspects ``reports/``, ``images/``, ``scripts/``, ``src/``.

Classification is by extension *and* path, and the stage is taken from the ORFS
numbered directory when present, otherwise from the filename.
"""

import os
import re
from typing import Dict, Iterable, List, Optional

from .models import Artifact, STAGE_ORDER

IMAGE_EXT = {".png", ".webp", ".jpg", ".jpeg", ".svg", ".gif", ".bmp", ".tif", ".tiff"}
REPORT_EXT = {".rpt", ".report", ".md", ".csv", ".json"}
LOG_EXT = {".log"}
DATA_EXT = {".def", ".lef", ".gds", ".gdsii", ".v", ".sv", ".spef", ".sdc", ".lib", ".odb", ".db", ".sdf", ".vcd"}
SCRIPT_EXT = {".tcl", ".py", ".sh", ".mk", ".makefile"}

STAGE_DIR_RE = re.compile(r"^\d+[_\-]?([a-z]+)$", re.I)
STAGE_NAME_RE = re.compile(r"\b(synth|floorplan|place|cts|grt|route|finish)\b", re.I)

SKIP_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv", "env",
    ".mypy_cache", ".pytest_cache", "objects", "3d", ".cache",
}
MAX_FILES = 4000
MAX_DEPTH = 7


def _stage_from_path(rel: str) -> Optional[str]:
    for part in rel.split(os.sep):
        match = STAGE_DIR_RE.match(part)
        if match:
            name = match.group(1).lower()
            if name in STAGE_ORDER:
                return name
    for part in rel.split(os.sep):
        low = part.lower()
        for stage in STAGE_ORDER:
            if low.startswith(stage) or low == stage:
                return stage
    return None


def classify(rel: str, name: str) -> str:
    ext = os.path.splitext(name)[1].lower()
    low_rel = rel.lower()
    if ext in IMAGE_EXT:
        return "image"
    if ext in LOG_EXT or "/logs/" in "/" + low_rel:
        return "log"
    if name in ("metrics.json", "rules-base.json", "metadata-base-ok.json") or name.endswith(".metrics.json"):
        return "metric"
    if ext in SCRIPT_EXT or "/scripts/" in "/" + low_rel:
        return "script"
    if ext in DATA_EXT:
        return "data"
    if ext in REPORT_EXT or "/reports/" in "/" + low_rel:
        return "report"
    return "other"


def scan_design(design_id: str, root: str, limit: int = MAX_FILES) -> List[Artifact]:
    """Walk a design directory and return the artifacts worth surfacing."""
    results: List[Artifact] = []
    root = os.path.abspath(root)
    if not os.path.isdir(root):
        return results
    count = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames
            if d not in SKIP_DIRS and not d.startswith(".") and not d.endswith(".egg-info")
        ]
        rel_dir = os.path.relpath(dirpath, root)
        depth = 0 if rel_dir == "." else rel_dir.count(os.sep) + 1
        if depth > MAX_DEPTH:
            dirnames[:] = []
            continue
        for filename in filenames:
            if filename.startswith("."):
                continue
            full = os.path.join(dirpath, filename)
            rel = os.path.relpath(full, root)
            try:
                stat = os.stat(full)
            except OSError:
                continue
            kind = classify(rel, filename)
            results.append(
                Artifact(
                    id="art-%d" % (len(results) + 1),
                    design_id=design_id,
                    path=full,
                    kind=kind,
                    stage=_stage_from_path(rel),
                    size=stat.st_size,
                    mtime=stat.st_mtime,
                )
            )
            count += 1
            if count >= limit:
                return _sorted(results)
    return _sorted(results)


def _sorted(artifacts: Iterable[Artifact]) -> List[Artifact]:
    order = {"image": 0, "report": 1, "metric": 2, "log": 3, "data": 4, "script": 5, "other": 6}
    items = sorted(
        artifacts,
        key=lambda a: (order.get(a.kind, 9), -(a.mtime or 0)),
    )
    for index, item in enumerate(items, start=1):
        item.id = "art-%d" % index
    return items


def looks_like_design(path: str) -> bool:
    """Heuristic gate used before auto-registering a directory as a design."""
    if not os.path.isdir(path):
        return False
    try:
        entries = set(os.listdir(path))
    except OSError:
        return False
    markers = {"config.mk", "constraint.sdc", "Makefile", "flow", "designs", "src", "scripts", "lef", "def"}
    if not (entries & markers):
        return False
    orfs_markers = {"results", "logs", "reports", "objects"}
    return bool(entries & orfs_markers) or bool(entries & {"config.mk", "constraint.sdc"})


def summarize(artifacts: List[Artifact]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for artifact in artifacts:
        counts[artifact.kind] = counts.get(artifact.kind, 0) + 1
    return counts
