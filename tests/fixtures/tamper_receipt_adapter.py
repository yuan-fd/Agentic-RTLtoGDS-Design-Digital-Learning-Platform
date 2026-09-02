from __future__ import annotations

import json
import os
from pathlib import Path


request = json.loads(Path(os.sys.argv[2]).read_text(encoding="utf-8"))
result = Path(os.sys.argv[4])
Path(os.environ["ORFS_AGENT_PROTOCOL_RECEIPT"]).write_text("tampered", encoding="utf-8")
(result.parent / "report.json").write_text("{}", encoding="utf-8")
result.write_text(json.dumps({"schema_version": 1, "status": "succeeded", "exit_code": 0,
                              "started_at": "2026-01-01T00:00:00+00:00", "ended_at": "2026-01-01T00:00:01+00:00",
                              "metrics": [], "artifacts": [{"kind": "report", "path": "report.json"}],
                              "failure": None, "provenance": {"fixture": request["task"]["task_id"]}}), encoding="utf-8")
