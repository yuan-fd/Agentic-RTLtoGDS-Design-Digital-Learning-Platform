# OpenROAD 平台

> [English](README.md) · **中文**

一个面向可复现实验的、证据优先的插件化芯片设计控制平面。

## 当前产品边界

平台只负责版本化契约、受控 Runtime、Artifact 与溯源、受保护 QoR
评估、公平实验协议和插件准入；它不重写上游研究算法。

当前支持的产品路径为：

```text
自然语言规格 → SpecIR → 平台托管 RTLScout → 独立验证 → 已验证 RTL
→ DesignGoal / typed policy → 已准入 ORFS-Agent 插件 → immutable TaskSpec
→ Workflow Runtime → 原始 artifacts → 受保护 QoR
```

- RTLScout 是唯一的产品 RTL 创建后端；自然语言绝不直接变成 shell/Tcl。
- ORFS-Agent 是唯一的 L2 产品设计空间探索插件；本地 BO/GP、stateful
  portfolio、ORFS AutoTuner 和 seeded random 仅可用于预注册、同预算的研究比较。
- TaiWei 3D 是独立插件工作流，不属于 2D 的 L1/L2 状态机。
- L3/L4 白盒修复、源码修改和算法演化仅保留未来契约与历史证据，不在当前产品中开放。
- 现有 Web workspace 是冻结的 legacy UI；新的 L1 trace workspace 尚待建设。

## 当前能力状态

| 能力 | 状态 | 边界 |
| --- | --- | --- |
| 2D ORFS Runtime | 已验证 | Runtime、原始产物和 protected evaluator 是唯一事实来源 |
| 自然语言 SpecIR / RTLScout | 已验证 | 需经过独立验证后才是目标产品 RTL 路径 |
| ORFS-Agent L2 | 已准入 | 固定源码、受限适配器、Runtime 与 protected QoR |
| TaiWei 3D | 独立插件 | 需使用其独立工具链与准入记录 |
| 本地 BO/GP / 演化代码 | 历史研究 | 不得成为产品默认算法或 L1/L2 fallback |
| L1 Dashboard | 计划中 | 将展示 Goal、ToolCall、Runtime、证据和结构化反思 |

## 重要的过渡限制

`POST /api/designs/import` 目前仍可被普通已认证用户调用；现有
`/api/v2/external-optimizer-loops` 只校验登记设计和所有权，尚未强制
RTLScout/独立验证来源。因此，该 legacy import 暂时仍可绕过“已验证 RTL”
进入 L2。这不是批准的第二产品路径，将由 P2 隔离为 research/fixture
入口并在 L2 拒绝未验证来源。

## 开发与治理

- Contracts 不依赖应用、Runtime 或具体插件。
- LLM 只能提出 `DesignGoal` / `SemanticToolCall`；Policy Gate 决定是否允许，
  Runtime 决定实际执行，evaluator 决定官方 QoR。
- 外部项目须有固定 commit、许可证结论、环境/安全审计、native smoke 和
  bounded platform smoke；无许可证者仅可源码审计。
- 旧代码、实验和文档先分类为 `ACTIVE`、`LEGACY`、`INVALID`、
  `HISTORICAL_EVIDENCE` 或 `UNKNOWN`，不得为了整洁直接删除。

详细规则见 [AGENTS.md](AGENTS.md)、[架构说明](ARCHITECTURE.md)、
[插件指南](docs/PLUGINS.md) 与
[P0 产品边界冻结记录](docs/governance/P0_PRODUCT_BOUNDARY_FREEZE.md)。
