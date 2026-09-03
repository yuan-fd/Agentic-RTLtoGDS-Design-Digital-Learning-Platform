# Slice 017 — ORFS-Agent paper candidate execution adapter

Status: **implementation complete; toolchain-dependent execution verification pending**

## Problem

The old ORFS-Agent bridge materialized observation data and invoked the pinned
upstream GP/EI workbench only across a legacy shared parameter intersection.
It could not execute the paper's full candidate: `CLK`, `PIN_ADJ`, `UP_ADJ`,
and `HIER_SYNTH` were removed before Runtime.  The original upstream launcher
cannot safely be run as-is because it rewrites a shared Makefile, cleans shared
results and dispatches to named SSH machines.

## Change boundary

Added only:

- `integrations/orfs_agent/orfs_agent_reproduction_adapter.py`
- `packages/execution/src/openroad_platform_execution/orfs_agent_reproduction_plugin.py`
- focused tests for the 12-field contract and manifest.

The old bridge, evaluator, scheduler, API and UI were not changed.

## Before / after dependency edge

Before:

```text
legacy platform 5/8-D projection -> ORFS-Agent GP/EI -> legacy ORFS runner
```

After:

```text
pinned upstream 12-D candidate -> reproduction adapter -> private paper-flow copy
  -> upstream-style make tunereport -> raw reports / materialization receipt
```

The adapter does not import, implement or replace GP/EI.  It is an execution
translation boundary only.

The associated `orfs-agent-paper-policy` Adapter invokes the pinned upstream
`analyst_agent_workbench.py` GP + EI routine over its unmodified 12-D
`constraints.json`.  The platform-managed `gpt-5.6-terra` component can only
select which already-measured rows train that routine; it cannot emit numeric
candidates or command text.  This is a model-substituted reproduction of the
paper's Claude analyst, and must be labelled as such.  The proposal trace
records selected row ids, model rationale, GP/EI seed, raw upstream response,
and the 12-D candidate list.

## Validation performed

- Syntax compilation of the Adapter and manifest factory.
- Five focused tests passed in the isolated ORFS-Agent Python environment:
  full-field preservation, no legacy padding projection, rejection of malformed
  candidates, task preservation and manifest construction.
- Candidate validation accepts the native upstream range and candidate-specific
  clock.  It intentionally does not add a fixed-SDC gate.

## Pending acceptance evidence

The pinned OpenROAD/Yosys binaries are being built in a separate user-owned
prefix.  The first build attempt using the server's Boost 1.87 reached the
`dst` module and failed because this 2024 OpenROAD revision uses older Asio
APIs that Boost 1.87 no longer provides.  That build and its log are retained
at `var/toolchains/orfs-ce8d36a-paper-build-20260902/`; no upstream source was
patched.

An initial idea to use Boost 1.74 was rejected before compilation: this pinned
OpenROAD source itself declares `find_package(Boost 1.78 REQUIRED)`, and its
own `etc/DependencyInstaller.sh` pins Boost 1.80.0 with MD5
`077f074743ea7b0cb49c6ed43953ae95`.  The active isolated rebuild therefore
uses that upstream-specified Boost 1.80.0, not 1.74 or the server Boost 1.87.

The first Boost 1.80 build contained only the components installed by the
upstream dependency helper.  Its OpenROAD build exposed a CMake transitive
dependency from `Boost::thread` to `Boost::chrono` and `Boost::atomic`.
Those two Boost 1.80 components were added to the same isolated prefix; no
OpenROAD source was changed.  A separate, clean OpenROAD runtime build uses
`-DENABLE_TESTS=OFF`: this excludes OpenROAD's developer unit-test targets,
not any ORFS flow stage, and prevents a test-only link target from being part
of the reproduction binary.  The prior failed build directories and logs are
retained as evidence.

After the pinned binaries build, the required sequence is:

1. native one-candidate `make tunereport`;
2. same candidate through `ProcessAdapter` / Runtime;
3. receipt proving all 12 variables reach the generated ORFS environment;
4. bounded multi-candidate GP/EI loop.

## Rollback

No active path was replaced.  Do not register the new manifest in application
composition; removing this manifest factory from composition disables the new
capability without altering any historical evidence.
