#!/usr/bin/env python3
"""Standalone read-only L1 Trace Dashboard server."""
from __future__ import annotations
import argparse
import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse
from openroad_platform_scheduler.l1_trace_projection import L1TraceReader, list_trace_ids, project_trace

ROOT = Path(__file__).parent
def handler(store):
    class DashboardHandler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(ROOT), **kwargs)
        def do_GET(self):
            path=urlparse(self.path).path
            if path == "/api/traces": return self.respond({"traces": list_trace_ids(store)})
            if path.startswith("/api/traces/"):
                try: return self.respond(project_trace(store, unquote(path.removeprefix("/api/traces/"))))
                except KeyError: return self.respond({"error":"trace not found"}, 404)
                except ValueError: return self.respond({"error":"trace integrity check failed"}, 409)
            if path == "/": self.path="/index.html"
            return super().do_GET()
        def respond(self, value, status=200):
            body=json.dumps(value, ensure_ascii=False).encode()
            self.send_response(status); self.send_header("Content-Type","application/json; charset=utf-8"); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body)
    return DashboardHandler
def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--trace-db",type=Path,required=True); parser.add_argument("--host",default="127.0.0.1"); parser.add_argument("--port",type=int,default=8765); args=parser.parse_args()
    Dashboard=handler(L1TraceReader(args.trace_db))
    ThreadingHTTPServer((args.host,args.port),Dashboard).serve_forever()
if __name__ == "__main__": main()
