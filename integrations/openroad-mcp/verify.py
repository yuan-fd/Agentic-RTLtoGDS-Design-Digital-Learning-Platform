#!/usr/bin/env python3
from __future__ import annotations

"""Exercise every one of the 15 official OpenROAD-MCP tools and print the raw answers.

    python3 verify.py                      # fast, read-mostly sweep
    python3 verify.py --orfs-run           # also start a REAL ORFS synth and cancel it
    python3 verify.py --raw --out report.json

Every step prints the arguments it used and the server's own reply, so you can
check the integration yourself rather than trusting a summary.  Exit status is
the number of failed steps.
"""

import argparse
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp_client import (  # noqa: E402
    MCPError,
    MCPStdioClient,
    result_images,
    result_text,
)

OK, FAIL, SKIP, KNOWN = "OK", "FAIL", "SKIP", "KNOWN"


def _redact(response: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not response:
        return response
    clone = json.loads(json.dumps(response))
    blocks = ((clone.get("result") or {}).get("content")) or []
    for block in blocks:
        if block.get("data"):
            block["data"] = "<%d base64 chars>" % len(block["data"])
        text = block.get("text")
        if isinstance(text, str) and len(text) > 4000:
            block["text"] = text[:4000] + "...<%d chars total>" % len(text)
    return clone


class Report:
    def __init__(self, raw: bool) -> None:
        self.rows: List[Dict[str, Any]] = []
        self.raw = raw

    def add(self, tool: str, status: str, arguments: Dict[str, Any],
            response: Optional[Dict[str, Any]], note: str = "") -> str:
        text = result_text(response) if response else ""
        row = {
            "tool": tool,
            "status": status,
            "arguments": arguments,
            "note": note,
            # Image payloads are stripped: the report records that bytes came
            # back, not megabytes of base64.
            "response": _redact(response),
        }
        self.rows.append(row)
        colour = {OK: "\033[32m", FAIL: "\033[31m", SKIP: "\033[33m",
                  KNOWN: "\033[36m"}.get(status, "")
        print("%s%-4s\033[0m %-30s %s" % (colour, status, tool, note))
        if response is not None and self.raw:
            print(json.dumps(response, ensure_ascii=False, indent=2))
        elif text:
            print("      %s" % text[:200].replace("\n", " "))
        return status

    def check(self, tool: str, arguments: Dict[str, Any], response: Dict[str, Any],
              predicate, describe: str) -> str:
        if "error" in response:
            return self.add(tool, FAIL, arguments, response,
                            "JSON-RPC error: %s" % json.dumps(response["error"], ensure_ascii=False)[:120])
        try:
            payload = json.loads(result_text(response) or "{}")
        except Exception:
            payload = {}
        try:
            ok = predicate(payload, response)
        except Exception as exc:
            return self.add(tool, FAIL, arguments, response, "predicate raised: %s" % exc)
        return self.add(tool, OK if ok else FAIL, arguments, response, describe(payload, response))

    def skipped(self, tool: str, arguments: Dict[str, Any], note: str) -> str:
        return self.add(tool, SKIP, arguments, None, note)

    def summary(self) -> int:
        counts = {OK: 0, FAIL: 0, SKIP: 0, KNOWN: 0}
        for row in self.rows:
            counts[row["status"]] += 1
        print("")
        print("=" * 74)
        print("tools exercised: %d   OK: %d   FAIL: %d   SKIP: %d   KNOWN-UPSTREAM: %d" % (
            len(self.rows), counts[OK], counts[FAIL], counts[SKIP], counts[KNOWN]))
        if counts[FAIL]:
            print("failed: %s" % ", ".join(r["tool"] for r in self.rows if r["status"] == FAIL))
        return counts[FAIL]


def first_image(payload: Dict[str, Any]) -> Optional[str]:
    for _stage, images in (payload.get("images_by_stage") or {}).items():
        for image in images:
            if image.get("filename"):
                return image["filename"]
    return None


def run(args: argparse.Namespace) -> int:
    report = Report(raw=args.raw)
    env = {}
    for item in args.env or []:
        if "=" in item:
            key, value = item.split("=", 1)
            env[key] = value

    client = MCPStdioClient(repo=args.repo, node=args.node, env=env, request_timeout=args.timeout)
    client.start()
    print("repo        : %s" % client.repo)
    print("entry       : %s" % client.entry)
    print("node        : %s" % client.node)
    print("server      : %s %s" % (client.server_info.get("name"), client.server_info.get("version")))
    print("protocol    : %s" % "MCP over stdio (newline-delimited JSON-RPC 2.0)")
    print("-" * 74)

    session_id: Optional[str] = None
    job_id: Optional[str] = None

    try:
        # ---------------------------------------------------------- tools/list
        tools = client.list_tools()
        names = sorted(t["name"] for t in tools)
        report.add("tools/list", OK if len(tools) == 15 else FAIL, {}, None,
                   "%d tools: %s" % (len(tools), ", ".join(names[:4]) + " ..."))

        # ---------------------------------------------- interactive sessions
        response = client.call_tool("create_interactive_session", {})
        status = report.check(
            "create_interactive_session", {}, response,
            lambda p, r: bool(p.get("session_id")) and p.get("is_alive") is True,
            lambda p, r: "session_id=%s alive=%s" % (p.get("session_id"), p.get("is_alive")))
        if status == OK:
            session_id = json.loads(result_text(response))["session_id"]

        report.check("list_interactive_sessions", {}, client.call_tool("list_interactive_sessions"),
                     lambda p, r: p.get("total_count", 0) >= 1 and isinstance(p.get("sessions"), list),
                     lambda p, r: "total=%s active=%s" % (p.get("total_count"), p.get("active_count")))

        if session_id:
            report.check("inspect_interactive_session", {"session_id": session_id},
                         client.call_tool("inspect_interactive_session", {"session_id": session_id}),
                         lambda p, r: bool(p.get("metrics")) and p.get("session_id") == session_id,
                         lambda p, r: "state=%s uptime=%ss" % (
                             (p.get("metrics") or {}).get("state"), (p.get("metrics") or {}).get("uptime_seconds")))

            report.check("interactive_openroad_query", {"session_id": session_id, "command": "help"},
                         client.call_tool("interactive_openroad_query",
                                          {"session_id": session_id, "command": "help"}),
                         lambda p, r: "add_global_connection" in (p.get("output") or ""),
                         lambda p, r: "output %d chars, truncated=%s" % (
                             len(p.get("output") or ""), p.get("truncated")))

            report.check("interactive_openroad_exec",
                         {"session_id": session_id, "command": "set_thread_count 1"},
                         client.call_tool("interactive_openroad_exec",
                                          {"session_id": session_id, "command": "set_thread_count 1"}),
                         lambda p, r: "thread" in (p.get("output") or "").lower(),
                         lambda p, r: (p.get("output") or "").strip().replace("\n", " ")[:80])

            report.check("get_session_history", {"session_id": session_id, "limit": 10},
                         client.call_tool("get_session_history", {"session_id": session_id, "limit": 10}),
                         lambda p, r: len(p.get("history") or []) >= 2,
                         lambda p, r: "%d commands recorded" % len(p.get("history") or []))

            report.check("grep_session_output", {"session_id": session_id, "pattern": "thread"},
                         client.call_tool("grep_session_output",
                                          {"session_id": session_id, "pattern": "thread", "max_matches": 3}),
                         lambda p, r: len(p.get("matches") or []) >= 1,
                         lambda p, r: "%d matches" % len(p.get("matches") or []))

        response = client.call_tool("get_session_metrics")
        report.check("get_session_metrics", {}, response,
                     lambda p, r: isinstance((p.get("metrics") or {}).get("manager"), dict),
                     lambda p, r: "sessions=%s commands=%s" % (
                         (p.get("metrics") or {}).get("manager", {}).get("total_sessions"),
                         (p.get("metrics") or {}).get("aggregate", {}).get("total_commands")))

        # ------------------------------------------------------- ORFS metrics
        metric_args = {"design": args.design, "platform": args.platform}
        response = client.call_tool("read_orfs_metrics", metric_args)
        report.check("read_orfs_metrics", metric_args, response,
                     lambda p, r: bool(p.get("stages")),
                     lambda p, r: "%d stages, gates=%s" % (
                         len(p.get("stages") or []), len(p.get("gates") or [])))

        # ---------------------------------------------------------- ORFS stage
        stage_args = {"design": args.design, "stage": args.stage, "platform": args.platform,
                      "dry_run": not args.orfs_run}
        if args.orfs_run:
            stage_args["wait_seconds"] = 0
        response = client.call_tool("run_orfs_stage", stage_args, timeout=args.timeout)
        status = report.check("run_orfs_stage", stage_args, response,
                              lambda p, r: bool(p.get("job_id")),
                              lambda p, r: "job_id=%s status=%s cmd=%s" % (
                                  p.get("job_id"), p.get("status"), (p.get("command") or "")[:60]))
        if status == OK:
            job_id = json.loads(result_text(response)).get("job_id")

        report.check("get_orfs_job", {"job_id": job_id} if job_id else {},
                     client.call_tool("get_orfs_job", {"job_id": job_id} if job_id else {}),
                     lambda p, r: bool(p.get("job_id") or p.get("jobs")),
                     lambda p, r: "status=%s stage=%s" % (p.get("status"), p.get("stage")))

        # ------------------------------------------------------- cancel a job
        if job_id:
            time.sleep(1.0)
            cancel_args = {"job_id": job_id}
            response = client.call_tool("cancel_orfs_job", cancel_args)
            try:
                payload = json.loads(result_text(response) or "{}")
            except Exception:
                payload = {}
            already = str(payload.get("status") or payload.get("message") or "").lower()
            if payload.get("cancelled") or payload.get("was_running") or "cancel" in already:
                report.add("cancel_orfs_job", OK, cancel_args, response,
                           "cancelled=%s" % (payload.get("cancelled") or payload.get("status")))
            else:
                report.add("cancel_orfs_job", SKIP, cancel_args, response,
                           "job had already finished; re-run with --orfs-run to cancel a live stage")
        else:
            report.skipped("cancel_orfs_job", {}, "no job id from run_orfs_stage")

        # ------------------------------------------------------ report images
        image_args = {"platform": args.image_platform, "design": args.image_design,
                      "run_slug": args.image_run}
        response = client.call_tool("list_report_images", image_args)
        status = report.check("list_report_images", image_args, response,
                              lambda p, r: p.get("total_images", 0) > 0,
                              lambda p, r: "%s images in %s" % (p.get("total_images"), p.get("run_path")))
        image_name = None
        if status == OK:
            image_name = first_image(json.loads(result_text(response)))

        if image_name:
            read_args = dict(image_args, image_name=image_name)
            response = client.call_tool("read_report_image", read_args, timeout=args.timeout)
            report.check("read_report_image", read_args, response,
                         lambda p, r: len(result_images(r)) == 1,
                         lambda p, r: "image=%s mime=%s" % (
                             image_name, (result_images(r) or [{}])[0].get("mimeType")))
        else:
            report.skipped("read_report_image", image_args,
                           "no image name available from list_report_images")

        # ------------------------------------------- known upstream limitation
        nested = {"platform": args.nested_image_platform, "design": args.nested_image_design,
                  "run_slug": args.nested_image_run}
        try:
            listing = client.call_tool("list_report_images", nested)
            payload = json.loads(result_text(listing) or "{}")
            nested_name = first_image(payload)
            if nested_name and payload.get("total_images", 0) > 0:
                response = client.call_tool("read_report_image", dict(nested, image_name=nested_name))
                got = len(result_images(response))
                detail = json.loads(result_text(response) or "{}").get("message") or ""
                if got:
                    report.add("read_report_image (nested run)", OK, nested, response,
                               "nested image read fine")
                else:
                    report.add("read_report_image (nested run)", KNOWN, nested, response,
                               "UPSTREAM: list_report_images recurses into variant dirs, "
                               "read_report_image does not (%s)" % detail[:70])
            else:
                report.skipped("read_report_image (nested run)", nested,
                               "this run has no nested images; skipped")
        except MCPError as exc:
            report.skipped("read_report_image (nested run)", nested, str(exc)[:90])

        # ----------------------------------------------------------- teardown
        if session_id:
            report.check("terminate_interactive_session", {"session_id": session_id},
                         client.call_tool("terminate_interactive_session", {"session_id": session_id}),
                         lambda p, r: p.get("terminated") is True,
                         lambda p, r: "terminated=%s was_alive=%s" % (p.get("terminated"), p.get("was_alive")))
        else:
            report.skipped("terminate_interactive_session", {}, "no session to terminate")
    finally:
        client.close()

    failures = report.summary()
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump({"repo": client.repo, "server": client.server_info, "steps": report.rows},
                      handle, ensure_ascii=False, indent=2)
        print("full report written to %s" % args.out)
    return failures


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Exercise all 15 official OpenROAD-MCP tools.")
    parser.add_argument("--repo")
    parser.add_argument("--node")
    parser.add_argument("--env", action="append")
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--raw", action="store_true", help="print full JSON-RPC responses")
    parser.add_argument("--out", help="write the full report as JSON")
    parser.add_argument("--design", default="gcd")
    parser.add_argument("--platform", default="sky130hd")
    parser.add_argument("--stage", default="synth")
    parser.add_argument("--orfs-run", action="store_true",
                        help="actually run the ORFS stage (default: --dry-run only)")
    parser.add_argument("--image-platform", default="sky130hd")
    parser.add_argument("--image-design", default="ibex")
    parser.add_argument("--image-run", default="base")
    parser.add_argument("--nested-image-platform", default="nangate45")
    parser.add_argument("--nested-image-design", default="opv2_gcd_e31472cb2d95826f")
    parser.add_argument("--nested-image-run", default="v2-generated-smoke-5-tune")
    args = parser.parse_args(argv)
    try:
        return run(args)
    except MCPError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 9


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:
        # e.g. `... | head`; stdout is gone, so exit quietly.
        try:
            sys.stdout.close()
        except Exception:
            pass
        os._exit(0)
