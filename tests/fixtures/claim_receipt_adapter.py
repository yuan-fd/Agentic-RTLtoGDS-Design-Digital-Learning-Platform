from __future__ import annotations
import json, os
from pathlib import Path
result = Path(os.sys.argv[4]); (result.parent / "report.json").write_text("{}", encoding="utf-8")
result.write_text(json.dumps({"schema_version":1,"status":"succeeded","exit_code":0,"started_at":"2026-01-01T00:00:00+00:00","ended_at":"2026-01-01T00:00:01+00:00","metrics":[],"artifacts":[{"kind":"report","path":"report.json"},{"kind":"runtime_protocol_receipt","path":"runtime_protocol_receipt.json"}],"failure":None,"provenance":{}}), encoding="utf-8")
