# `rtl-sim` v2 Toolkit

This first-party Toolkit runs a frozen testbench/oracle against staged RTL
using fixed Icarus Verilog and `vvp` entrypoints. The testbench is an artifact
bound to the M1 `VerificationPackage`; it is never generated from candidate
RTL and never accepted from a browser path.

The manifest is a candidate only. v2 admission requires operator review,
Icarus native smoke and platform smoke. Until admission, M1 reports simulation
unavailable instead of treating compile/lint as functional verification.

```bash
python3 -m pytest -q integrations/rtl_sim/tests
```
