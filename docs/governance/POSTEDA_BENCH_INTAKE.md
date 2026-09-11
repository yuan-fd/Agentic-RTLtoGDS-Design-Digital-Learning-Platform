# PostEDA-Bench external-project intake

status: bounded one-task diagnostic evaluator admitted

reviewed_at: 2026-09-05

## Identity and immutable source

| Field | Locked value |
| --- | --- |
| Canonical upstream | `https://github.com/pengjas/posteda-bench.git` |
| Repository owner / maintainer identity | GitHub user `pengjas`; repository is anonymized for a NeurIPS 2026 submission |
| Default branch observed | `main` |
| Required commit | `51884e5f20e6e199219cec87c1c779a3dfab95bc` |
| Commit timestamp | `2026-07-28T00:12:49Z` |
| Required Git tree | `c5ccdf6e7165bcc9749e10dacd023bfe5cde20a4` |
| Version represented by repository | README and commit history describe PostEDA-Bench v1.1.0; no GitHub tag or release object exists |
| License | CC BY 4.0, `LICENSE` SHA-256 `ef11c38a4df050ec831b0186a6d73fe72e2dadcfe0ea7563394596b8e75a1526` |
| Redistribution conclusion | **Green with attribution** for the repository material; retain the license and identify local derived evaluation separately |

The benchmark contains 145 tasks: 70 DRC tasks over GDS/KLayout and 75 PPA
tasks over RTL/configuration/OpenROAD-flow-scripts. Hidden `info.json` data is
scorer-only and must never enter an Agent prompt, diagnosis input, retrieval
corpus, or user-visible evidence packet.

## Native entrypoints and scoring

- DRC benchmark harness: `eval/eval_drc_sr.sh`.
- PPA benchmark harness: `eval/eval_ppa_sr.sh`.
- PPA metric collector: `eval/ppa_metric_collection.py`.
- Functional-equivalence check: `eval/equiv/check_equiv.sh`.
- Reference agents live below `agents/drc/**` and `agents/ppa/**`.

Official reported outputs are success rate, DRC error-reduction rate, PPA
violation-reduction rate, functional-equivalence status, cost and reasoning
process statistics. A platform-only diagnostic score is a derived evaluation;
it must not be called official PostEDA-Bench SR/ERR/VRR.

## Dependencies, environment, credentials and resources

- Linux, Bash >= 4.3, Python >= 3.10; reference environment is Python 3.11.
- `jq`, `bc`, `tput`, `realpath`, `basename`.
- KLayout >= 0.28 for DRC; locally observed candidate is KLayout 0.30.6.
- OpenROAD-flow-scripts with ASAP7 and Yosys >= 0.30 for PPA.
- Pinned Python requirements include LangChain/LangGraph/OpenAI, NumPy,
  optional Pillow, Google GenAI and scikit-learn.
- Reference agents may require `OPENAI_API_KEY`, `GOOGLE_API_KEY`, or a local
  vLLM endpoint. Credentials/network are not required or admitted for the
  initial dataset/evaluator smoke.
- Native defaults are five attempts per task, five parallel DRC agents or two
  parallel PPA agents, 16 PPA iterations and 1800 seconds per OpenROAD call.
  None of those expensive defaults is authorized by this intake.

## Security and write-behaviour review

The public source was inspected through the pinned GitHub tree/API before any
checkout or execution. Relevant risks are:

1. Both harnesses copy task data into work directories and recursively remove
   those directories during cleanup.
2. The PPA harness can forcibly remove Docker containers and temporary
   directories left by killed runs.
3. DRC tools generate Python scripts and invoke `klayout -b -r`; they modify
   GDS and DRC-report files.
4. `agents/ppa/tools/run_openroad.py` builds a Make command and invokes it with
   `subprocess.run(..., shell=True)`.
5. Reference agents call external model providers or local vLLM services and
   edit benchmark copies of GDS, RTL and configuration.
6. Full evaluation writes logs, results, reports, cost files and aggregate
   summaries; symlink-following copies appear in the harnesses.

Accordingly, the upstream shell harness and reference agents are not plugin
entrypoints. No downloaded script may receive a shared repository path, Docker
authority, credentials, network access, or unrestricted deletion target. Any
native smoke runs in a newly allocated isolated directory with resolved paths.

## Smallest adapter boundary

The first admitted use is a benchmark evaluator, not a product capability and
not an EDA repair plugin:

```text
pinned task ID + immutable prompt/input/report artifacts
  -> hidden-label firewall
  -> platform StageAnalysis / DiagnosisReport / RecoveryDecision
  -> isolated scorer adapter
  -> per-field score + evidence references + benchmark provenance
```

Input mapping exposes only the task's public prompt and public EDA artifacts.
The adapter resolves paths below the pinned checkout and copies only an
allowlisted task into a Runtime workspace. Hidden `info.json` is provided only
to the scorer after the platform output is sealed. Output contains typed
domain/blocker/count/action-class matches, abstentions, evidence integrity and
failure details.

The first bounded evaluation should use one DRC task whose precomputed report
can be inspected without changing GDS. It evaluates diagnosis grounding and a
typed next-action decision. It does not run a reference LLM, modify layout,
run a PPA search, or claim official benchmark success.

## Admission sequence

1. Create a clean detached checkout of the exact commit and verify HEAD/tree,
   license and locked file hashes.
2. Run a native, isolated, single-task DRC evaluator smoke using the upstream
   task files and KLayout/report logic; preserve stdout/stderr and hashes.
3. Define dependency-free benchmark request/result contracts.
4. Add a bounded adapter that cannot expose hidden labels to the analyzer.
5. Evaluate one deterministic platform diagnosis/decision and preserve a
   separate, clearly labelled derived score.
6. Only then consider a registered benchmark capability or a larger frozen
   task sample.

## Stop conditions

Stop if checkout identity/license drifts; hidden labels cannot be separated;
the native evaluator requires Docker or destructive access outside an isolated
workspace; the task requires modifying protected platform inputs; or a useful
score would require inventing expected answers absent from upstream ground
truth. In that case retain source-audit findings and do not claim PostEDA-Bench
evaluation.

## Rollback

Remove only the benchmark registry/adapter route added by a later slice.
Preserve this intake, source lock, Runtime receipts and smoke artifacts.
Delete an ignored checkout only after proving no evidence record references it.

## Completed admission evidence

Native single-task smoke:

```text
var/evidence/posteda-native-diagnostic-20260905-r1/summary.json
SHA-256 daa938e6d951918b891704025b0eabe9cc70222e6de1fcf58a608fcd3df9b365
```

Bounded two-stage Runtime evaluation:

```text
var/evidence/posteda-platform-diagnostic-20260905-r1/summary.json
SHA-256 1684cbea302c22100ad08bfa0efe50a283b42fe758d617c44281c299b1d04a3b
```

Admission remains limited to `drc_essential/L1/q1` and the derived diagnostic
score. No repair agent, full harness, PPA task or official metric is admitted.
