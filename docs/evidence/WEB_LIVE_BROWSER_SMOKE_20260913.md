# Live browser smoke — 2026-09-13

The standard teaching platform startup was launched on `127.0.0.1:8787`. Playwright Firefox loaded the real web server and requested the API-backed page:

- `GET /index.html` — 200
- `GET /assets/app.css` — 200
- `GET /assets/app.js` — 200
- `GET /api/auth/session` — 200
- `GET /api/health` — 200
- `GET /api/platform` — 200

The screenshot is archived as [`web-live-overview-20260913.png`](web-live-overview-20260913.png). MCP history/status correctly require authentication (401 in this unauthenticated smoke). This proves live page/API boot; authenticated Ibex execution replay remains a separate gate.
