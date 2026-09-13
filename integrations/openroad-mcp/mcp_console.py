#!/usr/bin/env python3
from __future__ import annotations

"""Manual console for the official OpenROAD-MCP server.

This exists so a human can exercise every one of the official MCP tools by hand
and read the raw protocol answers -- no UI, no daemon, no interpretation layer.

    python3 mcp_console.py ping
    python3 mcp_console.py tools
    python3 mcp_console.py describe run_orfs_stage
    python3 mcp_console.py call list_interactive_sessions
    python3 mcp_console.py call interactive_openroad_query '{"command":"help"}'
    python3 mcp_console.py repl

Note on safety: `--yes` is requested for tools that change state.  That is a
convenience guard, NOT a security boundary -- the official server has neither
authentication nor authorisation.  Anyone who can run this can run OpenROAD.
"""

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp_client import (  # noqa: E402
    MCPError,
    MCPStdioClient,
    parse_json,
    result_images,
    result_text,
)

# Tools that change state on the host.  Derived from the official tool
# descriptions; used only to decide whether to ask for --yes.
STATEFUL_TOOLS = {
    "interactive_openroad_exec",
    "create_interactive_session",
    "terminate_interactive_session",
    "run_orfs_stage",
    "cancel_orfs_job",
}


def make_client(args: argparse.Namespace) -> MCPStdioClient:
    env: Dict[str, str] = {}
    for item in args.env or []:
        if "=" in item:
            key, value = item.split("=", 1)
            env[key] = value
    return MCPStdioClient(
        repo=args.repo,
        node=args.node,
        env=env,
        request_timeout=args.timeout,
    )


def describe_tool(tool: Dict[str, Any]) -> str:
    schema = tool.get("inputSchema") or {}
    props = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    lines = ["%s%s" % (tool.get("name"), "   [changes state]" if tool.get("name") in STATEFUL_TOOLS else "")]
    description = (tool.get("description") or "").strip().split("\n")[0]
    if description:
        lines.append("    " + description)
    if not props:
        lines.append("    (no parameters)")
    for name, spec in props.items():
        marker = "*" if name in required else " "
        detail = spec.get("type", "")
        if spec.get("enum"):
            detail = "|".join(str(x) for x in spec["enum"][:6])
        if spec.get("default") is not None:
            detail += " default=%s" % spec["default"]
        description = (spec.get("description") or "").replace("\n", " ")[:80]
        lines.append("    %s %-16s %-18s %s" % (marker, name, detail, description))
    return "\n".join(lines)


def show_response(response: Dict[str, Any], raw: bool, indent: int = 2) -> int:
    """Print a tools/call response.  Returns a process exit code."""
    if raw:
        print(json.dumps(response, ensure_ascii=False, indent=indent))
    if "error" in response:
        print("JSON-RPC error: %s" % json.dumps(response["error"], ensure_ascii=False), file=sys.stderr)
        return 2
    result = response.get("result") or {}
    text = result_text(response)
    if text:
        try:
            print(json.dumps(json.loads(text), ensure_ascii=False, indent=indent))
        except Exception:
            print(text)
    images = result_images(response)
    if images:
        print("(%d image block(s): %s)" % (
            len(images), ", ".join(i.get("mimeType", "?") for i in images)))
    if result.get("isError"):
        print("tool reported an error", file=sys.stderr)
        return 1
    return 0


def call_tool(client: MCPStdioClient, name: str, arguments: Dict[str, Any],
              yes: bool, raw: bool, timeout: Optional[float]) -> int:
    if name in STATEFUL_TOOLS and not yes:
        print("'%s' changes state on this host." % name, file=sys.stderr)
        print("Re-run with --yes if that is what you want.", file=sys.stderr)
        return 3
    print("-> tools/call %s %s" % (name, json.dumps(arguments, ensure_ascii=False)))
    response = client.call_tool(name, arguments, timeout=timeout)
    return show_response(response, raw)


