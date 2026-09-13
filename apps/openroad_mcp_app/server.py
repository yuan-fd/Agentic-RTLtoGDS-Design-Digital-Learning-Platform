from __future__ import annotations
import argparse, json, os, selectors, signal, subprocess, threading, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

class MCP:
 def __init__(self, repo): self.repo=Path(repo); self.p=None; self.sel=None; self.lock=threading.Lock(); self.n=0
 def call(self, tool, args):
  with self.lock:
   if self.p is None or self.p.poll() is not None: self._start()
   self.n+=1; ident=self.n
   self.p.stdin.write((json.dumps({'jsonrpc':'2.0','id':ident,'method':'tools/call','params':{'name':tool,'arguments':args}})+'\n').encode()); self.p.stdin.flush()
   deadline=__import__('time').monotonic()+20
   while __import__('time').monotonic()<deadline:
    if self.sel.select(.2):
     line=self.p.stdout.readline().decode(errors='replace').strip()
     if not line: continue
     try: val=json.loads(line)
     except: continue
     if val.get('id')==ident: return self._result(val)
   raise RuntimeError('MCP request timed out')
 def _start(self):
  self.p=subprocess.Popen(['node',str(self.repo/'typescript/dist/main.js')],cwd=self.repo,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
  self.sel=selectors.DefaultSelector(); self.sel.register(self.p.stdout,selectors.EVENT_READ)
  self.p.stdin.write((json.dumps({'jsonrpc':'2.0','id':0,'method':'initialize','params':{'protocolVersion':'2025-06-18','capabilities':{},'clientInfo':{'name':'openroad-mcp-app','version':'1'}}})+'\n').encode()); self.p.stdin.flush()
  while self.sel.select(5):
   if self.p.stdout.readline().strip(): break
  self.p.stdin.write(b'{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}\n'); self.p.stdin.flush()
 def _result(self,v):
  if 'error' in v: raise RuntimeError(str(v['error']))
  out=v.get('result',{}).get('content',[]); txt=next((x.get('text') for x in out if x.get('text')), '{}')
  try: data=json.loads(txt)
  except: data={'output':txt}
  images=[{'data':x['data'],'mimeType':x.get('mimeType','image/webp')} for x in out if x.get('data')]
  return {'result':data, 'images':images}

class App(BaseHTTPRequestHandler):
 mcp=None
 def send(self, code, data, typ='application/json'):
  raw=data if isinstance(data,bytes) else json.dumps(data,ensure_ascii=False).encode(); self.send_response(code); self.send_header('Content-Type',typ); self.send_header('Content-Length',str(len(raw))); self.end_headers(); self.wfile.write(raw)
 def do_GET(self):
  if self.path=='/api/status': return self.send(200,{'ok':True,'mcp':'stdio','repo':str(self.mcp.repo),'server':'server-owned'})
  if self.path=='/': return self.send(200,(Path(__file__).parent/'static/index.html').read_bytes(),'text/html; charset=utf-8')
  if self.path.startswith('/static/'): return self.send(200,(Path(__file__).parent/self.path.lstrip('/')).read_bytes(),'text/css; charset=utf-8')
  self.send(404,{'error':'not found'})
 def do_POST(self):
  try:
   n=int(self.headers.get('Content-Length','0')); body=json.loads(self.rfile.read(n) or b'{}'); path=self.path
   if path=='/api/query': return self.send(200,self.mcp.call('interactive_openroad_query',{'command':body.get('command','')}))
   if path=='/api/sessions': return self.send(200,self.mcp.call('list_interactive_sessions',{}))
   if path=='/api/session/create': return self.send(200,self.mcp.call('create_interactive_session',{}))
   if path=='/api/session/inspect': return self.send(200,self.mcp.call('inspect_interactive_session',{'session_id':body['session_id']}))
   if path=='/api/reports': return self.send(200,self.mcp.call('list_report_images',{k:body[k] for k in ('platform','design','run_slug') if k in body}))
   if path=='/api/report': return self.send(200,self.mcp.call('read_report_image',{k:body[k] for k in ('platform','design','run_slug','image_name') if k in body}))
   return self.send(404,{'error':'not found'})
  except Exception as e: self.send(400,{'error':str(e)})

def main():
 p=argparse.ArgumentParser(); p.add_argument('--port',type=int,default=8780); p.add_argument('--mcp-repo',required=True); a=p.parse_args(); App.mcp=MCP(a.mcp_repo); print(f'OpenROAD MCP App: http://127.0.0.1:{a.port}',flush=True); ThreadingHTTPServer(('127.0.0.1',a.port),App).serve_forever()
if __name__=='__main__': main()
