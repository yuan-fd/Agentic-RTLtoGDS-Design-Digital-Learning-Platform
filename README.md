# Agentic RTL-to-GDS Learning Platform

> **English** · [中文](README.zh-CN.md)

An educational platform for showing how an LLM participates in digital design:

```text
natural-language specification → RTL → verification → ORFS → GDS → evidence
```

This repository is a teaching product, not a paper-research platform, an
optimizer publication platform, or a general entry point for every group
project. Earlier experiments and integrations remain available as classified
showcase or historical evidence; they are not silently promoted to the new
product path.

## Execution boundary

`openroad-platform-v2` is the execution base. The teaching layer communicates
with it over HTTP and does not import its source, open its database, duplicate
its Runtime, or own its raw artifacts. v2 remains domain-neutral and owns:

- tasks, staged inputs and isolated workspaces;
- process lifecycle, cancellation and timeout;
- artifacts, metrics, evidence and provenance;
- identity/session and Toolkit admission.

The teaching layer owns `SpecIR`, RTL versions, frozen verification packages,
candidate records, PDK capability records, script proposals and evidence
references. The browser receives no model API key. No-auth mode is for local
development only.

## Teaching modules

| Module | Purpose | Status |
| --- | --- | --- |
| Teaching Hub | Navigation, exercise catalog, history and Evidence Exchange read model | foundation |
| M1 · LLM → RTL → GDS | Complete guided flow from a frozen specification to real GDS | first vertical slice |
| M2 · Direct LLM vs RTLScout | Same SpecIR, verification package and RTL-to-GDS protocol | planned after M1 |
| M3 · Fixed baseline vs ORFS-Agent | Full observation and budget comparison under a frozen protocol | planned after M1 |
| M4 · Flow / Recipe Scripting Lab | Confirmed, allowlisted Tcl/Python recipe proposals | planned after M1 |

The first product milestone is M1: one fixed Course Lab exercise and one
natural-language single-clock FSM must complete through Nangate45 to GDS. A
failed generation, verification, toolchain, PDK, evaluator or GDS step is a
real failed/incomplete state; the UI never substitutes a default PDK, old run,
fallback image or fabricated QoR.

## Design directories

**Course Lab** contains ten bounded exercises—mux/decoder, priority encoder,
adder/subtractor, ALU, edge detector, counter, shift register, FIFO, UART TX,
and sequence detector/FSM. Every exercise has a frozen specification, oracle,
reference RTL, recipe, difficulty, PDK support and real smoke status.

**ORFS Showcase** contains larger fixed designs such as GCD, AES, Ibex,
RISC-V, JPEG, SPI, I2C GPIO, UART, Ethernet MAC and TinyRocket/CVA6. Showcase
designs demonstrate real IP and layout/tool capabilities; they are not
promises that arbitrary natural language can generate them.

## UI direction

The product UI is a compact Teaching Hub and workbench, not an infinite
dashboard:

- left: frozen Spec and editable RTL;
- center: stage timeline and current run;
- right: evidence, errors, explanations and next action;
- bottom: netlist, real DEF/GDS rendering, reports and QoR.

The visual system is white, high-contrast and restrained: black text, clear
sans-serif headings, monospace code/logs, few status colors, no blue full-page
background, gradients, decorative shadows, or fake visualizations. Every
rendered result points to an artifact hash; unavailable rendering dependencies
produce an explicit unavailable state.

## Repository map

```text
packages/contracts/       teaching and execution boundary contracts
apps/                     existing services, being separated by module
integrations/             admitted external tool intake records
docs/                     product specification, module catalog and governance
tests/                    contract and regression tests
```

Canonical Slice 0 documents:

- [Teaching platform specification](docs/TEACHING_PLATFORM_SPEC.md)
- [Module catalog](docs/TEACHING_MODULE_CATALOG.md)
- [PDK capability matrix](docs/PDK_CAPABILITY_MATRIX.md)
- [Evidence Exchange](docs/EVIDENCE_EXCHANGE.md)
- [Cleanup inventory](docs/governance/LEGACY_CLEANUP_INVENTORY.md)
- [HTTP boundary ADR](docs/adr/ADR-0004-teaching-layer-over-v2-http.md)

## Development and verification

```bash
python3 -m pytest -q tests/test_teaching_contracts.py
python3 -m pytest -q
```

## Private M1 acceptance

Start `openroad-platform-v2` on `127.0.0.1:8700`, then from this repository:

```bash
OPENROAD_V2_URL=http://127.0.0.1:8700 \
  bash scripts/start_teaching_platform.sh
```

M1 listens on `127.0.0.1:8101`. From an operator workstation, expose only the
two private ports through SSH:

```bash
ssh -L 18101:127.0.0.1:8101 -L 18700:127.0.0.1:8700 user@server
```

Then open `http://127.0.0.1:18101`. The v2 token stays on the server; no-auth
mode is for local development only.

The second command includes historical/integration checks that depend on local
toolchain fixtures. A complete run must report those environmental failures
explicitly; they must not be hidden by compatibility paths or skipped result
substitution.

Changes are developed in small slices. Each teaching module will eventually
have its own `pyproject.toml`, process entrypoint, database, smoke test,
contract tests and integration tests. A module may communicate with v2 through
the HTTP client only and may not import a sibling app or open the v2 database.
