# Web browser smoke — 2026-09-13

A real Playwright Firefox 1543 process loaded `apps/web/index.html` over HTTP from a local static server and captured [`web-static-overview-20260913.png`](web-static-overview-20260913.png).

This proves the page bundle and stylesheet load in a browser runtime. It is a static smoke only: it does not claim authenticated API interaction or Runtime execution, which remain separate acceptance gates.
