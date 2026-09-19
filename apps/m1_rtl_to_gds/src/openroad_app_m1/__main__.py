"""M1 process entrypoint."""

from __future__ import annotations

import argparse
import json
import os

from .service import M1Service
from .server import build_server
from .v2_client import V2Client


def main() -> int:
    parser = argparse.ArgumentParser(description="M1 RTL-to-GDS teaching module")
    parser.add_argument("--database", default=":memory:")
    parser.add_argument("--health", action="store_true")
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8101)
    parser.add_argument("--v2-url", default=os.environ.get("OPENROAD_V2_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--v2-token", default=os.environ.get("OPENROAD_V2_TOKEN"))
    args = parser.parse_args()
    if args.health:
        print(json.dumps({"app": "m1_rtl_to_gds", "status": "ready"}))
        return 0
    service = M1Service.in_memory() if args.database == ":memory:" else M1Service.open(args.database)
    if args.serve:
        server = build_server(args.host, args.port, service, V2Client(args.v2_url, token=args.v2_token))
        try:
            server.serve_forever()
        finally:
            server.server_close()
            service.store.close()
        return 0
    service.store.close()
    print(json.dumps({"app": "m1_rtl_to_gds", "status": "ready"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
