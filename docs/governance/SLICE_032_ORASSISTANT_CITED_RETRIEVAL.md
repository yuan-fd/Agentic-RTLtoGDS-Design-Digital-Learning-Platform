# Slice 032 — ORAssistant cited read-only retrieval admission

status: completed
completed_at: 2026-09-05
boundary: external knowledge retrieval only; no L1 orchestration/UI change

## Intended architectural change

Admit one pinned ORAssistant knowledge capability through the standard plugin
protocol.  The capability retrieves OpenROAD source documentation and error
evidence with resolvable citations.  It cannot execute EDA, mutate a design,
load a remote serialized index, access a database, or contact a model/network
service.

Before:

```text
L1/model prose or raw report -> no admitted OpenROAD knowledge authority
```

After:

```text
typed knowledge query
  -> knowledge.openroad.retrieve PluginManifest
  -> WorkflowRuntime / isolated adapter attempt
  -> pinned ORAssistant process_md + BM25RetrieverChain + format_docs
  -> Runtime-registered retrieval/explanation/corpus/provenance artifacts
```

The next migration may make this capability available through an L1 semantic
tool.  This slice intentionally does not change the scheduler, API or Web
layers.

## External intake

- ORAssistant: `https://github.com/The-OpenROAD-Project/ORAssistant.git`
- Commit: `a5df2dfe54869fd929d966a4ce335b9d0892f676`
- Tree: `9981a08b1166c82b32cd086d343dbe4a1347f84f`
- License: GPL-3.0-only; **Yellow**, isolated process only, no vendoring/linking
- Native functions: `process_md`, `BM25RetrieverChain`, `format_docs`
- Python: 3.13.7, retrieval-only venv, 53 resolved packages pinned by the
  upstream `uv.lock`
- Corpus: OpenROAD commit `63ed2e0fe5992099b7d528177bbb7a4df9523907`,
  tree `e32e44b5594f05dbb57f37cd81c032998ad1aa2c`, BSD-3-Clause

The upstream Hugging Face RAG dataset was not admitted because its endpoint did
not yield a verifiable commit/license during intake.  Consequently this slice
does not claim ORAssistant's full dataset coverage, vector similarity/MMR,
cross-encoder reranking or generated conversational answers.

The monolithic backend environment sync was interrupted after it began pulling
unused multi-gigabyte CUDA/PyTorch packages.  It was never used for execution.
The admitted retrieval environment installs only upstream-lock versions needed
by the selected native BM25 path.  Fail-closed import sentinels satisfy the
pinned module's optional provider type imports and raise if Google, Vertex,
Ollama or Hugging Face embeddings are instantiated.

## Security and authority checks

- `TaskSpec.inputs` is exactly `query`, `purpose`, `corpus_id`.
- Parameters are exactly `retriever=upstream-bm25` and bounded `top_k`.
- Shell commands, remote index URLs and unknown fields fail closed.
- A Python audit hook denies network resolution/connect and new subprocesses
  after immutable Git identities have been verified.
- Both source checkouts must be detached, clean and match commit/tree/license.
- Corpus material is freshly staged from text; `FAISS.load_local` and dangerous
  deserialization are not reachable.
- Every result contains source path, commit-pinned URL, document SHA-256 and
  chunk SHA-256.
- The explanation artifact distinguishes retrieved facts from hypotheses and
  unknown applicability.  It sets `diagnostic_claim=false`.
- Runtime remains the sole authority for terminal status and registered
  artifacts.

## Changed files

- `docs/governance/ORASSISTANT_INTAKE.md`
- `docs/governance/SLICE_032_ORASSISTANT_CITED_RETRIEVAL.md`
- `docs/governance/LEGACY_CLEANUP_INVENTORY.md`
- `integrations/orassistant/source.lock.json`
- `integrations/orassistant/environment.lock.json`
- `integrations/orassistant/openroad-corpus.lock.json`
- `integrations/orassistant/orassistant.plugin.json`
- `integrations/orassistant/orassistant_launcher.py`
- `integrations/orassistant/orassistant_adapter.py`
- `integrations/plugins.lock.json`
- `integrations/PLUGIN_INVENTORY.md`
- `packages/execution/src/openroad_platform_execution/orassistant_plugin.py`
- `packages/execution/src/openroad_platform_execution/__init__.py`
- `scripts/run_orassistant_native_retrieval_smoke.py`
- `scripts/run_orassistant_platform_acceptance.py`
- `tests/test_orassistant_plugin.py`

No evaluator, RTL, PDK, SDC, ORFS flow, A2-ORFO algorithm or RTLScout source
was changed.

## Focused tests

```text
PYTHONPATH=packages/contracts/src:packages/execution/src:packages/scheduler/src:packages/analysis/src \
python3 -m pytest -q tests/test_orassistant_plugin.py tests/test_plugin_registry.py

12 passed
```

The focused cases cover typed input bounds, static capability discovery, venv
launcher identity, denied shell/remote-index fields and source-lock policy.

## Native smoke evidence

- Evidence: `var/evidence/orassistant-native-retrieval-20260905-r1/native_smoke.json`
- SHA-256: `c944d04f8702672a183b1f1386090551329479c373d5f5ee333023e236bd5714`
- Terminal status: accepted
- Query: `What does [WARNING DRT-0349] mean?`
- Native chunks processed: 563
- Rank 1: pinned OpenROAD `src/drt/test/via_access_layer.ok`, containing the
  exact DRT-0349 warning text

## Bounded platform smoke evidence

- Canonical evidence: `var/evidence/orassistant-platform-20260905-r3/summary.json`
- SHA-256: `615864ce23a50d97e192c5b90db73f79774a43e543aa036073b5b8e03b54e43e`
- Runtime run ID: `b8108f2064ed41a981bd38ea49099a66`
- Terminal status: succeeded; acceptance: true
- Manifest source: static capability registry
- Registered artifacts:
  - retrieval `a9a5f15912cc4e788f657785dc2d7a0a`
  - explanation `e66d15c7eed34acea4635192758e81dd`
  - corpus manifest `652d023930db4fd4aa827370c030dd64`
  - provenance `753c316ab3ec4708934d089218270cf4`

`r1` preserves the failed venv-symlink resolution attempt.  `r2` is a passing
programmatic-manifest smoke.  `r3` supersedes it as canonical because it proves
the checked-in static manifest and launcher path.

## Acceptance and limitations

This slice proves that a real typed Runtime task invokes pinned upstream
ORAssistant preprocessing and BM25 retrieval and returns hash-verifiable cited
evidence.  It does not prove broad retrieval quality, root-cause diagnosis,
full ORAssistant hybrid/reranker parity, or EDA success.  Those claims require
the later PostEDA-Bench evaluation and, for full dataset parity, a separately
admitted dataset/model lock.

## Rollback

Remove only the Slice 032 plugin/launcher/adapter/task-builder/test and its
inventory entries.  Remove the ignored retrieval environment and the two exact
ignored clean checkouts only after confirming retained Runtime artifacts no
longer need them.  Keep `r1`–`r3` and the intake document as historical
evidence.  No Runtime schema migration or protected experiment rollback is
required.
