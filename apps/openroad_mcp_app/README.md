# OpenROAD MCP App

Standalone dashboard for the official OpenROAD-MCP server. It uses MCP stdio;
the browser never executes OpenROAD commands directly.

```bash
python3 apps/openroad_mcp_app/server.py --port 8780 \
  --mcp-repo /tmp/openroad-mcp-review
```

Open `http://127.0.0.1:8780`.
