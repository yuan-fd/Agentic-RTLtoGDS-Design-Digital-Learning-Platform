from __future__ import annotations

import argparse
import os

from .server import build_server
from .service import M4Service
from .store import M4Store
from .v2 import V2Client


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--database", default=os.environ.get("M4_DATABASE", ":memory:"))
    parser.add_argument("--host", default=os.environ.get("M4_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("M4_PORT", "8104")))
    parser.add_argument("--v2-url", default=os.environ.get("OPENROAD_V2_URL", "http://127.0.0.1:8700"))
    args = parser.parse_args()
    service = M4Service(M4Store(args.database), V2Client(args.v2_url, os.environ.get("OPENROAD_V2_TOKEN")))
    if args.serve:
        server = build_server(args.host, args.port, service)
        try:
            server.serve_forever()
        finally:
            server.server_close()
            service.store.close()
    else:
        service.store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
