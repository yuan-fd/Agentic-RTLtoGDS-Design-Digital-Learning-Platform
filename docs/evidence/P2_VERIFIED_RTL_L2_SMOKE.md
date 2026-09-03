# P2 verified-RTL to external-L2 bounded smoke

Date: 2026-09-02  
Result: accepted (admission smoke only; no QoR claim)

## Scope

The smoke reads a pre-existing Runtime-succeeded RTLScout-v2 SpecIR run,
verifies its managed artifact hash, then in a new isolated state directory runs
the current compile/lint and frozen-testbench simulation plugins.  Only after
both terminal Runtime records and their report artifacts are collected does it
create the external ORFS-Agent L2 checkpoint.

It does **not** execute an optimizer candidate or compare QoR; it proves the
P2 admission boundary, not PPA superiority.

## Evidence

- pinned source Runtime DB SHA-256:
  `b04a76268ac8409550c3c3de7f54200e6b8234b7b06ef48e7f5716b3df6fdf91`
- source RTLScout-v2 Runtime run: `dd35a2c05c9e4550a4c7ef39a90f247a`
- source Runtime record SHA-256:
  `c2daab0b6596939ae0b5565c906a2f88f7b44cfb23044495c9ec6d8714302819`
- source RTL artifact: `db014d7d79494910890b9fe07bf6ca37`, store key
  `outputs/design.sv`, under its recorded Runtime attempt workspace
- SpecIR: `specir-gcd-codex-e2e-final3`
- selected verified candidate: `candidate-6e181220246246de9b35b46596cc7d08`
- managed RTL SHA-256: `560f4327b68ca3a1a25633b1d98418252dc0c629ddfd14483486a340139205f4`
- compile/lint Runtime run: `6099ad549ab64546a66b5395b972f68e` (`succeeded`)
- simulation Runtime run: `e773954fc4ea424da02095e5ca91ae36` (`succeeded`)
- L2 checkpoint: `pipeline-8077c385d00742429899ac8177fb38ae`
- isolated Runtime DB SHA-256:
  `7754552b4d1931c7c171aee9df0c7381764595c672613f90716a067635fee326`
- summary SHA-256:
  `a4965ebf14a4b53b862ad8041cae695202cfcc4dc6309a04778b14315dffc648`
- full machine-readable result:
  `var/p2-verified-l2-smoke-20260902-contained/acceptance_summary.json`

The two append-only candidate checks retain their respective Runtime report
artifact references and SHA-256 values.  The L2 checkpoint retains SpecIR,
candidate, verification Runtime run and RTL hash provenance.

## Reproduction

Run `scripts/run_p2_verified_l2_smoke.py` with a new empty `--output-root`.
It fails closed if the pinned source Runtime DB hash changes, verifies the
source run's recorded RTL artifact before importing it, and never writes to the
historical source DB or its workspace.
