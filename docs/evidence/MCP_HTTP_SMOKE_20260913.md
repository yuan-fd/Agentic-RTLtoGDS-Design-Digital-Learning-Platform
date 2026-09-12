# MCP HTTP smoke evidence — 2026-09-13

The local API was started on `127.0.0.1:8765` with the repository's configured ORFS and runtime databases, using `OPENROAD_PLATFORM_NO_AUTH=1` only for local validation.

Observed results:

- `/api/health`: HTTP 200; database, ORFS, execution worker, and TaiWei readiness reported true. The durable DSE controller reported offline and remains an acceptance gap.
- `/api/teaching/mcp/status`: OpenROAD-MCP `1.1.0`, protocol `2025-06-18`, 15 tools.
- `POST /api/teaching/mcp/query` with `help`: returned live stdio MCP output.
- `/api/teaching/mcp/history`: returned the owner-scoped persisted query record.

This validates the HTTP-to-stdio-to-MCP chain. It does not claim that the DSE controller or a full browser experiment is complete.
