# OpenROAD Workbench 规格

## Objective

构建一个终端优先的 OpenROAD 工程调试台。用户启动 Workbench 后进入真实 shell PTY，可运行任意 shell 命令、OpenROAD、Tcl、Python、ORFS 和脚本；同时启动 Web GUI，用于管理设计、Session、运行、文件、日志、报告和结果。Agent 与 TUI 并列，为当前设计上下文生成和解释 Tcl/Python，并在用户确认后写入或执行。官方 OpenROAD-MCP 的全部工具能力必须保留。

## 用户模型

- Design：用户正在处理的设计项目，是顶层实体。
- Terminal Session：一个真实、可持续交互的 PTY 终端窗口；不是聊天，也不是阶段。
- Run/Job：终端中一次可追踪的命令、脚本或 ORFS 任务；一个 Session 可包含多个 Run。
- Artifact：日志、报告、图片、指标、网表等产物。
- Conversation：Agent 对话，可绑定 Design、Session、Run 和选中的 Artifact。

内部 ID 不直接作为用户名称。界面显示设计名、终端名、运行命令、阶段和时间。

## Interfaces

### TUI（主控制面）

- 启动后自动创建或恢复主 shell PTY。
- 支持任意 shell 命令、管道、重定向、环境变量、cd、长任务和 Ctrl-C。
- 支持 OpenROAD/tclsh/python/make 等交互和脚本执行。
- 显示实时 stdout/stderr、命令历史、当前 cwd、PID、退出码和进程状态。
- 右侧提供 Agent 对话；Agent 可读取当前上下文并生成命令/脚本。
- 底部显示当前 Design、Run、阶段和耗时。

### Web GUI（管理和分析面）

- Workbench 启动时打开或输出 Web 地址。
- 不承担主要命令输入；管理共享 Session、Run、Design 和 Artifact。
- 提供文件树、运行状态、调试日志、报告分类、指标表和图像预览。
- 可执行管理动作：创建/重连/终止 Session、停止 Run、打开文件、确认 Agent 提议。
- 与 TUI 共享同一后台状态，不能各自维护副本。

### Agent

- 读取当前 Design、cwd、Session、最近命令/输出、错误、报告和 MCP 结果。
- 支持 OpenROAD QA 和 Prompt-Script 检索，参考 EDA-Corpus 的分类。
- 生成、解释和修改 Tcl/Python；展示 diff。
- 执行前展示命令、cwd、Session 和影响范围，用户确认后执行。

### MCP

完整保留官方 15 个工具：交互式命令、Session、历史、指标、报告图、ORFS 指标、ORFS Job 启动/查询/取消。MCP 是结构化能力层，不替代通用 shell PTY。

## Commands

- 安装：`python3 apps/openroad_workbench/install.py`（写入 `~/bin/openroad-workbench`）
- 启动：`openroad-workbench`（后台 + TUI + Web 同时起）
- 仅后台：`openroad-workbench --no-tui`；状态：`--status`；停止：`--stop`
- 兼容接口：`curl http://127.0.0.1:8780/api/status` 仍返回 `{ok, transport, repo, tool_count}`
- 检查：`node --check web/app.js`、`python3 -m compileall apps/openroad_workbench`
- 验收：`python3 -m openroad_workbench.tests.acceptance`、`python3 -m openroad_workbench.tests.test_tui`
- 官方 MCP：默认路径 `~/openroad-mcp`（可用 `--mcp-repo` 覆盖）

## Architecture

```text
apps/openroad_workbench/
  cli.py                  openroad-workbench 入口（拉起 daemon / TUI）
  backend/
    core.py               单一真相源状态机（designs/sessions/runs/artifacts）
    pty_session.py        真 PTY + shell 集成（OSC 7770 上报命令/cwd/退出码）
    artifacts.py          ORFS 结果索引
    mcp_client.py         官方 MCP stdio 客户端（15 个工具）
    agent.py / corpus.py  可插拔 Agent + 本地语料检索
    server.py             aiohttp REST + SSE + 终端 WebSocket
    daemon.py             常驻后台
  tui/                    Textual 客户端（终端/Agent/状态栏）
  web/                    原生 JS dashboard
  tests/                  acceptance.py, test_tui.py
```

## Success Criteria

1. 用户可以只通过 TUI 运行任意 shell 命令，并实时看到 stdout/stderr。
2. `cd`、环境变量、管道、重定向、长任务和 Ctrl-C 均可用。
3. OpenROAD、Tcl、Python、make 和 ORFS 命令可以在同一终端上下文运行。
4. TUI 和 Web 看到同一个 Session、Run、日志和状态。
5. Web 自动按 Design、阶段和结果性质组织文件和报告，并能预览报告图。
6. Agent 能引用当前上下文和 EDA-Corpus，生成 Tcl/Python 并在确认后执行。
7. 官方 MCP 15 个工具均可调用，没有被 UI 层删减。
8. 页面采用 IDE/EDA 调试台的信息密度和深色工作区风格，不使用营销首页式布局。

## Boundaries

- Always：先验证真实 PTY 和官方 MCP，再做视觉层；用户界面显示可读名称；每个执行动作保留原始命令和日志。
- Ask first：新增外部依赖、改变官方 MCP 运行方式、持久化数据格式、远程执行能力。
- Never：用固定按钮替代终端；用一次性 subprocess 假装 PTY；把哈希 ID 当用户名称；把 MCP 工具删成少数演示接口；在终端闭环未通过前堆视觉装饰。

## References

- OpenROAD-MCP: https://github.com/The-OpenROAD-Project/OpenROAD-MCP
- EDA-Corpus: https://github.com/OpenROAD-Assistant/EDA-Corpus
- llm4chip visual reference: https://llm4chip.org/
