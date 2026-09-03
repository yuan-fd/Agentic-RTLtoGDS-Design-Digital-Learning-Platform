#!/usr/bin/env python3
"""Terminal-only L1 workbench dashboard over the public L1 API.

It owns no Session, Policy, Runtime state, or trace data.  Every panel is a
projection of API-returned durable events; commands merely call the API.
"""
from __future__ import annotations
import argparse, curses, json, textwrap
from urllib.request import Request, urlopen
from urllib.parse import quote


class Client:
 def __init__(self, base): self.base=base.rstrip("/")
 def post(self,path,payload):
  raw=json.dumps(payload).encode(); req=Request(self.base+path,data=raw,headers={"Content-Type":"application/json"})
  return json.loads(urlopen(req,timeout=10).read())
 def get(self,path): return json.loads(urlopen(self.base+path,timeout=10).read())


def _lines(value,width):
 return [line for part in str(value).splitlines() for line in textwrap.wrap(part,width=max(12,width))] or [""]


class Dashboard:
 def __init__(self, client): self.client,self.sid,self.after,self.events,self.notice=client,None,-1,[],"Type :new <goal> to begin."
 def refresh(self):
  if not self.sid:return
  data=self.client.get(f"/api/l1/sessions/{quote(self.sid)}/events?after={self.after}")
  if data.get("events"): self.events.extend(data["events"]); self.after=max(e["sequence"] for e in self.events)
 def command(self,text):
  try:
   op,_,arg=text[1:].partition(" ")
   if op=="new":
    result=self.client.post("/api/l1/sessions",{"text":arg});self.sid=result["session_id"];self.after=-1;self.events=[];self.notice=f"Session {self.sid}: {result['status']}";self.refresh()
   elif op=="answer":
    self.client.post(f"/api/l1/sessions/{self.sid}/answers",{"answers":[{"question_id":"objective-1","field":"objective","value":arg}]});self.notice="Clarification stored; Goal frozen.";self.refresh()
   elif op=="run":
    result=self.client.post(f"/api/l1/sessions/{self.sid}/execute",{"decision_summary":arg or "Execute one bounded typed Runtime tool."});self.notice=f"Runtime {result['plan']['run_id']} returned {result['runtime']['run']['status']}";self.refresh()
   elif op=="cancel": self.notice=str(self.client.post(f"/api/l1/sessions/{self.sid}/cancel",{"reason":arg or "operator cancellation"}))
   elif op=="recover": self.notice=str(self.client.post(f"/api/l1/sessions/{self.sid}/recover",{}));self.refresh()
   elif op=="refresh": self.refresh()
   else:self.notice="Commands: :new TEXT | :answer TEXT | :run [summary] | :cancel [reason] | :recover | :refresh | :quit"
  except Exception as exc:self.notice=f"API error: {exc}"
 def draw(self,win):
  win.erase(); h,w=win.getmaxyx(); win.addnstr(0,0,"OpenROAD Platform — L1 Terminal Workbench (durable API facts only)",w-1,curses.A_BOLD)
  win.addnstr(1,0,f"session: {self.sid or 'none'} | cursor: {self.after} | {self.notice}",w-1)
  left=max(34,w//2); win.addnstr(3,0,"Goal / Policy / Planner",left-1,curses.A_UNDERLINE);win.addnstr(3,left,"Runtime / Evidence Timeline",w-left-1,curses.A_UNDERLINE)
  goals=[e for e in self.events if e['kind'] in ('goal_drafted','goal_finalized','policy_decided','tool_called')]
  runtime=[e for e in self.events if e['kind'] in ('tool_receipt','state_transition','stopped')]
  y=4
  for e in goals[-8:]:
   text=f"#{e['sequence']} {e['kind']} {e.get('planner_summary') or ''}"
   for line in _lines(text,left-2):
    if y>=h-3:break
    win.addnstr(y,0,line,left-2);y+=1
  y=4
  for e in runtime[-10:]:
   fact=e.get('facts',{}); text=f"#{e['sequence']} {e['kind']} {fact.get('status') or fact.get('terminal_status') or ''} {fact.get('run_id') or ''} evidence={len(e.get('evidence',[]))}"
   for line in _lines(text,w-left-2):
    if y>=h-3:break
    win.addnstr(y,left,line,w-left-2);y+=1
  win.addnstr(h-2,0,"Command> ",w-1,curses.A_REVERSE); win.refresh()
 def run(self,win):
  curses.curs_set(1);win.timeout(250)
  while True:
   self.draw(win); curses.echo(); raw=win.getstr(win.getmaxyx()[0]-1,9,win.getmaxyx()[1]-10).decode(errors='replace').strip();curses.noecho()
   if not raw:
    try:self.refresh()
    except Exception as exc:self.notice=f"poll error: {exc}"
    continue
   if raw==":quit":return
   self.command(raw)

def main():
 p=argparse.ArgumentParser();p.add_argument("--api",default="http://127.0.0.1:8766");a=p.parse_args();curses.wrapper(Dashboard(Client(a.api)).run)
if __name__=="__main__":main()
