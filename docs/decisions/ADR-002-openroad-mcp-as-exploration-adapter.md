# ADR-002：OpenROAD-MCP 作为受控探索适配器

## 状态

Accepted · 2026-09-13

## 背景

官方 OpenROAD-MCP（仓库提交 `9dc80d3706fbcd8144cccb639fa21af7b933cbf5`，npm
版本 `1.1.0`）提供了我们当前 EDA Console 缺少的交互能力：OpenROAD PTY
Session、Tcl 查询、命令历史、Session 指标、ORFS 指标和报告图片。它的
`interactive_openroad_exec` 与 `run_orfs_stage` 也能修改设计或启动流程。

但官方 Streamable HTTP transport 没有认证；交互 Session 不会自动回收；
`exec` 是默认允许的状态修改入口；独立 flow runner 会写入 ORFS 工作树。
这些边界不适合作为教学平台的直接公网后端。

## 决策

OpenROAD-MCP 只作为 EDA Console 的探索适配器，不替换平台 Runtime。

```text
网页 EDA Console → 平台 MCP Adapter → OpenROAD-MCP（stdio）→ OpenROAD
                         ↓
                  探索记录 / Dashboard

正式实验 → 平台 Runtime → OpenROAD → Evidence / Learning Store
```

规则如下：

1. 生产集成优先启动本地 stdio MCP 子进程，不直接暴露官方 HTTP transport。
2. 用户身份、Session、工作目录和命令历史由平台绑定和隔离。
3. MCP 查询结果标记为“实时探索”，不能直接成为学习库证据。
4. 需要正式运行的操作转换为平台结构化 Runtime 计划，经过用户确认。
5. MCP 的 `run_orfs_stage` 不直接开放；平台 Runtime 是正式流程的唯一执行者。
6. 交互 Session 必须有平台级数量限制和空闲回收。
7. 报告图片和指标优先读取已完成 Runtime 的证据目录，避免重复执行。

## 工具映射

| MCP 工具 | 平台用途 | 默认权限 |
| --- | --- | --- |
| `interactive_openroad_query` | 查询设计状态、时序和约束 | Open Lab 可用 |
| `get_session_history` | 命令回顾和教学解释 | Session 所有者 |
| `get_session_metrics` | Dashboard 资源信息 | Session 所有者 |
| `read_orfs_metrics` | 解释已有 ORFS 指标 | 只读 |
| `list_report_images` / `read_report_image` | Dashboard 图像 | 证据路径受限 |
| `interactive_openroad_exec` | 交互式实验动作 | 结构化计划 + 用户确认 |
| `run_orfs_stage` | 正式流程 | 禁止直通，转 Runtime |
| `cancel_orfs_job` | 任务取消 | 只取消当前用户的 Runtime 任务 |

## 后果

- 新人能在网页里看到真实 OpenROAD 状态和图像，不必自己配置 MCP 客户端。
- Open Lab 获得自由探索能力，同时保留 Runtime 的正式证据边界。
- MCP 的交互状态和 Runtime 的正式状态不会混为一谈。
- 需要新增一个小型适配层和 Session 生命周期管理；不新增第二个 EDA 执行引擎。

## 分阶段验收

1. 隔离启动 MCP stdio，完成版本查询和只读报告查询。
2. 把查询、历史、指标和报告图片投影到现有 EDA Console/Dashboard。
3. 验证用户隔离、路径限制、Session 回收和命令审计。
4. 将一次交互探索升级为 Runtime 正式实验并保存证据。
5. 在 Ibex 课程中展示“探索结果”和“正式 Runtime 证据”的区别。
