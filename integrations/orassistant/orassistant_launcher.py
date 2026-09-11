#!/usr/bin/env python3
"""Resolve the repository-local locked ORAssistant environment, then exec it."""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    python = (ROOT / "var/external-envs/orassistant-retrieval-a5df2dfe/bin/python").absolute()
    adapter = ROOT / "integrations/orassistant/orassistant_adapter.py"
    source = ROOT / "var/external-sources/orassistant-a5df2dfe-clean"
    corpus = ROOT / "var/external-sources/openroad-docs-63ed2e0-clean"
    corpus_lock = ROOT / "integrations/orassistant/openroad-corpus.lock.json"
    for path in (python, adapter, source, corpus, corpus_lock):
        if not path.exists():
            raise FileNotFoundError(f"locked ORAssistant runtime input is missing: {path}")
    environment = dict(os.environ)
    environment.update({
        "ORASSISTANT_SOURCE": str(source),
        "ORASSISTANT_CORPUS_SOURCE": str(corpus),
        "ORASSISTANT_CORPUS_LOCK": str(corpus_lock),
        "ORASSISTANT_CORPUS_LOCK_SHA256": hashlib.sha256(corpus_lock.read_bytes()).hexdigest(),
        "PYTHONDONTWRITEBYTECODE": "1",
        "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
        "HF_DATASETS_OFFLINE": "1", "LANGCHAIN_TRACING_V2": "false",
        "NO_PROXY": "*", "no_proxy": "*",
        "PATH": os.pathsep.join((str(python.parent), "/usr/bin", "/bin")),
    })
    os.execve(str(python), [str(python), str(adapter), *sys.argv[1:]], environment)


if __name__ == "__main__":
    main()
