#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analysis/parsers/stage_json.py — 把 ORFS 每阶段的 JSON 归并成一份标准指标报告。

ORFS 会在 logs/<platform>/<design>/base/ 下输出 1_synth.json、2_1_floorplan.json、
3_5_place_dp.json、4_1_cts.json、5_1_grt.json、5_2_route.json、6_report.json 等文件，
key 形如 synth__design__instance__area、detailedroute__route__drc_errors。

本模块做三件事：
  1. 按文件名前缀把 JSON 归到六个阶段（synth/floorplan/place/cts/route/finish）
  2. 用「候选键 + 后缀匹配」把原始 key 映射成稳定的规范名（ORFS 换版本改名也不会崩）
  3. 输出统一结构，供 diagnosis / reporter / web-demo 消费

CLI:
    python3 -m analysis.parsers.stage_json --workdir demo_output/gds/xxx_123 \
        [--platform nangate45] [--design four_bit_counter] [--raw]
不给 platform/design 时会自动从目录结构推断。
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

# 阶段 → 该阶段的 JSON 文件名前缀（ORFS 用数字前缀编号）
STAGE_FILES = {
    "synth":     ("1_",),
    "floorplan": ("2_",),
    "place":     ("3_",),
    "cts":       ("4_",),
    "route":     ("5_",),
    "finish":    ("6_",),
}

# ORFS key 里的阶段命名空间（key 的第一段），用来剥掉前缀
KEY_NAMESPACES = (
    "synth", "floorplan", "globalplace", "detailedplace", "placeopt", "place",
    "cts", "globalroute", "detailedroute", "route", "finish", "grt", "drt",
)

# 规范指标名 → 候选 key 后缀（剥掉命名空间之后的部分），按优先级排列
# 命中规则：先精确匹配，再后缀匹配（endswith），都找不到就是 None
METRIC_SPECS: dict[str, list[tuple[str, list[str]]]] = {
    "synth": [
        ("instance_count",     ["design__instance__count"]),
        ("instance_area_um2",  ["design__instance__area"]),
        ("io_count",           ["design__io"]),
        ("net_count",          ["design__nets"]),
        ("sequential_count",   ["design__instance__count__sequential",
                                "design__instance__count__flop"]),
        ("setup_wns_ns",       ["timing__setup__ws"]),
    ],
    "floorplan": [
        ("die_area_um2",       ["design__die__area"]),
        ("core_area_um2",      ["design__core__area"]),
        ("instance_count",     ["design__instance__count"]),
        ("instance_area_um2",  ["design__instance__area__stdcell",
                                "design__instance__area"]),
        ("utilization_pct",    ["design__instance__utilization",
                                "design__core__util"]),
        ("macro_count",        ["design__instance__count__macros"]),
    ],
    "place": [
        ("instance_count",     ["design__instance__count"]),
        ("instance_area_um2",  ["design__instance__area"]),
        ("utilization_pct",    ["design__instance__utilization",
                                "design__core__util"]),
        ("estimated_wirelength_um", ["route__wirelength__estimated",
                                     "design__wirelength__estimated"]),
        ("setup_wns_ns",       ["timing__setup__ws"]),
        ("setup_tns_ns",       ["timing__setup__tns"]),
        ("displacement_mean_um", ["design__instance__displacement__mean"]),
        ("power_W",            ["power__total"]),
    ],
    "cts": [
        ("skew_ns",            ["clock__skew__worst", "clock__skew"]),
        ("insertion_delay_ns", ["clock__latency__worst",
                                "clock__insertion__worst",
                                "clock__latency__max"]),
        ("clock_buffer_count", ["design__instance__count__setup_buffer",
                                "design__instance__count__hold_buffer",
                                "design__instance__count__clock_buffer"]),
        ("setup_slack_ns",     ["timing__setup__ws"]),
        ("hold_slack_ns",      ["timing__hold__ws"]),
        ("setup_tns_ns",       ["timing__setup__tns"]),
        ("instance_count",     ["design__instance__count"]),
        ("power_W",            ["power__total"]),
    ],
    "route": [
        ("wirelength_um",      ["route__wirelength"]),
        ("estimated_wirelength_um", ["route__wirelength__estimated"]),
        ("via_count",          ["route__vias"]),
        ("via_singlecut_count", ["route__vias__singlecut"]),
        ("via_multicut_count",  ["route__vias__multicut"]),
        ("net_count",          ["route__net"]),
        ("drc_errors",         ["route__drc_errors", "drc__errors"]),
        ("antenna_violations", ["antenna__violating__nets", "antenna_violations"]),
        ("antenna_diode_count",["antenna_diodes_count"]),
        ("setup_wns_ns",       ["timing__setup__ws"]),
        ("setup_tns_ns",       ["timing__setup__tns"]),
        ("hold_wns_ns",        ["timing__hold__ws"]),
        ("hold_tns_ns",        ["timing__hold__tns"]),
        ("congestion_overflow", ["route__congestion__overflow",
                                 "congestion__overflow"]),
        ("grt_overflow_iterations", ["global_route__fastroute__overflow_iterations_s",
                                     "route__overflow__iterations"]),
        ("grt_route_time_s",   ["global_route__fastroute__route_l_s"]),
        ("power_W",            ["power__total"]),
    ],
    "finish": [
        ("instance_count",     ["design__instance__count"]),
        ("instance_area_um2",  ["design__instance__area"]),
        ("die_area_um2",       ["design__die__area"]),
        ("core_area_um2",      ["design__core__area"]),
        ("utilization_pct",    ["design__instance__utilization",
                                "design__core__util"]),
        ("setup_wns_ns",       ["timing__setup__ws"]),
        ("setup_tns_ns",       ["timing__setup__tns"]),
        ("hold_wns_ns",        ["timing__hold__ws"]),
        ("drc_errors",         ["route__drc_errors", "drc__errors"]),
        ("power_W",            ["power__total"]),
        ("warnings",           ["flow__warnings__count"]),
        ("errors",             ["flow__errors__count"]),
        ("warning_type_count", ["flow__warnings__type_count"]),
    ],
}

