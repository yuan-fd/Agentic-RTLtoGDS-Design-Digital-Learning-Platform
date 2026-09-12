# Authenticated browser smoke — 2026-09-13

Using Playwright Firefox against the standard API server on `127.0.0.1:8788`, a browser context registered `browser_smoke_20260913` through the real `/api/auth/register` endpoint (HTTP 201), reloaded the application, and confirmed the rendered page contains the Labs and Ibex teaching content.

Observed DOM checks:

- document title: `OpenROAD Self-Evolving EDA Platform`
- Labs markers: 2
- Ibex markers: 9

Screenshot: [`web-authenticated-overview-20260913.png`](web-authenticated-overview-20260913.png). This is authenticated page boot/content evidence; a full Ibex execution from the browser remains pending.
