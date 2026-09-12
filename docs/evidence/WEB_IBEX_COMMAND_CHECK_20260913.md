# Browser Ibex command-check smoke — 2026-09-13

In a real Playwright Firefox browser context against the live API server, registration returned `201`, then the browser submitted the guided Ibex command to `/api/teaching/command-check`.

Response: HTTP `200`, `accepted: true`, `action: run_baseline`, `missing: []`.

This closes the browser/API teaching command-check gate. It does not claim that the browser itself launched the long ORFS baseline; the existing Runtime evidence remains authoritative for that run.
