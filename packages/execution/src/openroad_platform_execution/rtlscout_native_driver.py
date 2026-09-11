"""Invoke the pinned RTLScout native entrypoint with a managed provider seam."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


# A Runtime adapter invokes this file by absolute path with RTLScout's isolated
# interpreter.  Python then places only this module's package directory on
# sys.path, not ``packages/execution/src``; add that one platform boundary
# explicitly before importing the provider adapter below.
EXECUTION_SRC = Path(__file__).resolve().parents[1]
CONTRACTS_SRC = Path(__file__).resolve().parents[3] / "contracts" / "src"
for platform_src in (EXECUTION_SRC, CONTRACTS_SRC):
    if str(platform_src) not in sys.path:
        sys.path.insert(0, str(platform_src))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--benchmark", required=True)
    parser.add_argument("--benchmarks-root", type=Path, required=True)
    parser.add_argument("--runs-dir", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--max-steps", type=int, required=True)
    parser.add_argument("--cost-metric", required=True)
    parser.add_argument("--provider-trace", type=Path, required=True)
    parser.add_argument("--codex-executable", type=Path, required=True)
    args = parser.parse_args(argv)

    source = args.source.resolve()
    if not (source / "run_benchmark.py").is_file():
        raise FileNotFoundError("pinned RTLScout native entrypoint is missing")
    sys.path.insert(0, str(source))

    # Import the exact upstream entrypoint and patch only its documented client
    # construction seam.  RTLAgent and every EDA/evaluation function remain the
    # pinned upstream implementation.
    import core.runner as native_runner
    import run_benchmark as native_entrypoint
    from openroad_platform_execution.rtlscout_managed_provider import (
        ManagedCodexRTLScoutClient,
    )

    native_runner.KNOWN_PROVIDERS.add("codex-cli")

    def build_managed_client(provider: str, model: str, api_key: str | None = None):
        if provider != "codex-cli" or api_key is not None:
            raise ValueError("native RTLScout driver accepts only the managed Codex provider")
        return ManagedCodexRTLScoutClient(
            model=model,
            executable=args.codex_executable,
            trace_path=args.provider_trace,
        )

    native_runner.build_client = build_managed_client
    os.chdir(source)
    sys.argv = [
        str(source / "run_benchmark.py"),
        "--benchmark", args.benchmark,
        "--model", f"codex-cli:{args.model}",
        "--benchmarks-root", str(args.benchmarks_root),
        "--runs-dir", str(args.runs_dir),
        "--max-steps", str(args.max_steps),
        "--cost-metric", args.cost_metric,
        "--agent-backend", "react",
    ]
    native_entrypoint.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
