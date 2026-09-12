# Browser Ibex Runtime submission — 2026-09-13

An authenticated Playwright Firefox context submitted the fixed Ibex baseline through the live web API:

- endpoint: `POST /api/teaching/reference-baseline`
- response: HTTP `201`
- run: `02d22e02664041af9a6f606c0825375b`
- initial Runtime state: `queued`

The response contains the server-pinned Ibex bundle, constraints, toolchain commit, and Runtime task specification. The web server was then stopped; this evidence proves browser submission and queue admission, while final execution remains governed by the durable Runtime worker.
