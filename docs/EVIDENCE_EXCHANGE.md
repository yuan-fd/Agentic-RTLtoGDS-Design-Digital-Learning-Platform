# Evidence Exchange v0.1

Evidence Exchange 是教学层和 v2 之间的元数据边界。它只保存引用、哈希、
协议和声明范围；原始 RTL、GDS、ODB、netlist、日志和报告由 v2 持有。

## 最小记录

| 字段 | 约束 |
| --- | --- |
| `evidence_id` | 教学层唯一标识 |
| `owner_id` | v2 identity/session 对应的用户 |
| `spec_id` | 冻结 SpecIR |
| `candidate_id` | RTL candidate/version |
| `run_id` | v2 Runtime run |
| `artifact_ids` | 至少一个 `artifact:` 引用 |
| `evidence_kind` | 受限的证据类型 |
| `status` | pending/succeeded/failed/incomplete/rejected |
| `sha256` | 小写 SHA-256 |
| `toolchain_digest` | 工具链身份摘要 |
| `protocol_digest` | recipe/protocol 摘要 |
| `claim_boundary` | 证据可支持的声明范围 |
| `created_at` | 带时区 ISO-8601 时间 |

`status=succeeded` 并不意味着任意规格都成功；它只意味着记录绑定的那次
运行和 artifact 完成。缺少 artifact、GDS 或 evaluator 通过条件的结果必须
保持 `incomplete` 或 `rejected`。

## 绑定规则

1. EvidenceRef 必须绑定单一 candidate、spec 和 run。
2. RTLVersion 改变会使旧 verification evidence 对新版本失效。
3. 展示层只能读取 v2 返回的 artifact/metric，不得从旧数据库拼接 QoR。
4. 图形渲染必须引用 artifact hash；没有渲染依赖时返回不可用状态。
5. identity/session 以 v2 为唯一来源，教学层不复制用户身份。
