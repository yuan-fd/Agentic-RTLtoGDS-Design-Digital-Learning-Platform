# OpenROAD-MCP intake evidence

Date: 2026-09-13

## Source

- Repository: `https://github.com/The-OpenROAD-Project/OpenROAD-MCP`
- Reviewed commit: `9dc80d3706fbcd8144cccb639fa21af7b933cbf5`
- npm package version in the reviewed checkout: `1.1.0`
- License: BSD-3-Clause

## Local probe

The source was cloned to an isolated temporary directory. On this server,
Node is `v24.18.0` on `linux/arm64`. `npm ci --ignore-scripts` completed with
no reported vulnerabilities; `npm run build` completed successfully. The
native `node-pty` module required a local `npm rebuild node-pty`, after which
the stdio server started successfully.

The MCP JSON-RPC probe sent `initialize` and `tools/list` to `node dist/main.js`.
The server returned protocol version `2025-03-26`, server name `openroad-mcp`,
version `1.1.0`, and the expected interactive session, ORFS metrics, report
image, and flow-run tools.

The repository now includes `scripts/probe_openroad_mcp.py`, a read-only
repeatable probe. Running it against the pinned local checkout returned
`status=ok`, protocol `2025-06-18`, and 15 tools in 0.545 seconds. It uses
`npx --no-install` when no local build is supplied, so it never downloads a
package as part of a platform check.

## Integration decision

This proves that the official server can run on the platform host, but it does
not authorize direct web exposure. The reviewed server's own security document
states that Streamable HTTP has no authentication, interactive sessions are
in-memory, and its state-modifying tools can execute OpenROAD or ORFS flow
commands. Platform integration therefore remains stdio-only behind the
adapter defined in ADR-002. The platform Runtime remains the authority for
formal experiments and learning evidence.

## Follow-up

The next acceptance slice is an authenticated, owner-scoped adapter probe for
read-only version/report queries and report-image projection. It must use a
server-pinned MCP build, an isolated workspace, bounded Session lifetime, and
must not expose `run_orfs_stage` directly.

The first web slice is now live: an authenticated user calling
`GET /api/teaching/mcp/status` receives the server-owned build identity,
protocol version, and 15-tool list. The endpoint only runs the read-only probe;
it accepts no command, path, or executable from the browser.
