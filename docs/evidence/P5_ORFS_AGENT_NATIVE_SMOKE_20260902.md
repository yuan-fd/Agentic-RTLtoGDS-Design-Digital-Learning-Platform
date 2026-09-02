# P5 ORFS-Agent native upstream smoke

Status: **passed native-entrypoint smoke; not an ORFS/PPA run**.

Command (with no Anthropic credential):

```bash
env -u ANTHROPIC_API_KEY .tools/venvs/orfs-agent/bin/python \
  scripts/run_orfs_agent_native_smoke.py \
  --source /tmp/orfs-agent-native-clean.PiTzoI \
  --output /tmp/orfs-agent-native-final.yesymY.json
```

The source was a clean detached checkout before and after execution at
`730f1fa11f9c17c0aaac332412af2b2538f42e9b`; its BSD-3-Clause license SHA-256
was `243601633b171278cd98f9ea495cbfc74aad9d7fc062c6e7c81e20d1fc44a22f`.
The upstream `analyst_agent_workbench.py` hash was
`be44cdc27ab106ded5b2a0661c283da06a5a7908f4ee2296dd36e1669e840738`.

The unmodified upstream `suggest_bayesian_optimization_configs()` consumed two
local 12-field observations and returned one GP/EI configuration.  The JSON
receipt SHA-256 is
`d0f9c93454769c559eef5ece706f14f6088333646a3d9dc12b3e97047974199f`.

The smoke did not invoke SSH, ORFS, network services, a remote launcher or an
Anthropic credential.  It proves only that the pinned upstream GP/EI Python
entrypoint can execute in its isolated environment; the separate bounded
Runtime smoke proves adapter integration and must not be relabelled as a PPA
result.