def prompt_arguments(tool: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Schema-driven prompting, so manual testing needs no JSON by hand."""
    schema = tool.get("inputSchema") or {}
    props = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    arguments: Dict[str, Any] = {}
    for name, spec in props.items():
        marker = "required" if name in required else "optional, Enter to skip"
        default = spec.get("default")
        hint = spec.get("type", "")
        description = (spec.get("description") or "").replace("\n", " ")[:70]
        prompt = "  %s (%s, %s)%s: " % (
            name, hint, marker, (" -- " + description) if description else "")
        try:
            value = input(prompt).strip()
        except EOFError:
            return None
        if not value:
            if name in required and default is None:
                print("  %s is required" % name, file=sys.stderr)
                return None
            continue
        if hint == "integer" or hint == "number":
            try:
                value = int(value)
            except ValueError:
                pass
        elif hint == "boolean":
            value = value.lower() in ("1", "true", "yes", "y")
        elif hint == "object" or hint == "array":
            try:
                value = parse_json(value, name)
            except MCPError as exc:
                print("  %s" % exc, file=sys.stderr)
                return None
        arguments[name] = value
    return arguments


def repl(client: MCPStdioClient, raw: bool) -> int:
    tools = {tool["name"]: tool for tool in client.list_tools()}
    print("Connected to %s (%d tools)." % (
        client.server_info.get("name", "?"), len(tools)))
    print("Commands: <tool-name> | tools | describe <tool> | raw on|off | quit")
    print("Type a tool name and you will be prompted for its parameters.\n")
    while True:
        try:
            line = input("mcp> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not line:
            continue
        if line in ("quit", "exit", "q"):
            return 0
        if line == "tools":
            for name in sorted(tools):
                print(describe_tool(tools[name]))
            continue
        if line.startswith("describe "):
            name = line.split(None, 1)[1].strip()
            if name not in tools:
                print("unknown tool %s" % name, file=sys.stderr)
                continue
            print(json.dumps(tools[name].get("inputSchema") or {}, ensure_ascii=False, indent=2))
            continue
        if line == "raw on":
            raw = True
            print("raw protocol output on")
            continue
        if line == "raw off":
            raw = False
            print("raw protocol output off")
            continue
        if line.startswith("call "):
            parts = line.split(None, 2)
            name = parts[1]
            payload = parse_json(parts[2]) if len(parts) > 2 else {}
            if name not in tools:
                print("unknown tool %s" % name, file=sys.stderr)
                continue
            call_tool(client, name, payload, yes=True, raw=raw, timeout=None)
            continue
        if line in tools:
            arguments = prompt_arguments(tools[line])
            if arguments is None:
                print("cancelled")
                continue
            call_tool(client, line, arguments, yes=True, raw=raw, timeout=None)
            continue
        print("unknown command: %s" % line, file=sys.stderr)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="mcp_console",
        description="Talk to the official OpenROAD-MCP server by hand (raw MCP protocol).",
    )
    parser.add_argument("command", choices=["ping", "tools", "describe", "call", "repl"])
    parser.add_argument("argument", nargs="?", help="tool name, or JSON arguments for 'call'")
    parser.add_argument("extra", nargs="?", help="JSON arguments for 'call'")
    parser.add_argument("--repo", default=None, help="path to the OpenROAD-MCP checkout")
    parser.add_argument("--node", default=None, help="path to the node binary")
    parser.add_argument("--env", action="append", help="extra env for the server, e.g. --env ORFS_FLOW_PATH=/path/flow")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--raw", action="store_true", help="also print the raw JSON-RPC response")
    parser.add_argument("--yes", action="store_true", help="allow tools that change state")
    args = parser.parse_args(argv)

    try:
        with make_client(args) as client:
            if args.command == "ping":
                print(json.dumps({
                    "repo": client.repo,
                    "entry": client.entry,
                    "node": client.node,
                    "serverInfo": client.server_info,
                    "toolCount": len(client.list_tools()),
                }, ensure_ascii=False, indent=2))
                return 0
            if args.command == "tools":
                for tool in client.list_tools():
                    print(describe_tool(tool))
                return 0
            if args.command == "describe":
                if not args.argument:
                    print("usage: mcp_console.py describe <tool>", file=sys.stderr)
                    return 2
                for tool in client.list_tools():
                    if tool["name"] == args.argument:
                        print(json.dumps(tool.get("inputSchema") or {}, ensure_ascii=False, indent=2))
                        return 0
                print("unknown tool %s" % args.argument, file=sys.stderr)
                return 2
            if args.command == "call":
                if not args.argument:
                    print("usage: mcp_console.py call <tool> [json]", file=sys.stderr)
                    return 2
                payload = {}
                blob = args.extra or args.argument
                if args.extra is not None or args.argument.strip().startswith("{"):
                    payload = parse_json(blob)
                return call_tool(client, args.argument, payload, args.yes, args.raw, None)
            return repl(client, args.raw)
    except MCPError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 1


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
