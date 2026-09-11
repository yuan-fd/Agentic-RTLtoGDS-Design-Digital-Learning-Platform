# A2-ORFO external-project intake

Status: **bounded policy-plugin admission complete; paper-scale campaign not authorized**

Reviewed: 2026-09-04

## Scope and identity

This intake covers the project described by its maintainers as **A2-ORFO
(Autonomous Agent for Intelligent OpenROAD Flow Optimization)**.  The canonical
repository name is `TaiWei-flow-Agent`:

| Field | Locked value |
| --- | --- |
| Canonical upstream | `https://github.com/CODA-Team/TaiWei-flow-Agent.git` |
| Maintainer identity | GitHub organization `CODA-Team` |
| Required commit | `8b20a3c1f22934a39c7ba51ed0ec6dffe730da2d` |
| Commit timestamp | `2026-06-23T02:39:01Z` |
| Upstream relationship | README states that A2-ORFO expands ABKGroup/ORFS-Agent |
| Git tree | `b3906db597359f5786e6cfc69f308479e26f5800` |
| License | BSD-3-Clause (`LICENSE`, SHA-256 `243601633b171278cd98f9ea495cbfc74aad9d7fc062c6e7c81e20d1fc44a22f`) |
| Redistribution conclusion | **Green**, provided notices are retained and nested projects are reviewed separately |

The existing unversioned directories under `.external-src/taiwei-flow-agent`
and `platform-plugins/` are audit material only.  They have no local `.git`
metadata and therefore are not executable admission sources.  Execution must
use a new clean detached checkout of the exact commit above.

## Native entrypoints and owned research logic

- Native campaign entrypoint: `maindriver.sh`.
- Sequential orchestration and configuration generation: `run_sequential.sh`.
- Parallel EDA launcher: `run_parallel.sh`.
- A2-ORFO agent, RAG/ReAct planning, historical comparison, and hybrid search:
  `optimize.py` plus `prompts.py`, `constraint_optimizer.py`, `inspectfuncs.py`,
  `modelfuncs.py`, `agglomfuncs.py`, `rag/`, and `rag_data/`.
- The repository also carries an `AutoTuner-integration` tree and an
  `EDA-Corpus-main` tree.  Their exact Git/submodule identities and licenses
  must be included in the clean-checkout receipt before those paths execute.

The clean checkout records `AutoTuner-integration` as Git tree
`133c3a3caac4190045237d88f375ca240696671a` and `EDA-Corpus-main` as Git
tree `4ca82f3a590d70433bba9085d0b2de88321b8db3`.  The corpus carries CC BY
4.0 text with SHA-256
`7e7170e3cebf88a9f60c7b8421418323c09304da1af4d5e90f4da1dc1c8a2661`.
No separate license was found inside `AutoTuner-integration`; it remains
covered only by the repository-level notice and must stay externally pinned.

The RAG model named by `.gitmodules` is
`mixedbread-ai/mxbai-embed-large-v1`.  The upstream Git tree has no `models`
gitlink, so the model is locked separately at Hugging Face commit
`b33106f585b9ce46904ad7443a3b52b7a63e231c`, Apache-2.0, license SHA-256
`4b0dfefcb74f1e50a8df72a9f2bf0088753f8568bc479387292469b4948705d4`.
The canonical host was unreachable during intake; `https://hf-mirror.com`
may be used only as a retrieval mirror after the canonical identity and exact
commit are verified.

The platform must preserve upstream ownership of knowledge retrieval,
analysis/planning, hybrid LLM/BO policy, candidate generation, and feedback
logic.  It must not create a local algorithm advertised as an A2-ORFO
equivalent.

## Environment, dependencies, credentials, and resources

The upstream README declares Ubuntu/Debian, Python, OpenROAD-flow-scripts,
ORFS-Agent, `jq`, `bc`, `timeout`, and the Python packages NumPy, pandas,
SciPy, scikit-learn, scikit-optimize, python-dotenv, OpenAI, PyTorch, and
sentence-transformers.  The full default campaign declares approximately 110
vCPUs and 220 GB RAM; individual runs require at least 8 vCPUs and 8 GB RAM,
with larger designs requiring 20--25 GB.

The native agent performs provider network calls.  Source inspection found
`OPENAI_API_KEY`, `SUPERVISOR_API_KEY`, and OpenAI-compatible base URLs.  No
credential may be copied into a TaskSpec, artifact, log, source file, or web
request.  Native execution is blocked until a platform-managed credential and
explicit network allowlist are available.  A model substitution must be named
in the protocol receipt and cannot be described as an exact paper
reproduction.

## Security and write-behaviour review

The following upstream behaviours are incompatible with direct execution by
the shared platform and are denied at the adapter boundary:

- shell launchers modify ORFS Makefiles/configuration and create per-candidate
  SDC/configuration files relative to implicit working directories;
