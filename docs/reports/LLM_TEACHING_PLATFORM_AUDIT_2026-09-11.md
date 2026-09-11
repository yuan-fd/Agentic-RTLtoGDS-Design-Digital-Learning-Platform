# LLM Teaching Platform 当前审计

更新：2026-09-11

## 评分

| 维度 | 得分 | 依据 |
|---|---:|---|
| 环境与可运行性 | 8/10 | 环境 doctor、启动脚本、多 worker；真实 ORFS 仍需独立 acceptance |
| Runtime 与证据权威 | 8/10 | Runtime 统一管理运行、artifact、状态；部分旧入口仍保留 |
| 教学模式 | 7/10 | Guided/Open/Challenge 契约、持久化上下文和网页提交已接入 |
| RTL Studio | 6/10 | Direct LLM 与 RTLScout 可登记并共用验证；完整双路径实测比较尚未完成 |
| DSE Lab | 6/10 | Rule Batch、原生 BO/GP、A2 状态链路已接入；四模式统一 campaign 尚未完成 |
| Agent Dashboard | 6/10 | Runtime 状态、动作、批次和 QoR 展示已具备；A2 网页阶段面板缺失 |
| 旧逻辑收敛 | 4/10 | 主要入口仍存在，迁移和归档尚未完成 |
| **总评** | **6.4/10** | 已从杂乱环境进入可验证增量改造阶段，尚未达到发布完成标准 |

## 已有证据

- 全量 Python 测试：852 passed，1 deselected。
- v2 RTL fixture：编译、仿真和 lint 通过。
- Web clarity、RTL comparison、Dashboard 和 Open Lab focused tests 通过。
- 工作区基线、源代码备份和回滚提交已保存。

## 关键缺口

1. 真实服务器环境下的 Direct LLM 与 RTLScout 双路径完整验证和 QoR 比较。
2. Rule Batch、BO/GP、A2-ORFO、baseline 的统一实验详情和公平预算展示。
3. A2-ORFO 网页操作、阶段进度和实时 Agent 面板。
4. 旧 API/服务入口迁移、归档和最终清理。
5. 一次全新、可复现的 RTL→验证→ORFS→QoR→网页 acceptance artifact。

评分只描述当前证据，不代表优化效果或发布资格。
