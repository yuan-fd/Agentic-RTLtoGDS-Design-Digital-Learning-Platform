"""Minimal M1 process entrypoint; HTTP composition is added in the workbench slice."""

from __future__ import annotations

import argparse
import json

from .service import M1Service


def main() -> int:
    parser = argparse.ArgumentParser(description="M1 RTL-to-GDS teaching module")
    parser.add_argument("--database", default=":memory:")
    parser.add_argument("--health", action="store_true")
    args = parser.parse_args()
    if args.health:
        print(json.dumps({"app": "m1_rtl_to_gds", "status": "ready"}))
        return 0
    service = M1Service.in_memory() if args.database == ":memory:" else M1Service.open(args.database)
    service.store.close()
    print(json.dumps({"app": "m1_rtl_to_gds", "status": "ready"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
