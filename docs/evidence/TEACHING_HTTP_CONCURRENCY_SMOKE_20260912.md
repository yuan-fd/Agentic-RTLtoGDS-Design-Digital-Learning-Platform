# Teaching HTTP concurrency smoke

Observed: 2026-09-12  
Command: `python3 scripts/run_teaching_http_concurrency_smoke.py`  
Commit: `7cd7696`

The smoke started the real `ThreadingHTTPServer` against an isolated temporary
database and `WorkbenchService` smoke backend. Eight concurrent clients then:

1. created a Teaching Session;
2. submitted its blocking clarification answer;
3. submitted the L1 `execute` request;
4. read the Session snapshot until Runtime status became `observed`.

Observed result:

```json
{
  "accepted": true,
  "concurrent_sessions": 8,
  "execute_responses": 8,
  "observed_runs": 8,
  "snapshot_reads": 8
}
```

This proves the HTTP/Session/Runtime smoke boundary for eight simultaneous
users. It uses the bounded smoke backend and therefore does not claim that
eight real EDA campaigns can complete concurrently.
