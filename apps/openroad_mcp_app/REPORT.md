# OpenROAD MCP App 功能报告

## 官方功能和使用场景

OpenROAD-MCP 是一个 MCP Server，把 OpenROAD/ORFS 能力提供给支持 MCP 的 AI 客户端。官方 1.1.0 提供 15 个工具，覆盖：

- 交互式 OpenROAD 查询和状态修改；
- 创建、列出、检查、终止交互 Session；
- Session 历史、输出搜索和运行指标；
- ORFS 报告图列表和内联读取；
- ORFS 指标读取；
- ORFS 阶段任务启动、查询和取消。

典型场景是让 AI 助手边问边看物理设计状态、分析报告图、调试 Tcl/OpenROAD 命令，或启动一个受控 ORFS 阶段。

## 本 App 支持的能力

本 App 使用官方固定构建的 MCP stdio 协议，`GET /api/tools` 返回官方工具目录，`POST /api/tool` 统一转发全部 15 个工具。界面拆成：首页、Sessions、Reports、ORFS Runs、Tools 五个入口。

- 查询工具直接执行；
- 状态修改和任务工具必须显式确认；
- Session、报告、任务和工具目录分开显示；
- 图像作为真实 MCP image block 预览；
- OpenROAD 命令不会由浏览器直接执行。

## 相对官方客户端的改动

- 将官方混合工具列表改成按用户任务分组的 App 页面；
- 首页只显示连接状态和入口；
- 增加读写权限标签和修改命令确认；
- 保留 MCP 原始结构化输出，方便排查；
- 提供移动端响应式布局和空/错误状态；
- 使用服务器端长驻 stdio MCP 进程，支持同一 App 内的 Session 连续操作。

## 真实验证

- 官方 MCP `tools/list` 返回 15 个工具；
- `list_interactive_sessions`、`get_session_metrics`、`list_report_images`、`read_orfs_metrics` 均通过 App 网关调用成功；
- `sky130hd/ibex/base` 返回 10 张报告图；
- Firefox 实际点击 Sessions、Reports、ORFS Runs、Tools 页面，无 JavaScript 错误；Tools 页面显示 15 项，Reports 页面显示 10 个图像按钮。
