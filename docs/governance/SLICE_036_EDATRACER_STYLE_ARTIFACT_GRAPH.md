# Slice 036: EDATracer-style cross-artifact graph

## Boundary

This slice defines and builds a bounded typed graph across Runtime runs,
stages, RTL/netlists, configurations, logs, reports, metrics, artifacts, and
file-line citations. It does not implement a vector index, run an LLM, copy
EDATracer code, expose workspace paths, or claim EDATracer-scale results.

## External reference boundary

The architectural reference is EDATracer (`arXiv:2608.04032v1`): heterogeneous
EDA artifacts are organized as a knowledge graph paired with semantic
retrieval. No public GitHub repository was discoverable on 2026-09-05, so no
commit/license/code intake is possible. This slice therefore cites only the
paper's public graph concept. Executable reuse remains prohibited until a
normal external-project intake succeeds.

## Before / after dependency edge

Before:

```text
Runtime run -> independent artifact and metric rows
```

After:

```text
multiple Runtime runs
  -> stage nodes -> registered artifact nodes
  -> metric nodes --metric_derived_from--> source artifact
  -> identical hashes --content_match--> cross-run continuity
  -> bounded Runtime excerpt -> basename + exact/whole-excerpt line span
```

The graph stores only a document basename, never a workspace or absolute
path. Line content is accessible only via Runtime's hash-checking bounded
artifact reader. Missing source links and truncated excerpts are explicit
unknowns.

## Changed files

- `packages/contracts/src/openroad_platform_contracts/artifact_index.py`
- `packages/contracts/src/openroad_platform_contracts/__init__.py`
- `packages/analysis/src/openroad_platform_analysis/artifact_graph.py`
- `packages/analysis/src/openroad_platform_analysis/__init__.py`
- `tests/test_artifact_graph.py`
- `scripts/run_artifact_graph_acceptance.py`
- this record

## Tests and real bounded acceptance

Focused tests cover the required entity classes, stage/artifact, metric/source,
same-attempt and content-hash edges, exact metric line lookup, strict contract
round trips, explicit orphan metrics, and workspace-path exclusion.

Canonical acceptance uses all five Runtime runs in the previously accepted
real RTLScout Spec-to-GDS flow and reads text only through
`WorkflowRuntime.read_artifact_excerpt`:

```text
var/evidence/edatracer-style-artifact-graph-20260905-r1/summary.json
SHA-256 df79d33949160f1efc8b018afd0f918729b1e99e0e3a008bbb0f325422e37aa4
accepted true

runs             5
nodes            66
edges            93
exact-line nodes 13
explicit unknowns 9
```

The graph contains RTL, config, log, report, metric and stage nodes, connects
same-content artifacts across runs, and preserves metric-to-source-artifact
edges. The source Runtime database hash is identical before and after indexing.

This proves a bounded typed graph and citation path, not semantic-vector
retrieval, 18.9 GB scale, or EDATracer benchmark accuracy.

## Protected and unrelated behavior

No Runtime record, artifact, evaluator, RTL, PDK, SDC, flow, plugin, or
campaign changed. Derived graph evidence references only Runtime run IDs and
registered artifact hashes.

## Rollback

Remove the artifact-index contracts, graph builder/export, tests, acceptance
script, and this record. Runtime evidence remains unchanged.
