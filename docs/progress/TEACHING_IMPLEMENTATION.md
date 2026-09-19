# M1 implementation checkpoint

Updated: 2026-09-20

M1 is the active product path. The old API, Web, Workbench, Runtime and
research paths were removed from active main after the M1 acceptance slice.
They remain recoverable through `archive/pre-teaching-platform` and are not
started or exposed by the teaching launcher.

## Real M1 evidence

- Counter verify: `run-63450b6958ef4f978f0222342a90ff62`
- Counter simulation: `run-39ca4050fc124f8cb25e93e104bb2810`
- Counter Nangate45 GDS: `run-eb7501e4c2a34db487a1158c494418a8`
- Sequence detector RTL: `rtl-6f1002440c7749c49e4c2d1c7e58c607`
- Sequence detector verify: `run-1d0e64da23a14834a45ee0e343d6f70e`
- Sequence detector simulation: `run-f94549666e6b4abcb95212bfed16bca1`
- Sequence detector Nangate45 GDS: `run-9a0ad2ca42be44998314ea8d286f548b`

Both designs returned GDS, DEF, ODB, netlist, report and complete QoR from v2;
both had DRC 0. Sequence detector GDS SHA-256 is
`1729e41e588e8be94db544331d310cd5707fd4c7493d6242247775efebb294fe`.

## Browser acceptance

Playwright exercised the real M1 UI through clarification, re-assessment,
freeze, Direct LLM generation, verification, simulation and GDS submission.
The four tested viewports were 1440, 1024, 768 and 320 pixels wide. The
observed page had no console errors, page errors or failed requests. The UI
renders v2 artifact hashes, netlist excerpts, KLayout SVG preview and QoR;
missing artifacts remain unavailable.

## Verification commands

```bash
python3 -m pytest -q
python3 -m pytest -q tests/test_m1_generator.py tests/test_m1_http_api.py \
  tests/test_m1_service.py tests/test_m1_v2_client.py tests/test_m1_web_contract.py \
  tests/test_rtl_frontend_contracts.py tests/test_teaching_contracts.py
```

The v2 repository has its own full test and guardrail suites. The external
`agenticeda-orfs` repository has its own plugin suite. They are not duplicated
in this teaching repository.

## Release gate

The next action is private server acceptance through the documented SSH tunnel.
The v2 and M1 services remain bound to loopback. Public IP exposure and public
domain sharing are not release actions; authenticated sharing requires a later
Cloudflare Access deployment after per-user v2 identity isolation is complete.
