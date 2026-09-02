# P5 ORFS-Agent bounded Runtime admission

Status: **accepted bounded integration smoke**.  This is not a QoR-improvement
study, an upstream-paper reproduction, or an admission of a local optimizer.

## Frozen inputs and source

- Platform commit: `38f7499` plus the P5 uncommitted implementation slice.
- ORFS-Agent source: clean detached checkout
  `/tmp/orfs-agent-p5-source.EJSdUC/repo` at
  `730f1fa11f9c17c0aaac332412af2b2538f42e9b`.
- License SHA-256:
  `243601633b171278cd98f9ea495cbfc74aad9d7fc062c6e7c81e20d1fc44a22f`.
- ORFS/OpenROAD: local managed ORFS commit
  `51ad1231a231ee85234c06db807688d029b85c35`; OpenROAD
  `26Q1-1961-g63ed2e0fe5` after sourcing the managed GCC12/OpenROAD scripts.
- Input: `tests/fixtures/p2_mux_2to1.v`, Nangate45, 10 ns clock and a fixed
  20 um minimum die size needed for a valid PDN on this intentionally tiny RTL.

## Protocol and result

Evidence root: `/tmp/openroad-p5-admission-final.2OqJ4k`.
`admission_summary.json` SHA-256 is
`077705bf27343d78146f2dcc1e17cbc339c46f229e72c7703e074d54740dbc7a`.

The smoke ran three repeated baseline seeds (101, 211, 307), then two frozen,
parameter-distinct observation probes (`core_utilization_pct` 45 and 65).
The managed model selected only training row IDs; the pinned, unchanged
ORFS-Agent workbench performed GP/EI proposal.  The proposed allowlisted
vector was executed once by Runtime under the same protected evaluator.

All seven Runtime tasks succeeded: three baseline ORFS runs, two probe ORFS
runs, the ORFS-Agent adapter task, and the candidate ORFS run.  The six ORFS
runs emitted immutable common-evaluator-v3 artifacts and passed their
artifact-hash checks.  The source checkout remained clean before and after.

This establishes the intended edge:

`Runtime evidence -> adapter -> managed typed policy -> upstream GP/EI -> Runtime ORFS -> protected evaluator`.

It deliberately makes no numerical comparison or PPA claim.  A future
comparative campaign must use the separately frozen paper-comparable protocol
with its required diverse warm-up and repeat policy; neither repeated baseline
receipts nor this smoke may be relabelled as such evidence.

## Recovery and rollback

`scripts/run_orfs_agent_admission.py --resume-pipeline-id <id>` resumes the
durable checkpoint in an existing output root rather than re-running completed
ORFS tasks.  Roll back this slice with a normal Git revert; preserve the raw
evidence roots, including earlier failed diagnostics, as historical evidence.
