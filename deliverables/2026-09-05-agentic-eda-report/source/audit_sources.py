"""Read-only source/evidence audit for the dated documentation deliverable."""
from __future__ import annotations

import ast
import hashlib
import json
import re
import subprocess
from pathlib import Path

OUT = Path(__file__).resolve().parents[1]
ROOT = OUT.parents[1]

EVIDENCE = [
    ("E01", "Native RTLScout Spec-to-GDS", "rtlscout-native-spec-to-gds-20260905-r8"),
    ("E02", "A2 native proposal / real execution / feedback", "a2-orfo-single-feedback-20260905-r4"),
    ("E03", "Executed backend-to-RTL checkpoint recovery", "platform-cross-stage-rtl-recovery-20260905-r2"),
    ("E04", "ORAssistant native retrieval in Runtime", "orassistant-platform-20260905-r3"),
    ("E05", "Four-domain stage diagnostics", "four-domain-stage-diagnostics-20260905-r1"),
    ("E06", "Typed control-state replay", "l1-pdagent-control-state-20260905-r1"),
    ("E07", "Artifact graph", "edatracer-style-artifact-graph-20260905-r1"),
    ("E08", "Convergence classification", "evidence-backed-convergence-20260905-r1"),
    ("E09", "Typed recovery policy", "l1-typed-recovery-policy-20260905-r1"),
    ("E10", "A2 configured 151-run campaign; no execution", "a2-orfo-product-migration-20260905-r3"),
    ("E11", "PostEDA derived diagnostic evaluation", "posteda-platform-diagnostic-20260905-r1"),
    ("E12", "CLOSER paper alignment; not official benchmark", "closer-protocol-alignment-20260905-r2"),
    ("E13", "Managed L1 reference", "l1-managed-aes-reference-20260904-r5"),
    ("E14", "Typed natural-language tool calls", "l1-codex-tool-call-20260904-r1"),
    ("E15", "Native A2 initializer", "a2-orfo-native-initializer-20260905-r1"),
    ("E16", "Durable A2 controller", "a2-orfo-durable-controller-20260905-r1"),
]

