# Browser Ibex Runtime race — 2026-09-13

An authenticated browser submission reached the real Runtime and returned HTTP 201 for run `ba3874ff27e647ca9dc39cda07147a51`. The live server log then showed two workers attempting execution; one reported:

`Runtime run ... could not start: Invalid stage transition running -> running`

The run remained `running` in `var/public/runtime.db` during observation. This is recorded as a blocking negative result for the browser-to-runtime acceptance gate. It indicates duplicate execution/claim handling still needs a targeted fix before claiming the full browser Ibex loop.
