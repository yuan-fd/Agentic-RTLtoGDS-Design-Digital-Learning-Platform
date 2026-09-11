from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from openroad_platform_contracts import (
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

from .orfs_config import infer_clock, infer_top, write_design_files
from .orfs_parameters import (
    effective_configuration_id,
    orfs_parameter_schema,
    parameter_source_evidence,
    validate_orfs_parameters,
)
from .process_guardian import ProcessGuardian
from .toolchain import ToolchainConfig


STAGE_ARTIFACTS = {
    # Older admitted ORFS revisions end ``make synth`` at the mapped netlist;
    # newer revisions may also materialize an ODB.  Both are authoritative
    # synthesis products.  Requiring an ODB unconditionally falsely rejects
    # the paper ce8d36a7 flow before floorplan.
    RunStage.SYNTH: ("1_synth.odb", "1_synth.v"),
    RunStage.FLOORPLAN: ("2_floorplan.odb",),
    RunStage.PLACE: ("3_place.odb",),
    RunStage.CTS: ("4_cts.odb",),
    RunStage.ROUTE: ("5_route.odb",),
    RunStage.FINISH: ("6_final.odb",),
}


# The paper-pinned ORFS/OpenROAD pair predates two coordinated upstream fixes.
# ORFS #3050 replaced the ``save_image`` proxy with the OpenROAD compile flag,
# while OpenROAD 4630b597 fixed that flag (it had always been defined).  The
# pinned OpenROAD therefore reports GUI support despite exposing no
# ``gui::show`` command.  Preserve the upstream predicate and additionally
# discover the exact command before invoking the optional visualization.  The
# adaptation applies only to the byte-identical admitted flow source and is
# recorded in per-attempt evidence; implementation/evaluation stays unchanged.
_HEADLESS_FINISH_BACKPORT = {
    "upstream_url": "https://github.com/The-OpenROAD-Project/OpenROAD-flow-scripts",
    "upstream_commit": "e7a0725758c0abde2b69e2cdba783435238748ef",
    "upstream_subject": "Correctly check for OR compiled w/o the GUI enabled.",
    "issue": "https://github.com/The-OpenROAD-Project/OpenROAD-flow-scripts/issues/3050",
    "paired_openroad_commit": "4630b597e7da45019e0e17f19bc58f9128bdbc03",
    "paired_openroad_subject": "ord: correct the setting of BUILD_PYTHON & BUILD_GUI",
    "path": "scripts/final_report.tcl",
    "source_sha256": "431bbf48065fa534369e78fb846390e8b32226800311c2c927afe27e63f8e7b2",
    "patched_sha256": "19e52ae48ac8116a4c451973561e3103b537a330f4e7a5cc14c40d2278708204",
    "old": "if {[expr [llength [info procs save_image]] > 0]} {",
    "new": (
        "if {[ord::openroad_gui_compiled] && "
        "[llength [info commands gui::show]] > 0} {"
    ),
}


class ORFSRunner:
    def __init__(
        self,
        *,
        orfs_root: str | Path | None = None,
        work_root: str | Path,
        openroad_bin: str | Path | None = None,
        yosys_bin: str | Path | None = None,
        toolchain: ToolchainConfig | None = None,
        guardian: ProcessGuardian | None = None,
    ):
        if toolchain is not None and any(
            value is not None for value in (orfs_root, openroad_bin, yosys_bin)
        ):
            raise ValueError("toolchain cannot be combined with explicit tool paths")
        self.toolchain = toolchain or ToolchainConfig.from_environment(
            name="legacy-orfs",
            orfs_root=orfs_root,
            openroad_bin=openroad_bin,
            yosys_bin=yosys_bin,
        )
        self.orfs_root = self.toolchain.orfs_root
        self.flow_home = self.toolchain.flow_home
        self.work_root = Path(work_root).expanduser().resolve()
        self.openroad_bin = self.toolchain.openroad_bin
        self.yosys_bin = self.toolchain.yosys_bin
        self.guardian = guardian or ProcessGuardian()

    def prepare(self, request: RunRequest) -> ExecutionPlan:
        request.validate()
        self._validate_runtime()
        rtl_path = Path(request.rtl_path).expanduser().resolve()
        rtl_paths = tuple(Path(item).expanduser().resolve() for item in request.rtl_files)
        source_paths = rtl_paths or (rtl_path,)
        rtl = "\n".join(path.read_text(encoding="utf-8", errors="replace")
                        for path in source_paths)
        design = request.top or infer_top(rtl, rtl_path.stem)
        if not re.fullmatch(r"[A-Za-z_]\w*", design):
            raise ValueError(f"Invalid inferred top module: {design}")
        clock = request.clock or infer_clock(rtl, design)
        workdir = self.work_root / request.run_id
        if workdir.exists() and any(workdir.iterdir()):
            raise FileExistsError(f"Run workspace is not empty: {workdir}")
        workdir.mkdir(parents=True, exist_ok=True)
        # Never invoke make in the operator-owned ORFS tree.  Materialize a
        # per-Attempt flow copy before any executable step so all possible
        # Makefile/script writes are contained by Runtime's workspace.
        staged_flow = workdir / "orfs-flow"
        shutil.copytree(self.flow_home, staged_flow, symlinks=True)
        flow_compatibility = self._apply_admitted_compatibility_backports(
            staged_flow, workdir,
        )
        canonical_parameters = validate_orfs_parameters(
            request.flow_parameters, platform=request.platform,
        )
        config_path = write_design_files(
            workdir=workdir,
            rtl_path=rtl_path,
            design=design,
            platform=request.platform,
            clock=clock,
            clock_period_ns=request.clock_period_ns,
            core_utilization_pct=request.core_utilization_pct,
            place_density=request.place_density,
            or_seed=request.or_seed,
            minimum_die_size_um=request.minimum_die_size_um,
            flow_parameters=request.flow_parameters,
            rtl_files=rtl_paths,
            rtl_root=(Path(request.rtl_root).expanduser().resolve()
                      if request.rtl_root else None),
            rtl_include_dirs=tuple(Path(item).expanduser().resolve()
                                   for item in request.rtl_include_dirs),
            synth_hdl_frontend=request.synth_hdl_frontend,
            design_options=request.design_options,
            sdc_path=(Path(request.sdc_path).expanduser().resolve()
                      if request.sdc_path else None),
            fast_route_tcl_path=(Path(request.fast_route_tcl_path).expanduser().resolve()
                                 if request.fast_route_tcl_path else None),
        )
        staged_root = workdir / "designs" / "src" / design
        staged_sources = []
        if rtl_paths:
            source_root = Path(request.rtl_root).expanduser().resolve()
            staged_sources = [staged_root / path.relative_to(source_root)
                              for path in rtl_paths]
        else:
            staged_sources = [staged_root / f"{design}{rtl_path.suffix.lower() or '.v'}"]
        self._write_json(workdir / "design_input_manifest.json", {
            "schema_version": 1,
            "kind": "ordered-rtl-bundle",
            "top": design,
            "source_order": [str(path.relative_to(staged_root)) for path in staged_sources],
            "sources": [self._file_record(path) for path in staged_sources],
            "include_dirs": [str((staged_root / Path(item).resolve().relative_to(
                Path(request.rtl_root).expanduser().resolve())).relative_to(staged_root))
                for item in request.rtl_include_dirs] if request.rtl_root else [],
            "synth_hdl_frontend": request.synth_hdl_frontend,
            "design_options": request.design_options,
        })
        stages = tuple(stage for stage in RunStage
                       if list(RunStage).index(stage) <= list(RunStage).index(request.target_stage))
        plan = ExecutionPlan(
            run_id=request.run_id,
            design=design,
            clock=clock,
            workdir=str(workdir),
            flow_home=str(staged_flow),
            config_path=str(config_path),
            stages=stages,
            request=request,
        )
        self._write_json(workdir / "plan.json", {
            "schema_version": 1,
            "run_id": plan.run_id,
            "design": plan.design,
            "clock": plan.clock,
            "workdir": plan.workdir,
            "flow_home": plan.flow_home,
            "source_flow_home": str(self.flow_home),
            "flow_compatibility": flow_compatibility,
            "config_path": plan.config_path,
            "stages": [stage.value for stage in plan.stages],
            "request": request.to_dict(),
            "tools": self.tool_versions(),
        })
        self._write_json(
            workdir / "toolchain_snapshot.json", self.toolchain_snapshot(plan)
        )
        self._write_json(workdir / "parameter_contract.json", {
            "schema_version": 1,
            "registry": orfs_parameter_schema(),
            "requested_parameters": canonical_parameters,
            "effective_configuration_id": effective_configuration_id(
                canonical_parameters, platform=request.platform,
            ),
            "platform": request.platform,
            "generated_config": str(config_path),
            "source_evidence": parameter_source_evidence(
                self.flow_home, canonical_parameters,
            ),
            "claim_boundary": "requested and materialized; runtime liveness requires log/artifact evidence",
        })
        return plan

    def run(
        self,
        plan: ExecutionPlan,
        *,
        cancel_requested: Callable[[], bool] | None = None,
        on_line: Callable[[str], None] | None = None,
        on_stage_start: Callable[[RunStage], None] | None = None,
        on_stage: Callable[[StageResult], None] | None = None,
    ) -> RunResult:
        workdir = Path(plan.workdir)
        log_path = workdir / "logs" / "flow.log"
        started = datetime.now(timezone.utc)
        stage_results: list[StageResult] = []
        final_status = RunStatus.SUCCEEDED
        error = None

        for stage in plan.stages:
            if on_stage_start is not None:
                on_stage_start(stage)
            command = self._command(plan, stage)
            outcome = self.guardian.run(
                command,
                cwd=Path(plan.flow_home),
                env=self._environment(),
                log_path=log_path,
                timeout_seconds=plan.request.stage_timeout_seconds,
                cancel_requested=cancel_requested,
                on_line=on_line,
            )
            gds_exported = False
            if stage == RunStage.FINISH and self._can_export_gds(plan):
                gds_exported = self._export_gds(
                    plan,
                    cancel_requested=cancel_requested,
                    on_line=on_line,
                )
            artifact_error = self._stage_gate(plan, stage)
            if outcome.cancelled:
                status = RunStatus.CANCELLED
                message = "Cancellation requested"
            elif outcome.timed_out:
                status = RunStatus.FAILED
                message = f"Stage exceeded {plan.request.stage_timeout_seconds}s timeout"
            elif outcome.returncode != 0:
                status = RunStatus.FAILED
                message = self._process_failure_message(
                    log_path, stage, outcome.returncode, gds_exported=gds_exported
                )
            elif artifact_error:
                status = RunStatus.FAILED
                message = artifact_error
            else:
                status = RunStatus.SUCCEEDED
                message = None
            stage_result = StageResult(
                stage=stage,
                status=status,
                returncode=outcome.returncode,
                seconds=round(outcome.seconds, 3),
                message=message,
            )
            stage_results.append(stage_result)
            if on_stage is not None:
                on_stage(stage_result)
            if status != RunStatus.SUCCEEDED:
                final_status = status
                error = message
                self._write_flow_error(workdir, stage, message or status.value)
                break

        artifacts = self._collect_artifacts(plan)
        metrics = self._collect_metrics(plan)
        completed_stages = {item.stage for item in stage_results
                            if item.status == RunStatus.SUCCEEDED}
        gds_path = self._results_dir(plan) / "6_final.gds"
        result = RunResult(
            run_id=plan.run_id,
            status=final_status,
            design=plan.design,
            workdir=plan.workdir,
            started_at=started.isoformat(),
            finished_at=datetime.now(timezone.utc).isoformat(),
            stages=tuple(stage_results),
            artifacts=tuple(artifacts),
            milestones={
                "synthesizable": RunStage.SYNTH in completed_stages,
                "functionally_verified": False,
                "implementation_valid": (
                    plan.request.target_stage == RunStage.FINISH and
                    final_status == RunStatus.SUCCEEDED
                ),
                "gds_complete": gds_path.is_file() and gds_path.stat().st_size > 0,
            },
            metrics=tuple(metrics),
            error=error,
        )
        self._write_json(workdir / "run_result.json", result.to_dict())
        return result

    def tool_versions(self) -> dict[str, str | None]:
        versions = {
            "openroad": self._version([str(self.openroad_bin), "-version"]),
            "yosys": self._version([str(self.yosys_bin), "-V"]),
            "orfs_commit": self._version(["git", "-C", str(self.orfs_root), "rev-parse", "HEAD"]),
        }
        if self.toolchain.klayout_bin is not None:
            versions["klayout"] = self._version(
                [str(self.toolchain.klayout_bin), "-v"]
            )
        return versions

    def toolchain_snapshot(self, plan: ExecutionPlan) -> dict[str, object]:
        platform_config = self.flow_home / "platforms" / plan.request.platform / "config.mk"
        generated_config = Path(plan.config_path)
        rtl = Path(plan.request.rtl_path).expanduser().resolve()
        return {
            "schema_version": 1,
            "toolchain": self.toolchain.snapshot(),
            "versions": self.tool_versions(),
            "orfs_worktree_status": self._command_lines([
                "git", "-C", str(self.orfs_root), "status", "--porcelain=v1",
            ]),
            "files": {
                "openroad": self._file_record(self.openroad_bin),
                "yosys": self._file_record(self.yosys_bin),
                "klayout": self._file_record(self.toolchain.klayout_bin),
                "platform_config": self._file_record(platform_config),
                "generated_config": self._file_record(generated_config),
                "flow_compatibility_receipt": self._file_record(
                    Path(plan.workdir) / "flow_compatibility.json"
                ),
                "rtl": self._file_record(rtl),
                "rtl_bundle": [self._file_record(Path(item).expanduser().resolve())
                               for item in plan.request.rtl_files],
            },
            "request": {
                "platform": plan.request.platform,
                "target_stage": plan.request.target_stage.value,
                "top": plan.design,
                "clock": plan.clock,
                "clock_period_ns": plan.request.clock_period_ns,
                "core_utilization_pct": plan.request.core_utilization_pct,
                "place_density": plan.request.place_density,
                "flow_parameters": plan.request.flow_parameters,
                "rtl_root": plan.request.rtl_root,
                "rtl_include_dirs": plan.request.rtl_include_dirs,
                "synth_hdl_frontend": plan.request.synth_hdl_frontend,
                "design_options": plan.request.design_options,
                "sdc": self._file_record(
                    Path(plan.request.sdc_path).expanduser().resolve()
                    if plan.request.sdc_path else None),
                "fast_route_tcl": self._file_record(
                    Path(plan.request.fast_route_tcl_path).expanduser().resolve()
                    if plan.request.fast_route_tcl_path else None),
                "or_seed": plan.request.or_seed,
                "minimum_die_size_um": plan.request.minimum_die_size_um,
                "stage_timeout_seconds": plan.request.stage_timeout_seconds,
            },
        }

    def _validate_runtime(self) -> None:
        if not (self.flow_home / "Makefile").is_file():
            raise FileNotFoundError(f"ORFS Makefile not found: {self.flow_home / 'Makefile'}")
        for name, binary in (("OpenROAD", self.openroad_bin), ("Yosys", self.yosys_bin)):
            if not binary.is_file() or not os.access(binary, os.X_OK):
                raise FileNotFoundError(f"{name} executable not found: {binary}")

    def _command(self, plan: ExecutionPlan, stage: RunStage) -> list[str]:
        return self._make_command(plan, stage.value)

    def _make_command(self, plan: ExecutionPlan, target: str) -> list[str]:
        workdir = Path(plan.workdir)
        raw_cores = os.environ.get("OPENROAD_PLATFORM_ORFS_CORES", "16")
        try:
            cores = int(raw_cores)
        except ValueError as exc:
            raise ValueError("OPENROAD_PLATFORM_ORFS_CORES must be an integer") from exc
        if not 1 <= cores <= 64:
            raise ValueError("OPENROAD_PLATFORM_ORFS_CORES must be between 1 and 64")
        return [
            "make",
            f"DESIGN_CONFIG={plan.config_path}",
            f"DESIGN_HOME={workdir / 'designs'}",
            f"WORK_HOME={workdir}",
            f"OPENROAD_EXE={self.openroad_bin}",
            f"YOSYS_EXE={self.yosys_bin}",
            f"NUM_CORES={cores}",
            "EQUIVALENCE_CHECK=0",
            "LEC_CHECK=0",
            target,
        ]

    def _environment(self) -> dict[str, str]:
        return self.toolchain.build_environment()

    @staticmethod
    def _results_dir(plan: ExecutionPlan) -> Path:
        return (Path(plan.workdir) / "results" / plan.request.platform /
                plan.design / "base")

    def _stage_gate(self, plan: ExecutionPlan, stage: RunStage) -> str | None:
        results = self._results_dir(plan)
        alternatives = [results / name for name in STAGE_ARTIFACTS[stage]]
        missing = [] if any(path.is_file() and path.stat().st_size > 0
                            for path in alternatives) else [
                                "one of " + ", ".join(str(path) for path in alternatives)
                            ]
        if stage == RunStage.FINISH:
            required = [results / name for name in ("6_final.def", "6_final.v", "6_final.gds")]
            missing.extend(str(path) for path in required
                           if not path.is_file() or path.stat().st_size == 0)
        return f"Required artifacts missing or empty: {', '.join(missing)}" if missing else None

    def _can_export_gds(self, plan: ExecutionPlan) -> bool:
        results = self._results_dir(plan)
        return not (results / "6_final.gds").is_file() and (results / "6_final.odb").is_file()

    def _export_gds(
        self,
        plan: ExecutionPlan,
        *,
        cancel_requested: Callable[[], bool] | None,
        on_line: Callable[[str], None] | None,
    ) -> bool:
        results = self._results_dir(plan)
        outcome = self.guardian.run(
            self._make_command(plan, "gds"),
            cwd=Path(plan.flow_home),
            env=self._environment(),
            log_path=Path(plan.workdir) / "logs" / "flow.log",
            timeout_seconds=plan.request.stage_timeout_seconds,
            cancel_requested=cancel_requested,
            on_line=on_line,
        )
        gds = results / "6_final.gds"
        return outcome.returncode == 0 and not outcome.timed_out and not outcome.cancelled \
            and gds.is_file() and gds.stat().st_size > 0

    @staticmethod
    def _process_failure_message(
        log_path: Path,
        stage: RunStage,
        returncode: int,
        *,
        gds_exported: bool,
    ) -> str:
        detail = None
        try:
            lines = log_path.read_text(errors="replace").splitlines()
            detail = next(
                (line.strip() for line in reversed(lines)
                 if "[ERROR" in line or re.search(r"\bError:\s", line)),
                None,
            )
        except OSError:
            pass
        message = f"make {stage.value} exited with {returncode}"
        if detail:
            message += f": {detail[:300]}"
        if gds_exported:
            message += "; GDS export succeeded, but implementation validity failed"
        return message

    def _collect_artifacts(self, plan: ExecutionPlan) -> list[Artifact]:
        workdir = Path(plan.workdir)
        candidates = [
            workdir / "plan.json",
            workdir / "design_input_manifest.json",
            workdir / "toolchain_snapshot.json",
            workdir / "parameter_contract.json",
            workdir / "flow_compatibility.json",
            workdir / "logs/flow.log",
            workdir / "analysis/flow_error.log",
            Path(plan.config_path),
            Path(plan.config_path).with_name("constraint.sdc"),
            Path(plan.config_path).with_name("fastroute.tcl"),
            Path(plan.config_path).with_name("pdn.tcl"),
        ]
        results = self._results_dir(plan)
        candidates.extend(results / name for name in (
            "1_synth.odb", "1_synth.v", "2_floorplan.odb", "3_place.odb", "4_cts.odb",
            "5_route.odb", "6_final.odb", "6_final.def", "6_final.v", "6_final.gds",
        ))
        reports = (workdir / "reports" / plan.request.platform /
                   plan.design / "base")
        candidates.extend(reports / name for name in (
            "6_finish.rpt", "5_route_drc.rpt", "synth_check.txt", "synth_stat.txt",
        ))
        # These machine-readable ORFS reports are the source of the bounded
        # Runtime metric projection below.  They are artifacts, not hidden
        # workspace inputs: Runtime registers and hashes them before metrics
        # may cite them.
        logs = workdir / "logs" / plan.request.platform / plan.design / "base"
        candidates.extend(logs / name for name in ("6_report.json", "5_2_route.json"))
        suffix_kinds = {
            ".v": ArtifactKind.NETLIST,
            ".odb": ArtifactKind.ODB,
            ".def": ArtifactKind.DEF,
            ".gds": ArtifactKind.GDS,
            ".log": ArtifactKind.LOG,
            ".json": ArtifactKind.REPORT,
            ".rpt": ArtifactKind.REPORT,
            ".txt": ArtifactKind.REPORT,
        }
        artifacts = []
        for path in candidates:
            # A clean ORFS run may create an empty DRC/antenna report.  Empty
            # files are absence markers, not evidence artifacts; Runtime
            # correctly rejects them as an artifact protocol violation.
            if not path.is_file() or path.stat().st_size == 0:
                continue
            artifacts.append(Artifact(
                kind=suffix_kinds.get(path.suffix.lower(), ArtifactKind.OTHER),
                path=str(path.relative_to(workdir)),
                size_bytes=path.stat().st_size,
                sha256=self._sha256(path),
            ))
        return artifacts

    @classmethod
    def _apply_admitted_compatibility_backports(
        cls, staged_flow: Path, workdir: Path,
    ) -> list[dict[str, object]]:
        """Backport reviewed upstream fixes into only the isolated flow copy."""
        patch = _HEADLESS_FINISH_BACKPORT
        relative = Path(str(patch["path"]))
        target = staged_flow / relative
        records: list[dict[str, object]] = []
        if target.is_file() and cls._sha256(target) == patch["source_sha256"]:
            original = target.read_text(encoding="utf-8")
            old = str(patch["old"])
            if original.count(old) != 1:
                raise ValueError(
                    "Admitted ORFS headless finish backport source is ambiguous"
                )
            target.write_text(
                original.replace(old, str(patch["new"])), encoding="utf-8"
            )
            actual = cls._sha256(target)
            if actual != patch["patched_sha256"]:
                raise ValueError(
                    "Admitted ORFS headless finish backport digest mismatch"
                )
            records.append({
                "kind": "upstream_backport",
                "scope": "optional_headless_finish_visualization_guard",
                "path": str(relative),
                "source_sha256": patch["source_sha256"],
                "patched_sha256": actual,
                "upstream_url": patch["upstream_url"],
                "upstream_commit": patch["upstream_commit"],
                "upstream_subject": patch["upstream_subject"],
                "issue": patch["issue"],
                "paired_openroad_commit": patch["paired_openroad_commit"],
                "paired_openroad_subject": patch["paired_openroad_subject"],
                "capability_probe": "info commands gui::show",
                "protected_inputs_changed": False,
            })
        receipt = {
            "schema_version": 1,
            "kind": "orfs-flow-compatibility",
            "changes": records,
            "claim_boundary": (
                "Reviewed upstream compatibility backports applied only to the "
                "Runtime-owned attempt copy; RTL, PDK, SDC, evaluator, metrics, "
                "and optimizer semantics are unchanged."
            ),
        }
        cls._write_json(workdir / "flow_compatibility.json", receipt)
        return records

    @staticmethod
    def _write_flow_error(workdir: Path, stage: RunStage, message: str) -> None:
        path = workdir / "analysis" / "flow_error.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"stage={stage.value}\nreason={message}\n", encoding="utf-8")

    def _collect_metrics(self, plan: ExecutionPlan) -> list[Metric]:
        """Return only bounded, artifact-cited ORFS report facts.

        This is not a protected evaluator or a QoR success claim.  It exposes
        the three M1 observations so Runtime can retain their exact report
        provenance; a later policy/evaluator decides whether they satisfy a
        frozen Goal.
        """
        return [*self._collect_finish_metrics_fallback(plan),
                *self._collect_route_metrics(plan)]

    @staticmethod
    def _collect_finish_metrics_fallback(plan: ExecutionPlan) -> list[Metric]:
        finish = (Path(plan.workdir) / "logs" / plan.request.platform / plan.design
                  / "base" / "6_report.json")
        try:
            payload = json.loads(finish.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        names = (
            "finish__design__instance__area",
            "finish__timing__setup__ws",
            "finish__power__total",
        )
        metrics = []
        for name in names:
            value = payload.get(name)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                metrics.append(Metric(name=name, value=value,
                                      source="orfs-finish-report-json-v1"))
        return metrics

    @staticmethod
    def _collect_route_metrics(plan: ExecutionPlan) -> list[Metric]:
        route = (Path(plan.workdir) / "logs" / plan.request.platform / plan.design
                 / "base" / "5_2_route.json")
        try:
            payload = json.loads(route.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        value = payload.get("detailedroute__route__drc_errors")
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return []
        return [Metric(name="detailedroute__route__drc_errors", value=value,
                       source="orfs-route-report-json-v1")]

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _write_json(path: Path, payload: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)

    @staticmethod
    def _version(command: list[str]) -> str | None:
        try:
            result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, timeout=15, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return None
        return next((line.strip() for line in result.stdout.splitlines() if line.strip()), None)

    @staticmethod
    def _command_lines(command: list[str]) -> list[str]:
        try:
            result = subprocess.run(
                command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, timeout=15, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return ["unknown"]
        return [line for line in result.stdout.splitlines() if line.strip()]

    @classmethod
    def _file_record(cls, path: Path | None) -> dict[str, object] | None:
        if path is None:
            return None
        resolved = path.expanduser().resolve()
        if not resolved.is_file():
            return {"path": str(resolved), "size_bytes": None, "sha256": None}
        return {
            "path": str(resolved),
            "size_bytes": resolved.stat().st_size,
            "sha256": cls._sha256(resolved),
        }
