from __future__ import annotations
import argparse,json,selectors,subprocess,threading,time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path

READ_ONLY={'interactive_openroad_query','list_interactive_sessions','inspect_interactive_session','get_session_history','get_session_metrics','list_report_images','read_report_image','get_orfs_job','read_orfs_metrics','grep_session_output'}
DESTRUCTIVE={'interactive_openroad_exec','create_interactive_session','terminate_interactive_session','run_orfs_stage','cancel_orfs_job'}
class MCP:
 def __init__(self,repo): self.repo=Path(repo); self.p=None; self.sel=None; self.lock=threading.RLock(); self.ident=0; self.tools=[]
 def _start(self):
  self.p=subprocess.Popen(['node',str(self.repo/'typescript/dist/main.js')],cwd=self.repo,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
  self.sel=selectors.DefaultSelector(); self.sel.register(self.p.stdout,selectors.EVENT_READ)
  self._send(0,'initialize',{'protocolVersion':'2025-06-18','capabilities':{},'clientInfo':{'name':'openroad-mcp-app','version':'1'}}); self._read(0,10); self.p.stdin.write(b'{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}\n'); self.p.stdin.flush()
  self._send(1,'tools/list',{}); self.tools=self._read(1,10).get('result',{}).get('tools',[])
 def _send(self,i,method,params): self.p.stdin.write((json.dumps({'jsonrpc':'2.0','id':i,'method':method,'params':params})+'\n').encode()); self.p.stdin.flush()
 def _read(self,i,timeout):
  end=time.monotonic()+timeout
  while time.monotonic()<end:
   if not self.sel.select(.2): continue
   line=self.p.stdout.readline().decode(errors='replace').strip()
   if not line: continue
   try:v=json.loads(line)
   except:continue
   if v.get('id')==i:return v
  raise RuntimeError('MCP request timed out')
 def call(self,tool,args,confirm=False):
  if tool not in READ_ONLY|DESTRUCTIVE: raise ValueError('tool is not admitted')
  if tool in DESTRUCTIVE and not confirm: raise ValueError('confirm=true is required for state-changing tools')
  with self.lock:
   if self.p is None or self.p.poll() is not None:self._start()
   self.ident+=1;i=self.ident;self._send(i,'tools/call',{'name':tool,'arguments':args});v=self._read(i,30)
   if 'error' in v:raise RuntimeError(str(v['error']))
   blocks=v.get('result',{}).get('content',[]); text=next((b.get('text') for b in blocks if b.get('text')), '')
   try:data=json.loads(text) if text else {}
   except:data={'output':text}
   return {'tool':tool,'result':data,'images':[{'data':b['data'],'mimeType':b.get('mimeType','image/webp')} for b in blocks if b.get('data')]}
 def catalog(self):
  with self.lock:
   if self.p is None or self.p.poll() is not None:self._start()
   return [{'name':x.get('name'),'description':x.get('description',''),'read_only':x.get('name') in READ_ONLY,'input_schema':x.get('inputSchema',{})} for x in self.tools]
class App(BaseHTTPRequestHandler):
 mcp=None
 def send(self,code,data,typ='application/json'):
  raw=data if isinstance(data,bytes) else json.dumps(data,ensure_ascii=False).encode();self.send_response(code);self.send_header('Content-Type',typ);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
 def do_GET(self):
  if self.path=='/api/status':return self.send(200,{'ok':True,'transport':'stdio','repo':str(self.mcp.repo),'tool_count':len(self.mcp.catalog())})
  if self.path=='/api/tools':return self.send(200,{'tools':self.mcp.catalog()})
  if self.path=='/':return self.send(200,(Path(__file__).parent/'static/index.html').read_bytes(),'text/html; charset=utf-8')
  if self.path.startswith('/static/'):return self.send(200,(Path(__file__).parent/self.path.lstrip('/')).read_bytes())
  return self.send(404,{'error':'not found'})
 def do_POST(self):
  try:
   n=int(self.headers.get('Content-Length','0'));b=json.loads(self.rfile.read(n) or b'{}');p=self.path
   if p=='/api/tool':return self.send(200,self.mcp.call(str(b.get('tool')),b.get('arguments') or {},b.get('confirm') is True))
   return self.send(404,{'error':'not found'})
  except Exception as e:return self.send(400,{'error':str(e)})
def main():
 p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=8780);p.add_argument('--mcp-repo',required=True);a=p.parse_args();App.mcp=MCP(a.mcp_repo);print(f'OpenROAD MCP App: http://127.0.0.1:{a.port}',flush=True);ThreadingHTTPServer(('127.0.0.1',a.port),App).serve_forever()
if __name__=='__main__':main()