# 利用率有的版本给 0~1 的比例，有的给 0~100 的百分数，统一成百分数
PCT_METRICS = {"utilization_pct"}

# OpenROAD reports timing in the active Liberty/SDC time unit.  That unit is
# not universally ns: ASAP7 uses ps while sky130hd and nangate45 use ns.  The
# raw ORFS JSON carries the authoritative unit in the floorplan metrics.  A
# parser that merely renames ``timing__setup__ws`` to ``setup_wns_ns`` silently
# introduces a 1000x error on ASAP7, so every time-valued metric is converted
# before it enters EDAIR, an optimizer, or a paper table.
TIME_METRICS = {
    name
    for specs in METRIC_SPECS.values()
    for name, _ in specs
    if name.endswith("_ns")
}
TIME_UNIT_TO_NS = {
    "fs": 1e-6,
    "ps": 1e-3,
    "ns": 1.0,
    "us": 1e3,
    "ms": 1e6,
    "s": 1e9,
}
TIME_UNIT_KEY = "run__flow__platform__time_units"


def _time_unit_evidence(raw: dict[str, dict]) -> dict:
    observed = []
    for stage_payload in raw.values():
        value = stage_payload.get(TIME_UNIT_KEY)
        if isinstance(value, str) and value.strip() and value.strip() not in observed:
            observed.append(value.strip())
    if not observed:
        return {
            "status": "missing", "raw_values": [], "canonical_unit": "ns",
            "scale_to_ns": None,
        }
    if len(observed) != 1:
        return {
            "status": "conflict", "raw_values": observed, "canonical_unit": "ns",
            "scale_to_ns": None,
        }
    match = re.fullmatch(
        r"\s*([0-9]+(?:\.[0-9]+)?)\s*(fs|ps|ns|us|ms|s)\s*",
        observed[0], flags=re.I,
    )
    if not match:
        return {
            "status": "unsupported", "raw_values": observed,
            "canonical_unit": "ns", "scale_to_ns": None,
        }
    magnitude = float(match.group(1))
    scale = magnitude * TIME_UNIT_TO_NS[match.group(2).lower()]
    if not math.isfinite(scale) or scale <= 0:
        return {
            "status": "unsupported", "raw_values": observed,
            "canonical_unit": "ns", "scale_to_ns": None,
        }
    return {
        "status": "verified", "raw_values": observed,
        "canonical_unit": "ns", "scale_to_ns": scale,
    }


