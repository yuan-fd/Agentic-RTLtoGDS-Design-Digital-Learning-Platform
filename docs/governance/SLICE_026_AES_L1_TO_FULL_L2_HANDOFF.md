# Slice 026 — same-session AES L1 to complete L2 handoff

## Intended architectural change

Continue the exact managed AES/Sky130HD L1 session accepted in Slice 022,
measure one policy-registered candidate, compare protected evaluator facts,
record reflection and escalation, configure the full ORFS-Agent protocol, and
prove that an independent worker can reconstruct and advance its durable
controller.

The Slice 022 evidence directory remains immutable. This slice takes a SQLite
backup of its durable control-plane state into a new evidence directory while
preserving the same session, trace, Goal, baseline run, and baseline artifact
references. New candidate and L2 records are written only to that continuation.

## File boundary

- `scripts/run_l1_aes_to_l2_handoff_acceptance.py`
- focused L1/L2 handoff and worker tests, if a defect requires correction
- this evidence record

No parameter-domain, optimizer, evaluator, Runtime, RTL, PDK, SDC, or ORFS
source change is planned.

## Before and after dependency edge

Before: the real L1 baseline evidence and the full-campaign controller had
separate integration proofs.

After: one durable session identity links baseline -> registered candidate ->
protected comparison -> reflection -> L2 authorization -> exact 12-D
variable-clock domain/configuration -> independent worker transition.

## Acceptance evidence

Evidence root:

`var/evidence/l1-aes-to-full-l2-handoff-20260904-r2`

Summary SHA-256:

`5e4110bf3afe9cfe8f859016599672e705059c70b819fc203425a35d13c171ed`

Durable identities:

- session: `l1-session-539dee89d9a34bd4af9072cd494c9b38`
- trace: `l1-trace-09307dee9ac7460ca9e84f0a58e4b568`
- Goal: `goal-539dee89d9a34bd4af9072cd494c9b38`
- accepted Slice 022 baseline run:
  `4934a4baebe74ac0bb5943a37a24942a`
- real L1 candidate run: `e7279d7da56e4206befdd0d4f926bc10`
- L2 authorization: `l2-auth-75dfdef8d55729a83eb27e92`
- full-campaign pipeline:
  `pipeline-6eec7fb95cf24d61aff507723b3f070a`
- independently submitted upstream initializer:
  `02ecdcb9c5e849d3b51940b02fff84cc`

The candidate changed only registered `place_density`, from 0.60 to 0.50.
Runtime and its protected evaluator succeeded. All 25 registered artifacts
have unique store keys and were re-read from the attempt workspace; recomputed
sizes and SHA-256 values have zero mismatches. The sole official QoR artifact:

- artifact id: `35758cd86d574dc4ad1d196210f343fd`
- SHA-256:
  `6364bacb162cf3c6156eda9fa0e82748f9fb63b2310d2d4b555648381048552b`
- evaluation id:
  `e15f55eac55da5b004a766437b15326c30fd5eb84a5c7bc0ae7759b1b5f3cf24`
- producer: `protected-orfs-evaluator`
- Runtime authority: `protected_evaluator`

Canonical comparison:

| Metric | Baseline | Candidate | Interpretation |
| --- | ---: | ---: | --- |
| setup WNS (ns) | -0.240581 | -0.103799 | +0.136782 ns improvement; still negative |
| area (um2) | 122809 | 123263 | 1.003697x baseline, below 1.03 cap |
| power (W) | 0.418987 | 0.415206 | -0.003781 W |
| DRC errors | 0 | 0 | constraint retained |

Both Runtime runs succeeded, but both protected evaluations remain
`feasible=false` because setup WNS is negative (and retain the previously
documented incomplete paper synth-JSON diagnostic). The M1 reflection accepts
the bounded candidate as an improvement under DRC/area limits; it does not
claim the timing target is met or that PPA superiority is established.

Full L2 configuration retains exactly:

- 12 parameters:
  `CLK, UTIL, TNS_End_Percent, GP_PAD, DP_PAD, DPO, PIN_ADJ, UP_ADJ,
  LB_ADDON, HIER_SYNTH, CTS_CSIZE, CTS_CDIA`;
- variable-clock semantics (`CLK` range remains live);
- objective set `ECP, DWL, COMBO` (this campaign selects ECP);
- upstream initializer;
- 50 initial measurements, five rounds of five GP/EI suggestions, and three
  independent confirmations: 78 physical measurements total; and
- authorized parallelism 4, initialization/screening seed 401, confirmation
  seeds 503/601/699.

The worker ran as a separate process reconstructed only from pinned operator
arguments and SQLite state. It advanced revision 1 to revision 2 and created
one queued `upstream_full_initialize` Runtime task. The acceptance runner then
recovered from two post-transition assertion/serialization defects without
rerunning the candidate or submitting a second initializer. Recovery details:

- `runner-recovery.json` SHA-256:
  `5b3614915bbdfa39b4b821210e68cab509b4d0c07816fd63aeffe35d0e8ec68c`
- final Runtime inventory: two succeeded L1 runs plus one queued initializer.

The preceding r1 intake failure is retained at
`var/evidence/l1-aes-to-full-l2-handoff-20260904-r1`; its factory rejected the
ordinary Yosys wrapper because its compiled datdir did not resolve to the
admitted installation. No run was created. Failure-record SHA-256:
`263d1bb1917788a6f0d1dd80c7c105cabf4dfb7b97b239eb3fca290f4cc8304d`.

Focused L1/handoff/worker/full-campaign tests:

```text
44 passed in 17.52s
```

## Protected components and unrelated behavior

The managed 7-file AES RTL bundle, 4.5 ns L1 SDC, paper ORFS/PDK, evaluator,
and external optimizer checkout must remain byte-identical. The L1 candidate
may change only a registered flow parameter. L2 configuration must retain all
12 upstream dimensions and the complete `50 + 5*5 + 3 = 78` measurement
budget.

Post-run receipts confirm:

- design bundle SHA-256:
  `d5c87023d12199cd3d28b815979b7611b0986091fef59abc4e591f18edfc2fc0`
- SDC SHA-256:
  `aa675a0a1ce100a655b230f623a5fb3bdc4e32be92994844abce7243ad9c9d5f`
- ORFS commit: `ce8d36a7fef0ab9c47d183bcf078bce0f60f5a54`
- ORFS-Agent commit: `730f1fa11f9c17c0aaac332412af2b2538f42e9b`
- both external worktrees remained clean.

## Rollback

Remove only this slice's new continuation evidence and revert its runner/doc.
The immutable Slice 022 baseline evidence remains the rollback anchor.
