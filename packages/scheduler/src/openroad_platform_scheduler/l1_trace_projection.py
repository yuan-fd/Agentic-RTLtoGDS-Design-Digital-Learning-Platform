"""Fail-closed read-only presentation projection for durable L1 traces."""
from __future__ import annotations
import json, sqlite3
from pathlib import Path
from urllib.parse import quote
from openroad_platform_contracts.l1_trace import L1TraceEvent
from .l1_trace_store import _digest
class L1TraceReader:
 def __init__(self,database):
  self.database=Path(database)
  if not self.database.is_file(): raise FileNotFoundError(self.database)
 def _connect(self): return sqlite3.connect(f"file:{quote(str(self.database.resolve()))}?mode=ro",uri=True)
 def _schema(self,c):
  if not {"trace_id","event_id","sequence","parent_event_id","event_json","previous_event_sha256","event_sha256"}.issubset({r[1] for r in c.execute("PRAGMA table_info(l1_trace_event)")}): raise ValueError("trace database has no current read-only schema")
 def list_trace_ids(self):
  with self._connect() as c: self._schema(c); return tuple(r[0] for r in c.execute("SELECT DISTINCT trace_id FROM l1_trace_event ORDER BY trace_id"))
 def read(self,trace_id):
  with self._connect() as c: self._schema(c); rows=c.execute("SELECT event_id,sequence,parent_event_id,event_json,previous_event_sha256,event_sha256 FROM l1_trace_event WHERE trace_id=? ORDER BY sequence",(trace_id,)).fetchall()
  out=[]; prev=None; digest=None; state=None
  for i,r in enumerate(rows):
   if r[1]!=i or r[2]!=(prev.event_id if prev else None) or r[4]!=digest or _digest(r[3],digest)!=r[5]: raise ValueError("trace integrity check failed")
   e=L1TraceEvent.from_dict(json.loads(r[3]))
   if e.event_id!=r[0] or e.sequence!=r[1] or e.parent_event_id!=r[2] or (state and e.state_before_sha256 is not None and e.state_before_sha256!=state.state_after_sha256): raise ValueError("trace integrity check failed")
   out.append(e); prev=e; digest=r[5]; state=e if e.state_after_sha256 is not None else state
  return tuple(out)
def list_trace_ids(reader): return reader.list_trace_ids()
def project_trace(reader,trace_id):
 events=reader.read(trace_id)
 if not events: raise KeyError(trace_id)
 return {"trace_id":trace_id,"event_count":len(events),"events":[{"sequence":e.sequence,"event_id":e.event_id,"occurred_at":e.occurred_at,"kind":e.kind.value,"goal_id":e.goal_id,"tool":e.tool.value if e.tool else None,"policy_verdict":e.policy_verdict,"planner_summary":e.planner_summary,"facts":e.facts,"hypotheses":e.hypotheses,"evidence":[p.to_dict() for p in e.evidence],"state_before_sha256":e.state_before_sha256,"state_after_sha256":e.state_after_sha256} for e in events]}