CODE = [
    ("C01", "packages/contracts/src/openroad_platform_contracts/platform.py", "class TaskSpec"),
    ("C02", "packages/contracts/src/openroad_platform_contracts/platform.py", "class PluginManifest"),
    ("C03", "packages/contracts/src/openroad_platform_contracts/platform.py", "class PluginResult"),
    ("C04", "packages/contracts/src/openroad_platform_contracts/agent_control.py", "class ToolName"),
    ("C05", "packages/contracts/src/openroad_platform_contracts/product_surface.py", "DEFAULT_PRODUCT_SURFACE ="),
    ("C06", "packages/execution/src/openroad_platform_execution/adapter.py", "class ProcessAdapter"),
    ("C07", "packages/scheduler/src/openroad_platform_scheduler/runtime.py", "class WorkflowRuntime"),
    ("C08", "packages/scheduler/src/openroad_platform_scheduler/l1_tool_registry.py", "class L1RuntimeToolRegistry"),
    ("C09", "packages/scheduler/src/openroad_platform_scheduler/l1_runtime_bridge.py", "class L1RuntimeBridge"),
    ("C10", "packages/scheduler/src/openroad_platform_scheduler/a2_orfo_campaign.py", "class A2ORFOCampaignService"),
    ("C11", "integrations/a2_orfo/a2_orfo_adapter.py", "workflow = upstream.OptimizationWorkflow"),
    ("C12", "packages/analysis/src/openroad_platform_analysis/stage_diagnostics.py", "def _headroom"),
    ("C13", "packages/analysis/src/openroad_platform_analysis/stage_diagnostics.py", "def diagnose_runtime"),
    ("C14", "packages/analysis/src/openroad_platform_analysis/orfs_protected_evaluator.py", "def _evaluate_full_candidate"),
    ("C15", "apps/l1_workbench/service.py", "request = OptimizationRequest("),
    ("C16", "apps/web/index.html", "唯一 BO/GP"),
    ("C17", "CONTRIBUTING.md", "项目当前缺少顶层 LICENSE"),
    ("C18", "LICENSE", "MIT License"),
    ("C19", "packages/scheduler/src/openroad_platform_scheduler/l1_control_state_machine.py", "class "),
    ("C20", "packages/analysis/src/openroad_platform_analysis/convergence.py", "def "),
    ("C21", "packages/analysis/src/openroad_platform_analysis/artifact_graph.py", "def "),
    ("C22", "packages/scheduler/src/openroad_platform_scheduler/rtl_checkpoint_restore.py", "def "),
    ("C23", "apps/l1_workbench/a2_campaign_worker.py", "def "),
    ("C24", "apps/l1_workbench/terminal_dashboard.py", "def "),
    ("C25", "packages/scheduler/src/openroad_platform_scheduler/l1_model_boundary.py", "class "),
    ("C26", "packages/execution/src/openroad_platform_execution/rtlscout_native_driver.py", "def "),
]


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def main():
    documents = list((ROOT / "docs/governance").glob("*.md"))
    document_text = {str(p.relative_to(ROOT)): p.read_text() for p in documents}
    receipts = []
    for eid, title, folder in EVIDENCE:
        p = ROOT / "var/evidence" / folder / "summary.json"
        d = json.loads(p.read_text())
        actual = digest(p)
        refs = [name for name, text in document_text.items() if folder in text and actual in text]
        records = {}
        for node in walk(d):
            if "workspace" in node and isinstance(node.get("artifacts"), list):
                for a in node["artifacts"]:
                    if a.get("store_key") and a.get("sha256"):
                        target = Path(node["workspace"]) / a["store_key"]
                        records[str(target)] = (a["sha256"], a.get("kind"))
            if (isinstance(node.get("path"), str) and node["path"].startswith(str(ROOT / "var/evidence"))
                    and re.fullmatch(r"[0-9a-f]{64}", str(node.get("sha256", "")))):
                records[node["path"]] = (node["sha256"], node.get("kind", "referenced_file"))
        checked = []
        for target, (expected, kind) in sorted(records.items()):
            f = Path(target)
            found = digest(f) if f.is_file() else None
            checked.append({"path": str(f.relative_to(ROOT)), "kind": kind,
                            "expected_sha256": expected, "actual_sha256": found,
                            "verified": found == expected,
                            "size_bytes": f.stat().st_size if f.is_file() else None})
        runs = []
        for node in walk(d):
            if isinstance(node.get("run_id"), str) and isinstance(node.get("status"), str):
                pair = {"run_id": node["run_id"], "status": node["status"]}
                if pair not in runs:
                    runs.append(pair)
        facts = {k: d[k] for k in ["accepted", "status", "statuses", "checks", "claim_boundary",
                                  "required_eda_runs", "budget", "official_closer_bench_result"] if k in d}
        if eid == "E02":
            facts.update({"feedback_status": d["feedback"]["status"],
                          "feedback_feasible": d["feedback"]["feasible"],
                          "first_candidate": d["first_candidate"], "next_candidate": d["next_candidate"],
                          "historical_source": d["historical_source"]})
        if eid == "E01":
            facts["natural_language_spec"] = d["natural_language_spec"]
            facts["verification"] = d["verification"]
        if eid == "E12":
            facts["alignment_counts"] = d["audit"].get("counts")
        receipts.append({"id": eid, "title": title, "path": str(p.relative_to(ROOT)),
                         "sha256": actual, "matching_governance_docs": refs,
                         "facts": facts, "runs": runs, "checked_artifacts": checked})

    code = []
    for cid, name, needle in CODE:
        p = ROOT / name
        lines = p.read_text().splitlines()
        line = next((i for i, s in enumerate(lines, 1) if needle in s), None)
        if not line:
            raise ValueError(f"Missing code anchor: {cid} {needle}")
        code.append({"id": cid, "path": name, "line": line, "anchor": needle,
                     "sha256": digest(p), "line_count": len(lines)})

    contract_edges = []
    for p in (ROOT / "packages/contracts/src").rglob("*.py"):
        tree = ast.parse(p.read_text())
        for node in ast.walk(tree):
            modules = ([node.module or ""] if isinstance(node, ast.ImportFrom)
                       else [n.name for n in node.names] if isinstance(node, ast.Import) else [])
            for module in modules:
                if module.startswith(("openroad_platform_scheduler", "openroad_platform_execution",
                                      "openroad_platform_analysis", "apps", "integrations")):
                    contract_edges.append({"path": str(p.relative_to(ROOT)), "line": node.lineno, "module": module})
    attachments = []
    for p in [
        Path('/share/home/yuanwenjie/.codex/attachments/de9c7ece-edf7-41fa-a00c-bd1c12daff47/ASPDAC27-AgenticEDA-Tutorial-zhiangwang-submitted.pdf'),
        Path('/share/home/yuanwenjie/.codex/attachments/200ebc64-f378-4d88-8b6d-d5eeac34ba9c/平台状况总结.docx'),
    ]:
        attachments.append({"name": p.name, "path": str(p), "sha256": digest(p)})
    result = {"audit_date": "2026-09-05", "head": subprocess.check_output(['git','rev-parse','HEAD'], cwd=ROOT).decode().strip(),
              "method": "Read existing summaries, recompute referenced artifact hashes, inspect source anchors; no EDA rerun.",
              "evidence": receipts, "code": code, "attachments": attachments,
              "contracts_forbidden_import_edges": contract_edges}
    (OUT / "verification/source-audit.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    checked = [a for e in receipts for a in e["checked_artifacts"]]
    failures = [a for a in checked if not a["verified"]]
    print(json.dumps({"summaries": len(receipts), "artifact_reference_checks": len(checked),
                      "unique_artifact_paths": len({a['path'] for a in checked}),
                      "failed_artifact_checks": len(failures), "forbidden_contract_edges": contract_edges,
                      "summaries_without_governance_hash_match": [e['id'] for e in receipts if not e['matching_governance_docs']]}, indent=2))
    if failures:
        print(json.dumps(failures, indent=2))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