- `AutoTuner-integration/**/run_or_job.py` constructs SSH commands, invokes
  subprocesses with `shell=True`, and evaluates remote stdout with `eval`;
- launch scripts may clean or overwrite result/log directories;
- RAG indexing writes local serialized indexes;
- the upstream README suggests putting an API key in source code;
- the complete campaign assumes large parallel resource allocation and named
  remote hosts.

Consequently `maindriver.sh`, `run_parallel.sh`, `run_or_job.py`, and remote
SSH helpers are never platform adapter entries.  No downloaded script may be
executed before the clean checkout, nested licenses, submodules, dependencies,
and exact write set have been rechecked.

## Smallest adapter boundary

The admitted design is a policy plugin, not a second Runtime:

```text
artifact-backed observations + frozen goal/protocol + knowledge references
    -> bounded A2-ORFO policy process
    -> typed candidate proposal + rationale + cited evidence
    -> Policy
    -> existing Runtime ORFS candidate execution
    -> protected evaluator
    -> artifact-backed feedback to the same A2-ORFO policy process
```

Input mapping:

- exact design, platform, objective, constraints, search space, seed and
  remaining budget;
- immutable observation rows with Runtime run IDs and artifact references;
- read-only knowledge/index paths admitted for this plugin invocation; and
- an explicit model/provider profile supplied by the platform operator.

Output mapping:

- complete upstream candidate fields without silent freezing or projection;
- proposal origin (`llm`, `bo`, `hybrid`, or another upstream-native label),
  rationale and evidence references;
- upstream checkpoint/context artifacts required for the next iteration; and
- structured failure information.  The plugin cannot declare measured QoR or
  terminal Runtime success.

Runtime replaces only workspace allocation, local process execution,
concurrency, timeout, cancellation, artifact capture, protected evaluation,
and recovery.  Any incompatibility that requires reimplementing A2-ORFO's
policy is a stop condition.

## Admission and smoke sequence

1. Create a clean detached checkout of the locked commit outside tracked
   source and record repository, submodule, license, and algorithm-file hashes.
2. Build an isolated dependency environment without modifying the ORFS-Agent
   environment or the system Python.
3. Run the smallest upstream-provided native smoke that exercises real
   A2-ORFO policy logic.  A syntax check, import, `--help`, mock candidate, or
   locally reimplemented sampler is not sufficient.
4. Freeze one design/PDK/toolchain, one objective, the complete upstream
   domain, seed, one-feedback budget, evaluator version, and artifact policy.
5. Run one bounded platform loop: upstream proposal -> Runtime ORFS ->
   protected evaluation -> feedback -> next upstream proposal.
6. Verify restart/idempotence and preserve both success and failure evidence.

No paper-scale campaign is authorized by this intake.  The current 78-run
ORFS-Agent campaign is independent historical work and must not be stopped,
rewritten, or relabelled as A2-ORFO evidence.

## Acceptance evidence still required

The bounded admission requirements above were completed by migration slice
030.  Canonical evidence is
`var/evidence/a2-orfo-single-feedback-20260905-r4/summary.json`, SHA-256
`c11638e49bf345987afda2f7159856a67cb4b1f962ceb6a8520d95f6ff7f55aa`.
It records two native A2 policy runs around one real Runtime ORFS measurement.

This does **not** authorize or claim a paper-scale A2 campaign.  Before such a
campaign, freeze its independent statistical protocol, resource budget and
comparison arms.  The retained `r1`, `r2`, and `r3` directories are failed or
invalid acceptance attempts and must not be cited as successful evidence:

- `r1`: Codex structured-output schema incompatibility, no EDA submitted;
- `r2`: EDA and feedback completed, but MODEL was incorrectly dispatched to
  `configure_selection`; useful debugging evidence only;
- `r3`: correct stage dispatch exposed upstream's divergent hard-coded range
  table; the platform rejected the out-of-contract candidate before EDA.

The accepted `r4` binds native `OptimizationWorkflow.run_iteration()` to the
same commit's formal `constraints.json` before proposal generation.  It does
not clamp or repair a generated candidate after the fact.

## Stop conditions

Stop with a written decision record if the clean commit or a nested license is
not verifiable, a managed provider credential is unavailable, native policy
cannot run without remote SSH/shared-tree mutation, the complete candidate
domain cannot be represented, or the protected evaluator/SDC would need to be
changed.  In those cases source audit may continue, but the plugin remains
unregistered and non-executable.

## Rollback

Before registration, rollback is deletion of no source or evidence: leave this
intake and any failed smoke artifacts as historical evidence and do not add an
A2-ORFO manifest.  After registration, remove only the A2-ORFO registry entry
and adapter deployment while preserving Runtime attempts, checkpoints and
artifacts.
