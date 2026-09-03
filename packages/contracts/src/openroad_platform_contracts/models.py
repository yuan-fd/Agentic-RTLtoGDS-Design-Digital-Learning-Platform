from __future__ import annotations

import dataclasses
import json
import re
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class RunStage(str, Enum):
    SYNTH = "synth"
    FLOORPLAN = "floorplan"
    PLACE = "place"
    CTS = "cts"
    ROUTE = "route"
    FINISH = "finish"


STAGE_ORDER = tuple(RunStage)


class RunStatus(str, Enum):
    QUEUED = "queued"
    PREPARING = "preparing"
    RUNNING = "running"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ArtifactKind(str, Enum):
    RTL = "rtl"
    NETLIST = "netlist"
    ODB = "odb"
    DEF = "def"
    GDS = "gds"
    LOG = "log"
    REPORT = "report"
    METRICS = "metrics"
    OTHER = "other"


@dataclass(frozen=True)
class RunRequest:
    rtl_path: str
    # Ordered multi-file/SystemVerilog bundle. ``rtl_path`` remains the
    # primary source for backward compatibility and top inference.  When this
    # tuple is non-empty, every file is staged with its path relative to
    # ``rtl_root``; source order is part of the experiment identity.
    rtl_files: tuple[str, ...] = ()
    rtl_root: str | None = None
    rtl_include_dirs: tuple[str, ...] = ()
    synth_hdl_frontend: str | None = None
    design_options: dict[str, Any] = field(default_factory=dict)
    sdc_path: str | None = None
    top: str | None = None
    clock: str | None = None
    clock_period_ns: float = 10.0
    platform: str = "nangate45"
    target_stage: RunStage = RunStage.FINISH
    core_utilization_pct: float = 10.0
    place_density: float = 0.45
    # Versioned plugin-owned tuning vector. Legacy scalar fields remain as a
    # compatibility projection; new optimization campaigns use this mapping.
    flow_parameters: dict[str, Any] = field(default_factory=dict)
    # OpenROAD detailed routing randomizes the order of nets to reroute.  Keep
    # this explicit so replicated paper experiments can use paired seeds
    # instead of pretending that identical deterministic reruns are samples.
    or_seed: int = 1
    minimum_die_size_um: float | None = None
    stage_timeout_seconds: int = 3600
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    labels: dict[str, str] = field(default_factory=dict)

    def validate(self, *, require_rtl: bool = True) -> None:
        rtl = Path(self.rtl_path).expanduser()
        if require_rtl and not rtl.is_file():
            raise ValueError(f"RTL file does not exist: {rtl}")
        bundle = tuple(Path(item).expanduser() for item in self.rtl_files)
        if bundle:
            root = Path(self.rtl_root).expanduser().resolve() if self.rtl_root else None
            if root is None or not root.is_dir():
                raise ValueError("rtl_root must be an existing directory for a multi-file bundle")
            for source in bundle:
                resolved = source.resolve()
                if require_rtl and (not resolved.is_file() or resolved.stat().st_size == 0):
                    raise ValueError(f"RTL bundle file does not exist or is empty: {resolved}")
                if not resolved.is_relative_to(root):
                    raise ValueError(f"RTL bundle file escapes rtl_root: {resolved}")
                if resolved.suffix.lower() not in {".v", ".sv"}:
                    raise ValueError(f"RTL bundle source must be .v or .sv: {resolved}")
            if require_rtl and rtl.resolve() not in {item.resolve() for item in bundle}:
                raise ValueError("rtl_path must identify one source in rtl_files")
            for include in self.rtl_include_dirs:
                directory = Path(include).expanduser().resolve()
                if not directory.is_dir() or not directory.is_relative_to(root):
                    raise ValueError(f"RTL include directory is invalid or escapes rtl_root: {directory}")
        elif self.rtl_root is not None or self.rtl_include_dirs:
            raise ValueError("rtl_root/include directories require rtl_files")
        if self.synth_hdl_frontend not in {None, "yosys", "slang"}:
            raise ValueError("synth_hdl_frontend must be yosys, slang, or null")
        if not isinstance(self.design_options, dict) or not all(
            isinstance(name, str) and name for name in self.design_options
        ):
            raise ValueError("design_options must be a string-keyed mapping")
        if self.sdc_path is not None:
            sdc = Path(self.sdc_path).expanduser()
            if require_rtl and (not sdc.is_file() or sdc.stat().st_size == 0):
                raise ValueError(f"SDC file does not exist or is empty: {sdc}")
        if self.top is not None and not re.fullmatch(r"[A-Za-z_]\w*", self.top):
            raise ValueError(f"Invalid top module: {self.top}")
        if self.clock is not None and not re.fullmatch(r"[A-Za-z_]\w*", self.clock):
            raise ValueError(f"Invalid clock port: {self.clock}")
        if self.clock_period_ns <= 0:
            raise ValueError("clock_period_ns must be positive")
        if not 0 < self.core_utilization_pct < 100:
            raise ValueError("core_utilization_pct must be between 0 and 100")
        if not 0 < self.place_density <= 1:
            raise ValueError("place_density must be between 0 and 1")
        if not isinstance(self.flow_parameters, dict) or not all(
            isinstance(name, str) and name for name in self.flow_parameters
        ):
            raise ValueError("flow_parameters must be a string-keyed mapping")
        if (not isinstance(self.or_seed, int) or isinstance(self.or_seed, bool)
                or not 0 <= self.or_seed <= 2_147_483_647):
            raise ValueError("or_seed must be an integer between 0 and 2147483647")
        if self.minimum_die_size_um is not None and not (
            5 <= self.minimum_die_size_um <= 10_000
        ):
            raise ValueError("minimum_die_size_um must be between 5 and 10000")
        if self.stage_timeout_seconds <= 0:
            raise ValueError("stage_timeout_seconds must be positive")

    def to_dict(self) -> dict[str, Any]:
        return _to_primitive(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> RunRequest:
        payload = dict(value)
        payload["target_stage"] = RunStage(payload.get("target_stage", RunStage.FINISH))
        payload["rtl_files"] = tuple(payload.get("rtl_files") or ())
        payload["rtl_include_dirs"] = tuple(payload.get("rtl_include_dirs") or ())
        return cls(**payload)


@dataclass(frozen=True)
class ExecutionPlan:
    run_id: str
    design: str
    clock: str | None
    workdir: str
    flow_home: str
    config_path: str
    stages: tuple[RunStage, ...]
    request: RunRequest


@dataclass(frozen=True)
class StageResult:
    stage: RunStage
    status: RunStatus
    returncode: int
    seconds: float
    message: str | None = None


@dataclass(frozen=True)
class Artifact:
    kind: ArtifactKind
    path: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True)
class Metric:
    name: str
    value: float | int | str | None
    unit: str | None = None
    source: str | None = None


@dataclass(frozen=True)
class RunResult:
    run_id: str
    status: RunStatus
    design: str
    workdir: str
    started_at: str
    finished_at: str
    stages: tuple[StageResult, ...]
    artifacts: tuple[Artifact, ...]
    milestones: dict[str, bool] = field(default_factory=dict)
    metrics: tuple[Metric, ...] = ()
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _to_primitive(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)


def _to_primitive(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        return {item.name: _to_primitive(getattr(value, item.name))
                for item in dataclasses.fields(value)}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _to_primitive(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_to_primitive(item) for item in value]
    return value