# ──────────────────────────────────────────────────────────────────────
# 读取与归类
# ──────────────────────────────────────────────────────────────────────
def _logs_dir(workdir: Path, platform: str, design: str) -> Path:
    return workdir / "logs" / platform / design / "base"


def autodetect(workdir: Path) -> tuple[str | None, str | None]:
    """从 logs/<platform>/<design>/base 反推 platform 与 design。"""
    logs = workdir / "logs"
    if not logs.is_dir():
        return None, None
    for plat in sorted(p for p in logs.iterdir() if p.is_dir()):
        for des in sorted(p for p in plat.iterdir() if p.is_dir()):
            if (des / "base").is_dir():
                return plat.name, des.name
    return None, None


def _load_stage_raw(base: Path) -> dict[str, dict]:
    """把 base/ 下所有 *.json 按数字前缀归到六个阶段，同阶段多文件合并。"""
    raw = {s: {} for s in STAGE_FILES}
    if not base.is_dir():
        return raw
    for f in sorted(base.glob("*.json")):
        stage = next((s for s, pres in STAGE_FILES.items()
                      if any(f.name.startswith(p) for p in pres)), None)
        if stage is None:
            continue
        try:
            data = json.loads(f.read_text(errors="replace"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            raw[stage].update(data)
    return raw


def _strip_ns(key: str) -> str:
    """synth__design__instance__area → design__instance__area"""
    head = key.split("__", 1)
    if len(head) == 2 and head[0] in KEY_NAMESPACES:
        return head[1]
    return key


def _num(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, str):
        try:
            return float(v)
        except ValueError:
            return None
    return None


def _pick(raw: dict, candidates: list[str]):
    """从原始 key/value 里取一个候选：先精确，再后缀匹配。"""
    stripped = {_strip_ns(k): v for k, v in raw.items()}
    for cand in candidates:
        if cand in stripped:
            n = _num(stripped[cand])
            if n is not None:
                return n
    for cand in candidates:                       # 后缀兜底，容忍改名
        for k, v in stripped.items():
            if k.endswith(cand):
                n = _num(v)
                if n is not None:
                    return n
    return None


def _clock_period(workdir: Path, platform: str, design: str) -> float | None:
    """从 constraint.sdc 里读时钟周期，用来算 fmax。"""
    for sdc in (workdir / "designs").rglob("*.sdc"):
        m = re.search(r"-period\s+([\d.]+)", sdc.read_text(errors="replace"))
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                pass
    return None


def extract_metrics_from_log_dir(log_dir, *, design: str, platform: str,
                                 clock_period_ns: float | None = None,
                                 expected_stage: str = "finish") -> dict:
    """Normalize an ORFS leaf log directory without assuming workspace layout.

    Native platform runs store JSON below ``workdir/logs/P/D/base`` while the
    upstream AutoTuner stores every trial in a content-addressed leaf directory.
    Both are ORFS JSON produced by the same pinned flow.  This entry point keeps
    parsing identical without copying or rewriting upstream evidence.
    """
    base = Path(log_dir).expanduser().resolve()
    raw = _load_stage_raw(base)
    time_unit = _time_unit_evidence(raw)
    stages = {}
    for stage, specs in METRIC_SPECS.items():
        src = raw.get(stage) or {}
        if not src:
            stages[stage] = {"status": "not_run", "metrics": {}}
            continue
        metrics = {}
        for name, candidates in specs:
            value = _pick(src, candidates)
            if value is None:
                continue
            if name in TIME_METRICS and time_unit["status"] == "verified":
                value *= time_unit["scale_to_ns"]
            if name in PCT_METRICS and value <= 1.0:
                value *= 100.0
            # Preserve the precision present in ORFS JSON.  In particular,
            # four decimal places in ASAP7 ps become seven meaningful decimal
            # places after conversion to ns.  Nine decimals remove binary
            # floating noise without erasing that evidence.
            if isinstance(value, float):
                value = round(value, 9)
            metrics[name] = value
        slack = metrics.get("setup_wns_ns", metrics.get("setup_slack_ns"))
        if clock_period_ns and slack is not None and clock_period_ns - slack > 0:
            metrics["fmax_mhz"] = round(1000.0 / (clock_period_ns - slack), 2)
        stages[stage] = {"status": "completed", "metrics": metrics}

    order = list(STAGE_FILES)
    if expected_stage not in order:
        raise ValueError(f"unsupported expected stage: {expected_stage}")
    expected = order[:order.index(expected_stage) + 1]
    done = [name for name in expected if stages[name]["status"] == "completed"]
    # Signoff facts are split by ORFS: detailed-route owns the terminal DRC
    # count while 6_report owns timing, power and area.  Merge per metric;
    # treating a non-empty finish dictionary as a replacement loses an
    # explicit route DRC=0 and incorrectly turns clean runs into missing data.
    terminal = {**stages["route"]["metrics"], **stages["finish"]["metrics"]}
    setup = terminal.get("setup_wns_ns")
    hold = terminal.get("hold_wns_ns")
    drc = terminal.get("drc_errors")
    antenna = stages["route"]["metrics"].get("antenna_violations")
    timing_bad = ((setup is not None and setup < 0) or
                  (hold is not None and hold < 0))
    physical_bad = bool(drc) or bool(antenna)
    if len(done) < len(expected):
        overall = "incomplete"
    elif timing_bad or physical_bad:
        overall = "violations"
    elif expected_stage == "finish":
        overall = "clean"
    else:
        overall = "target_stage_complete"
    return {
        "design": design, "platform": platform, "log_dir": str(base),
        "clock_period_ns": clock_period_ns, "units": {
            "time": time_unit,
            "area": {"canonical_unit": "um^2"},
            "power": {"canonical_unit": "W", "source": "ORFS metric contract"},
        }, "stages": stages,
        "summary": {
            "stages_completed": len(done), "stages_total": len(expected),
            "expected_stage": expected_stage,
            "signoff_complete": expected_stage == "finish" and len(done) == len(expected),
            "has_timing_violation": timing_bad,
            "has_drc_errors": physical_bad, "overall_status": overall,
        },
    }


# ──────────────────────────────────────────────────────────────────────
# 主入口
# ──────────────────────────────────────────────────────────────────────
def extract_metrics(workdir, platform: str | None = None,
                    design: str | None = None, keep_raw: bool = False,
                    expected_stage: str = "finish") -> dict:
    """扫描一次 RTL-to-GDS 的工作目录，返回标准化的阶段指标。"""
    workdir = Path(workdir).resolve()
    if not platform or not design:
        p, d = autodetect(workdir)
        platform, design = platform or p, design or d
    if not platform or not design:
        return {"design": design, "platform": platform, "stages": {},
                "summary": {"stages_completed": 0, "overall_status": "unknown",
                            "note": f"在 {workdir} 下找不到 logs/<platform>/<design>/base。"}}

    base = _logs_dir(workdir, platform, design)
    raw = _load_stage_raw(base)
    time_unit = _time_unit_evidence(raw)
    period = _clock_period(workdir, platform, design)
    if period is not None and time_unit["status"] == "verified":
        period *= time_unit["scale_to_ns"]

    stages = {}
    for stage, specs in METRIC_SPECS.items():
        src = raw.get(stage) or {}
        if not src:
            stages[stage] = {"status": "not_run", "metrics": {}}
            continue

        metrics = {}
        for name, cands in specs:
            v = _pick(src, cands)
            if v is None:
                continue
            if name in TIME_METRICS and time_unit["status"] == "verified":
                v *= time_unit["scale_to_ns"]
            if name in PCT_METRICS and v <= 1.0:      # 0~1 → 百分数
                v = v * 100.0
            if isinstance(v, float):
                v = round(v, 9)
            metrics[name] = v

        # fmax：ORFS 不直接给，用 周期 与 setup 裕量 反推
        ws = metrics.get("setup_wns_ns", metrics.get("setup_slack_ns"))
        if period and ws is not None and period - ws > 0:
            metrics["fmax_mhz"] = round(1000.0 / (period - ws), 2)

        stages[stage] = {"status": "completed", "metrics": metrics}
        if keep_raw:
            stages[stage]["raw"] = src

    # 读 flow_error.log（如有）
    flow_log = ""
    err_log = workdir / "analysis" / "flow_error.log"
    if err_log.is_file():
        flow_log = err_log.read_text(encoding="utf-8", errors="replace").strip()
        failed = re.search(r"^stage=(\w+)$", flow_log, re.M)
        if failed and failed.group(1) in stages:
            stages[failed.group(1)]["status"] = "failed"

    order = list(STAGE_FILES)
    if expected_stage not in order:
        expected_stage = "finish"
    expected = order[:order.index(expected_stage) + 1]
    done = [stage for stage in expected if stages[stage]["status"] == "completed"]
    fin = {**stages["route"]["metrics"], **stages["finish"]["metrics"]}
    wns = fin.get("setup_wns_ns")
    hold = fin.get("hold_wns_ns")
    drc = fin.get("drc_errors")
    ant = stages["route"]["metrics"].get("antenna_violations")

    timing_bad = (wns is not None and wns < 0) or (hold is not None and hold < 0)
    drc_bad = bool(drc) or bool(ant)

    if len(done) < len(expected):
        overall = "incomplete"
    elif timing_bad or drc_bad:
        overall = "violations"
    elif expected_stage != "finish":
        overall = "target_stage_complete"
    else:
        overall = "clean"

    return {
        "design": design,
        "platform": platform,
        "workdir": str(workdir),
        "clock_period_ns": period,
        "units": {
            "time": time_unit,
            "area": {"canonical_unit": "um^2"},
            "power": {"canonical_unit": "W", "source": "ORFS metric contract"},
        },
        "stages": stages,
        "summary": {
            "stages_completed": len(done),
            "stages_total": len(expected),
            "expected_stage": expected_stage,
            "signoff_complete": expected_stage == "finish" and len(done) == len(expected),
            "has_timing_violation": bool(timing_bad),
            "has_drc_errors": bool(drc_bad),
            "overall_status": overall,
            "flow_log": flow_log,
        },
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="把 ORFS 各阶段 JSON 归并成标准指标报告")
    ap.add_argument("--workdir", required=True, help="rtl_to_gds 的工作目录")
    ap.add_argument("--platform", default=None, help="默认自动推断")
    ap.add_argument("--design", default=None, help="默认自动推断")
    ap.add_argument("--raw", action="store_true", help="同时保留原始 key")
    ap.add_argument("-o", "--output", default=None, help="写入文件，默认打印到 stdout")
    a = ap.parse_args(argv)

    out = extract_metrics(a.workdir, a.platform, a.design, keep_raw=a.raw)
    text = json.dumps(out, indent=2, ensure_ascii=False)
    if a.output:
        Path(a.output).write_text(text, encoding="utf-8")
        print(f"已写入 {a.output}", file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
