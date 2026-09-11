# ORAssistant external-project intake

status: reviewed-for-bounded-native-smoke
reviewed_at: 2026-09-05
scope: read-only OpenROAD knowledge retrieval and cited error explanation only

## Identity and immutable source

- Canonical upstream: `https://github.com/The-OpenROAD-Project/ORAssistant.git`
- Maintainer: The OpenROAD Project / Precision Innovations
- Branch at audit: `master`
- Pinned commit: `a5df2dfe54869fd929d966a4ce335b9d0892f676`
- Pinned Git tree: `9981a08b1166c82b32cd086d343dbe4a1347f84f`
- Native application entrypoints: `backend/main.py`, `backend/chatbot.py`, and
  `backend/mcp_server.py`
- Retrieval implementation at the pinned revision:
  `backend/src/chains/*`, `backend/src/vectorstores/faiss.py`, and
  `backend/src/agents/retriever_*`
- Declared Python version: `>=3.13`
- Related paper: *ORAssistant: A Custom RAG-based Conversational Assistant for
  OpenROAD* (arXiv:2410.03845).

The commit and tree above were resolved through the GitHub commit API before
any checkout, installation, or execution.  A clean checkout used by a smoke
must have exactly this `HEAD` and tree.  A moving branch tip is never an
execution input.

## License and redistribution conclusion

The pinned repository contains GNU General Public License v3.0 and GitHub
identifies it as `GPL-3.0`.  Intake conclusion is **Yellow**:

- the unmodified upstream may be checked out and executed as an isolated
  research process under the GPL;
- the platform may exchange documented JSON with that process;
- upstream source is not copied into, linked into, or redistributed as part of
  the platform repository by this slice; and
- any future distribution of a combined work or modified upstream must receive
  a separate GPL compliance review and corresponding-source plan.

The execution checkout therefore lives below ignored `var/external-sources/`,
not under a platform package.  The lock and adapter contain no upstream source.

## Native architecture, dependencies, and external state

The full upstream application is materially larger than the requested
capability.  The pinned backend declares, among other dependencies, FastAPI,
LangChain/LangGraph, FAISS, sentence-transformers, PostgreSQL clients,
Google/Vertex integrations, LangSmith, Hugging Face, Ollama and OpenAI client
libraries.  The complete application can require:

- Python 3.13 and a separately locked virtual environment;
- PostgreSQL for conversation state;
- model/download credentials such as Google/Vertex, Hugging Face or LangSmith,
  or a reachable local Ollama service;
- network access for documentation ingestion, model retrieval or cloud LLMs;
  and
- substantial local embedding-model and vector-index storage.

These requirements are not inherited by platform core.  The bounded smoke may
use a separate environment and only the dependencies required by the selected
native retrieval path.  Credentials and network access are not accepted in a
`TaskSpec`.

## Security review

The following full-application surfaces are **denied** in this admission:

1. `backend/mcp_server.py` and `backend/src/openroad_mcp/**` can launch ORFS
   subprocesses and modify dynamic Makefiles/design configuration.  They would
   bypass the platform Policy and Runtime execution authority.
2. `backend/main.py`, database modules, frontend services and conversation
   persistence are outside the requested knowledge capability.
3. `FAISSVectorDatabase.load_db()` enables dangerous deserialization for a
   serialized FAISS/LangChain store.  No downloaded, shared, or otherwise
   untrusted pickle/index may be loaded.
4. Documentation acquisition and model download can make network writes and
   change over time.  A platform run must instead consume a locally materialized
   corpus/model whose origin and digest are pinned before execution.
5. No upstream code is allowed to receive a platform workspace path other than
   the Runtime attempt directory, and the knowledge plugin must not receive an
   ORFS tree, design checkout, shell command, API token or database credential.

The checkout must be inspected after pinning and before execution.  Any source
drift, unexpected submodule, executable installer, remote pickle, subprocess
reachability on the selected path, or need to reimplement the upstream hybrid
retrieval algorithm triggers the charter stop condition.

## Smallest adapter boundary

The admitted capability is `knowledge.openroad.retrieve`:

```text
typed query + corpus lock + retrieval options
  -> Runtime TaskSpec
  -> isolated adapter process
  -> pinned ORAssistant native retriever over a local text corpus
  -> ranked chunks with title/source URL/document digest/score
  -> Runtime artifacts
  -> deterministic cited error explanation view
```

The platform adapter may validate and normalize JSON and artifacts.  It must
not reproduce ranking, embedding, MMR, BM25, reranking, agent routing or answer
generation logic owned by ORAssistant.  The first admission uses only a native
read-only retriever mode demonstrable without the denied MCP/database/frontend
surfaces.  If the pinned revision exposes no such callable seam without broad
application initialization, work stops and records alternatives instead of
creating a local "equivalent" retriever.

Input mapping:

- `inputs.query`: bounded UTF-8 text, not shell text;
- `inputs.corpus_manifest`: attempt-local manifest of immutable text documents;
- `parameters.retriever`: an upstream-advertised retrieval method;
- `parameters.top_k`: bounded result count; and
- `parameters.purpose`: `knowledge` or `error_explanation`.

Output mapping:

- `retrieval.json`: ranked native results and upstream method/provenance;
- `explanation.json`: facts quoted from results, explicit inference/unknown
  fields and citation identifiers (for error-explanation requests);
- `native_trace.json`: selected upstream entrypoint, source/model/corpus locks
  and denied-capability confirmation; and
- raw stdout/stderr logs preserved by Runtime.

An explanation is an evidence-backed index, never a replacement for the source
chunk and never an EDA success claim.

## Frozen smoke protocol

The upstream README names the Hugging Face dataset
`The-OpenROAD-Project/ORAssistant_RAG_Dataset`, but its endpoint did not return
a commit or license during this intake.  It is therefore **not admitted** and
is not downloaded.  The first smoke instead uses a second, independently
locked source corpus: OpenROAD at commit
`63ed2e0fe5992099b7d528177bbb7a4df9523907` (tree
`e32e44b5594f05dbb57f37cd81c032998ad1aa2c`, BSD-3-Clause).  The corpus lock
selects documentation, tool READMEs, message text when tracked, and one pinned
error-log example; native ORAssistant preprocessing ingests fresh text inside
the attempt.  This establishes the safe adapter seam but does not claim the
coverage of ORAssistant's full published dataset.

Native smoke must precede platform smoke and use the same immutable corpus and
query:

1. verify checkout commit/tree and license;
2. prove the selected import/call graph does not import MCP execution,
   database, frontend or unsafe index-loading code;
3. build a fresh local index from text documents only (never deserialize a
   downloaded FAISS/pickle object);
4. submit an OpenROAD command/error query;
5. require at least one ranked result containing a stable source/title/URL,
   chunk text and document digest; and
6. preserve command, exit code, environment lock, output and hashes.

Bounded platform smoke then submits the same query through `PluginManifest`,
`TaskSpec`, the adapter process and Runtime.  Acceptance requires terminal
`SUCCEEDED`, Runtime-registered evidence artifacts, citations that resolve to
the stored corpus, and negative tests proving shell/MCP/remote-index fields are
rejected.

The smoke proves integration and citation integrity only.  It does not prove
answer correctness on a broad benchmark, diagnostic quality, or PPA benefit.

## Rollback

Remove the ORAssistant manifest/lock and platform-owned adapter files, and
delete only the explicitly named ignored execution checkout/environment after
verifying no retained evidence references it.  Existing Runtime/evidence rows
and upstream-source audit records remain historical evidence.
