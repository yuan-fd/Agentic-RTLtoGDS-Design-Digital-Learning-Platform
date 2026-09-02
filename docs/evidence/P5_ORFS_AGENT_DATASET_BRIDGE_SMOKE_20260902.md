# P5 ORFS-Agent dataset-bridge bounded Runtime smoke

Date: 2026-09-02

This is an integration smoke only. It does not execute ORFS, invoke upstream
GP/EI, measure QoR, or support a performance claim.

## Immutable identities

- Platform commit: `90671899653bdb746170185bed023dfc32d2a7cd`
- Upstream: `https://github.com/ABKGroup/ORFS-Agent.git`
- Upstream commit: `730f1fa11f9c17c0aaac332412af2b2538f42e9b`
- Upstream source state before/after: clean detached checkout (empty porcelain
  output).
- OpenROAD environment loaded from
  `/share/home/wangza/opt/openroad/scripts/env-gcc12.sh` and
  `/share/home/wangza/opt/openroad/scripts/openroad_env.sh`.

## Bounded execution

`WorkflowRuntime` executed the `optimizer.l2.dataset-bridge` manifest. Runtime
created the attempt-owned protocol receipt, injected its digest, and registered
all evidence only after adapter completion and receipt revalidation.

- Run id: `72279e18f09d4d6994e6bd3ffd28df70`
- Terminal status: `succeeded`
- Attempt workspace:
  `/tmp/orfs-agent-p5-final.FHmQkv/work/72279e18f09d4d6994e6bd3ffd28df70/0ef294dde82a4dfd85be00061d0d4f80/attempt-1`

| Runtime artifact | SHA-256 |
| --- | --- |
| `runtime_protocol_receipt.json` | `9257c4a6c3fa480ba86c70123c248f79064113dd0b0dc2cd468b58b140250b6a` |
| `orfs_agent_output.json` | `99660b66d23d4e39a7c76cb71ccab880058020fe7e904ab6b7d732e7942fc57e` |
| `orfs_agent_input_manifest.json` | `6b0a0a4cbce5b08cf19c9bd87037d67c6749abaf9e5ddf967df069bd7df02d16` |
| `orfs_agent_source_lock.json` | `1d063b81262d18df6459e8b9a6cc169d479c6a58dc492c017873a3e45ca44869` |

Rollback: `git revert` the P5 dataset-bridge commits beginning at `49791a5`.
