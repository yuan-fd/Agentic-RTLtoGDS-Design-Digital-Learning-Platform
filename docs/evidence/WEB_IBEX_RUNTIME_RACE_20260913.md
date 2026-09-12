# Browser Ibex Runtime race — 2026-09-13

An authenticated browser submission reached the real Runtime and returned HTTP 201 for run `ba3874ff27e647ca9dc39cda07147a51`. The live server log then showed two workers attempting execution; one reported:

`Runtime run ... could not start: Invalid stage transition running -> running`

The run was later cancelled when the temporary server was stopped. The cause was a benign queue-read race that surfaced as an error log. The worker path now treats a losing SQLite stage transition as normal contention and relies on the transactional RuntimeStore state machine (commit `f18ab82`); focused worker/scheduler tests pass (`6 passed`). A fresh long ORFS browser run is still needed for final closure.
