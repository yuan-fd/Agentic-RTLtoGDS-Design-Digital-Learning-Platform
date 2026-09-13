# OpenROAD Workbench

终端优先的 OpenROAD 工程调试台。TUI 是主控制面，浏览器 dashboard 是同一后台的
管理与分析面，Agent 与终端并列。官方 OpenROAD-MCP 的 15 个工具完整保留。

```
TUI (Textual)   Web dashboard        Agent
      \               |                /
       \              |               /
        +------ 共享后台 daemon ------+
        |  PTY sessions · runs · artifacts
        |  MCP client · event bus
        +--------------------------------+
                        |
              bash / openroad / tclsh / python / make / ORFS
```

## 前置条件

| 需要 | 版本/位置 | 说明 |
|---|---|---|
| Python | **>= 3.9** | 用到 `os.waitstatus_to_exitcode`（3.9 起） |
| Python 包 | `aiohttp>=3.8`、`pyte>=0.8`、`textual>=1.0` | 见 `requirements.txt` |
| Node | >= 18 | 仅用于启动官方 OpenROAD-MCP |
| 官方 MCP | `~/openroad-mcp`（`typescript/dist/main.js` 必须已构建） | 用 `--mcp-repo` 或 config 指向别处 |
| OpenROAD | 在 PATH 中 | 终端里 `openroad` 可用即可；工作台不依赖其内部 API |

```bash
python3 -m pip install --user -r apps/openroad_workbench/requirements.txt
# 内网/国内镜像：
# python3 -m pip install --user -i https://pypi.tuna.tsinghua.edu.cn/simple \
#     -r apps/openroad_workbench/requirements.txt
```

官方 MCP 获取与构建：

```bash
git clone https://github.com/The-OpenROAD-Project/OpenROAD-MCP ~/openroad-mcp
cd ~/openroad-mcp/typescript && npm install && npm run build
```

`mcp_repo` 未解析到时，`/api/status` 会明确返回 `available: false`，
`openroad-workbench --status` 非 0 退出；不会静默降级。

## 快速开始

```bash
python3 apps/openroad_workbench/install.py            # 安装 openroad-workbench 命令
openroad-workbench                                     # 启动后台 + TUI + Web
openroad-workbench --design ~/OpenROAD-flow-scripts/flow/designs/sky130hd/gcd
openroad-workbench --no-tui                            # 只起后台，打印 dashboard 地址
openroad-workbench --status                            # 查看后台状态（JSON）
openroad-workbench --stop                              # 停止后台
```

远程服务器上使用浏览器时做端口转发：

```bash
ssh -L 8780:127.0.0.1:8780 user@host
# 然后打开 http://127.0.0.1:8780
```

## TUI 按键

| 按键 | 作用 |
|---|---|
| 直接输入 | 就是真实 shell：任意命令、管道、重定向、`openroad`、`tclsh`、`python`、`make` |
| `Ctrl+C` | 发送到终端（中断前台进程），**不会退出程序** |
| `Ctrl+N` / `Ctrl+W` | 新建 / 关闭终端 |
| `Ctrl+1..9` | 切换终端 |
| `F4` | 显示/隐藏侧栏 |
| `F2` / `Esc` | 聚焦 Agent 输入 / 回到终端 |
| `F3` | 显示/隐藏 Agent 面板 |
| `Ctrl+G` | 把 Agent 最近回复里的代码块**填入**终端输入栏（不执行；多行用括号粘贴插入，回车由你按） |
| `Alt+U` / `Alt+D` / `Alt+B` | 上翻 / 下翻 / 回到最底部 |
| `F1` | 帮助 |
| `Ctrl+Q` | 退出 TUI（后台任务继续运行，重开即重连） |

> 键位刻意避开 readline 的 `Ctrl-B/E/J/U/D/Y`：那些属于 shell。
> `Ctrl-U`（删行）、`Ctrl-D`（EOF）、`Ctrl-B/E`（左右移光标）在终端里照常可用。

## 设计要点

* **真 PTY**：`pty.fork()` 起真实终端，`Ctrl-C` 由内核行规程投递给前台进程组，
  不是合成信号。管道、重定向、环境变量、交互式程序全部可用。
* **Run 追踪**：生成的 shell 集成在每次提示符前发出私有 OSC 序列，携带**权威**的
  命令、cwd 与退出码；键盘输入重建只用于"按下回车就立刻显示运行中"。
* **单一真相源**：TUI 与 Web 都是 daemon 的客户端，不存在两套状态。
* **终端画面在服务端渲染**（pyte），浏览器不需要终端模拟器。
* **Agent 不执行**：只提议命令/脚本，填入终端输入栏后由用户回车。

## 目录

```
backend/  core.py(状态机) pty_session.py(真 PTY) artifacts/mcp_client/agent/corpus/server/daemon/config
tui/      Textual 客户端（app.py, widgets.py, client.py）
web/      aiohttp dashboard（原生 JS，无前端框架）
tests/    acceptance.py(终端+HTTP+负向用例) test_tui.py(无头 TUI 验收)
install.py  requirements.txt  WORKBENCH_SPEC.md
```

## 已知未实现 / 边界（如实申报）

* **Agent 未接模型**：`provider=null`，只做上下文汇总与本地语料检索；不会编造执行结果。
* **Agent 不展示 diff**：SPEC 里"展示 diff"未实现，目前只有"填入命令行 + 原文回显"。
* **语料库未内置**：`corpus_path` 为空时检索返回 0 条，不会假装命中。
* **Web 端不跑命令**：终端画面只读；命令只在 TUI 里执行（这是刻意的职责划分）。
* **单用户、无鉴权**：daemon 只监听 `127.0.0.1`，任何能访问该端口的人即拥有该用户的
  shell 权限。端口转发给别人等于交出 shell。
* **Run 记录来源**：shell 集成上报（带每会话随机 token）与键盘重建；`stages` 是从
  终端输出推断的**观察值**，不是 ORFS 的权威阶段状态。

## 验证

```bash
cd apps
python3 -m openroad_workbench.tests.acceptance       # 终端核心验收（SC 1-3 + HTTP）
python3 -m openroad_workbench.tests.test_tui out.svg # 无头 TUI 验收 + SVG 快照
```

## 配置

`~/.openroad-workbench/config.json`：

```json
{
  "mcp_repo": "/home/<user>/openroad-mcp",
  "port": 8780,
  "default_cwd": "/home/<user>",
  "corpus_path": "/home/<user>/.openroad-workbench/corpus",
  "agent": { "provider": "null", "base_url": "", "model": "", "api_key_env": "OPENROAD_WORKBENCH_API_KEY" }
}
```

Agent 目前默认 `provider=null`：它仍然会汇总真实上下文并检索本地 EDA 语料，
但明确声明未接入模型，不会编造执行结果。接入任意 OpenAI 兼容端点：

```bash
export OPENROAD_WORKBENCH_API_KEY=sk-...
# 并把 config.json 的 agent.provider 改为 "openai"，填 base_url / model
```

把 EDA-Corpus 放到 `corpus_path` 后重启 daemon 即可参与检索。
