# P3 three-platform environment and source compatibility admission

Status: passed for environment/source admission; each later capability keeps
its own bounded functional smoke gate.
Date: 2026-09-02

| Platform | Source/entry evidence | Environment conclusion | Execution scope |
| --- | --- | --- | --- |
| ORFS 2D backend | Server-managed `OpenROAD-flow-scripts` at `51ad1231a`; Runtime adapter entry; local authorization lock | GCC12 plus `/share/home/wangza/opt/openroad/deps` environment starts OpenROAD and Yosys; P2 clean Runtime smoke passed | Protected RTL-to-GDS evaluator backend, not product L2 optimizer |
| RTLScout | `.external-src/rtlscout` at `87a00edf`; `run_benchmark.py`; BSD-3-Clause-Clear LICENSE SHA-256 `524ba273c6422513d7096d9d1993552a221cf4f293ec95b14feee6ec9b3662eb` | Python 3.12.4 and Verilator 5.040 present; pinned manifest construction passed with explicit Yosys | P4 owns black-box SpecIR-to-RTL functional smoke |
| TaiWei-Pin-3D | `.external-src/taiwei-pin-3d` at `db201367`; BSD-3-Clause LICENSE hash agrees with lock | Independent `.tools/taiwei-official-3d` GCC12 build starts pinned OpenROAD `305d3ba2` and Yosys `77005b69`; current binary hash rebaselined in lock | Independent 3D extension only; P8 owns 3D GDS/metric smoke |

## Boundaries

This admission does not merge 2D and 3D toolchains, expose a local optimizer,
or claim functional correctness, QoR improvement, 3D sign-off, or PPA
superiority. The TaiWei PDK data remains private-local only as recorded in its
license audit. Raw smoke artifacts stay in their Runtime workspaces.

## Rollback

Revert the P3 lock/document commit. No external source, toolchain, PDK, or
historical evidence is removed.
