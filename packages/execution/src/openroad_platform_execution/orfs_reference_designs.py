"""Pinned source-bundle recipes for the v2 industrial DSE study.

Recipes identify source bytes and elaboration requirements.  Optimizer logic
is deliberately absent: every optimizer receives the same resulting
``RunRequest`` apart from its calibrated flow-parameter vector and seed.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from openroad_platform_contracts import RunRequest, RunStage


@dataclass(frozen=True)
class ORFSReferenceDesign:
    platform: str
    design: str
    top: str
    clock: str
    clock_period_ns: float
    rtl_root: Path
    rtl_files: tuple[Path, ...]
    include_dirs: tuple[Path, ...]
    sdc_path: Path
    synth_hdl_frontend: str | None
    design_options: Mapping[str, Any]
    native_baseline_overrides: Mapping[str, Any]
    source_fingerprint: str
    orfs_commit: str
    fast_route_tcl_path: Path | None = None

    def request(self, *, flow_parameters: Mapping[str, Any], or_seed: int,
                target_stage: RunStage = RunStage.FINISH,
                run_id: str, stage_timeout_seconds: int = 7200) -> RunRequest:
        parameters = dict(flow_parameters)
        place_density = float(parameters.pop(
            "place_density", self.native_baseline_overrides.get("place_density", .55)))
        return RunRequest(
            rtl_path=str(next(path for path in self.rtl_files if path.stem == self.top)),
            rtl_files=tuple(str(path) for path in self.rtl_files),
            rtl_root=str(self.rtl_root),
            rtl_include_dirs=tuple(str(path) for path in self.include_dirs),
            synth_hdl_frontend=self.synth_hdl_frontend,
            design_options=dict(self.design_options),
            sdc_path=str(self.sdc_path),
            top=self.top, clock=self.clock, clock_period_ns=self.clock_period_ns,
            platform=self.platform, target_stage=target_stage,
            core_utilization_pct=float(flow_parameters.get(
                "core_utilization_pct", self.native_baseline_overrides["core_utilization_pct"])),
            place_density=place_density,
            flow_parameters=parameters, or_seed=or_seed,
            stage_timeout_seconds=stage_timeout_seconds, run_id=run_id,
            labels={
                "reference_design": self.design,
                "design_bundle_sha256": self.source_fingerprint,
                "orfs_commit": self.orfs_commit,
            },
        )


DEFINITIONS = {
    ("asap7", "aes"): {
        "root": "aes", "top": "aes_cipher_top", "clock": "clk",
        # ASAP7's Liberty/SDC unit is ps.  Public contracts and EDAIR are ns;
        # the source SDC remains byte-identical and therefore still contains
        # the official raw value 380 ps.
        "sdc": "constraint.sdc", "period": 0.380,
        "baseline": {"core_utilization_pct": 70, "place_density": .65,
                     "tns_end_percent": 100},
    },
    ("sky130hd", "aes"): {
        "root": "aes", "top": "aes_cipher_top", "clock": "clk",
        "sdc": "constraint.sdc", "period": 3.6,
        "options": {"remove_abc_buffers": 1, "swap_arith_operators": 1,
                    "openroad_hierarchical": 1},
        "baseline": {"core_utilization_pct": 35, "place_density_lb_addon": .2,
                     "tns_end_percent": 100},
    },
    ("asap7", "jpeg"): {
        "root": "jpeg", "top": "jpeg_encoder", "clock": "clk",
        "sdc": "jpeg_encoder15_7nm.sdc", "period": 0.680, "include": "include",
        "baseline": {"core_utilization_pct": 70, "place_density": .75,
                     "tns_end_percent": 100},
    },
    ("sky130hd", "jpeg"): {
        "root": "jpeg", "top": "jpeg_encoder", "clock": "clk",
        "sdc": "constraint.sdc", "period": 5.0, "include": "include",
        "options": {"remove_abc_buffers": 1},
        "baseline": {"core_utilization_pct": 55, "place_density_lb_addon": .15,
                     "tns_end_percent": 100},
    },
    ("asap7", "ibex"): {
        "root": "ibex_sv", "top": "ibex_core", "clock": "clk_i",
        # ORFS ships this explicit, reviewable variant because its default
        # 1000 ns constraint is not signoff-feasible on the pinned flow. Every
        # optimizer arm receives these same bytes; the clock is never tuned.
        "sdc": "constraint_pos_slack.sdc", "period": 1.468,
        "include": "vendor/lowrisc_ip/prim/rtl", "frontend": "slang",
        "extra": "syn/rtl/prim_clock_gating.v",
        "options": {"swap_arith_operators": 1, "openroad_hierarchical": 1},
        "baseline": {"core_utilization_pct": 40, "place_density_lb_addon": .2,
                     "enable_dpo": 0, "tns_end_percent": 100},
    },
    ("sky130hd", "ibex"): {
        "root": "ibex_sv", "top": "ibex_core", "clock": "clk_i",
        "sdc": "constraint.sdc", "period": 10.0,
        "include": "vendor/lowrisc_ip/prim/rtl", "frontend": "slang",
        "extra": "syn/rtl/prim_clock_gating.v",
        "options": {"remove_abc_buffers": 1, "swap_arith_operators": 1,
                    "openroad_hierarchical": 1},
        "baseline": {"core_utilization_pct": 50, "place_density_lb_addon": .25,
                     "tns_end_percent": 100},
    },
}


ORFS_AGENT_PAPER_ORFS_COMMIT = "ce8d36a7fef0ab9c47d183bcf078bce0f60f5a54"
ORFS_AGENT_PAPER_AES_SKY130HD = {
    "root": "aes", "top": "aes_cipher_top", "clock": "clk",
    "sdc": "constraint.sdc", "period": 4.5,
    "fast_route": "fastroute.tcl",
    "options": {"remove_abc_buffers": 1},
    "baseline": {"core_utilization_pct": 20, "place_density": .6,
                 "tns_end_percent": 100},
}


def load_orfs_reference_design(orfs_root: str | Path, *, platform: str,
                               design: str) -> ORFSReferenceDesign:
    root = Path(orfs_root).expanduser().resolve()
    definition = DEFINITIONS.get((platform, design))
    if definition is None:
        raise ValueError(f"unregistered v2 reference design: {platform}/{design}")
    return _load_reference_design(root, platform=platform, design=design,
                                  definition=definition,
                                  recipe_id="orfs-current-reference-v1")


def load_orfs_agent_paper_reference_design(
    orfs_root: str | Path, *, platform: str = "sky130hd", design: str = "aes",
) -> ORFSReferenceDesign:
    """Load the exact fixed-clock reference used before L2 variable-clock DSE.

    This is deliberately a separate recipe from the current ORFS
    Sky130HD/AES definition, whose SDC is 3.6 ns.  Accepting the current recipe
    here would make the L1 evidence/design handoff ambiguous.
    """
    if (platform, design) != ("sky130hd", "aes"):
        raise ValueError("ORFS-Agent paper reference is only sky130hd/aes")
    root = Path(orfs_root).expanduser().resolve()
    commit = _git_output(root, "rev-parse", "HEAD")
    if commit != ORFS_AGENT_PAPER_ORFS_COMMIT:
        raise ValueError(
            "ORFS-Agent paper reference requires ORFS commit "
            f"{ORFS_AGENT_PAPER_ORFS_COMMIT}; observed {commit or 'unknown'}"
        )
    dirty = _git_output(root, "status", "--porcelain", "--untracked-files=all")
    if dirty:
        raise ValueError("ORFS-Agent paper reference requires a clean detached checkout")
    return _load_reference_design(
        root, platform=platform, design=design,
        definition=ORFS_AGENT_PAPER_AES_SKY130HD,
        recipe_id="orfs-agent-paper-aes-sky130hd-v1",
        expected_commit=ORFS_AGENT_PAPER_ORFS_COMMIT,
    )


def _load_reference_design(
    root: Path, *, platform: str, design: str, definition: Mapping[str, Any],
    recipe_id: str, expected_commit: str | None = None,
) -> ORFSReferenceDesign:
    source_root = root / "flow/designs/src" / definition["root"]
    suffix = "*.sv" if definition.get("frontend") == "slang" else "*.v"
    files = tuple(sorted(source_root.glob(suffix)))
    if definition.get("extra"):
        files += (source_root / definition["extra"],)
    include_dirs = ((source_root / definition["include"],)
                    if definition.get("include") else ())
    sdc = root / "flow/designs" / platform / design / definition["sdc"]
    fast_route = (root / "flow/designs" / platform / design /
                  definition["fast_route"] if definition.get("fast_route") else None)
    required = (*files, *include_dirs, sdc, *((fast_route,) if fast_route else ()))
    if not files or any(not path.exists() for path in required):
        raise FileNotFoundError(f"incomplete ORFS reference bundle: {platform}/{design}")
    if not any(path.stem == definition["top"] for path in files):
        raise ValueError(f"top source is absent from ORFS bundle: {definition['top']}")
    records = []
    for path in files:
        records.append((str(path.relative_to(root)), _sha256(path)))
    for directory in include_dirs:
        for path in sorted(directory.rglob("*")):
            if path.is_file() and path.suffix.lower() in {".v", ".sv", ".vh", ".svh"}:
                records.append((str(path.relative_to(root)), _sha256(path)))
    records.append((str(sdc.relative_to(root)), _sha256(sdc)))
    if fast_route is not None:
        records.append((str(fast_route.relative_to(root)), _sha256(fast_route)))
    commit = _git_output(root, "rev-parse", "HEAD") or "unknown"
    if expected_commit is not None and commit != expected_commit:
        raise ValueError("reference checkout changed during bundle resolution")
    fingerprint = hashlib.sha256(json.dumps(
        {"recipe_id": recipe_id, "definition": definition,
         "files": records, "orfs_commit": commit},
        sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()
    return ORFSReferenceDesign(
        platform=platform, design=design, top=definition["top"],
        clock=definition["clock"], clock_period_ns=float(definition["period"]),
        rtl_root=source_root, rtl_files=files, include_dirs=include_dirs,
        sdc_path=sdc, synth_hdl_frontend=definition.get("frontend"),
        design_options=dict(definition.get("options") or {}),
        native_baseline_overrides=dict(definition["baseline"]),
        source_fingerprint=fingerprint, orfs_commit=commit,
        fast_route_tcl_path=fast_route,
    )


def _git_output(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *arguments], text=True,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False,
    ).stdout.strip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
