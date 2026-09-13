# OpenROAD-MCP integration

**范围：只做接入，不做 app。** 这里没有任何界面、守护进程、索引器或自己的抽象层——
它就是把官方的 `OpenROAD-MCP` 服务器按 MCP 协议完整接起来，给你一个能**手动逐个调用
全部 15 个工具**并看到**原始协议应答**的入口。

## 接入的是什么（已固定版本）

| 项 | 值 |
|---|---|
| 上游仓库 | https://github.com/The-OpenROAD-Project/OpenROAD-MCP |
| 固定的 commit | `9dc80d3706fbcd8144cccb639fa21af7b933cbf5`（2026-09-12） |
| 版本 | `openroad-mcp 1.1.0` |
| 本机路径 | `~/openroad-mcp` |
| 入口 | `typescript/dist/main.js`（`bin.openroad-mcp`） |
| 传输 | stdio（本目录默认）；上游同时支持 `--transport http` |
| 运行时 | Node v24.18.0（要求 ≥22）、OpenROAD 在 PATH、`ORFS_FLOW_PATH` 默认 `~/OpenROAD-flow-scripts/flow` |

复现这份 checkout：

```bash
git clone https://github.com/The-OpenROAD-Project/OpenROAD-MCP.git ~/openroad-mcp
cd ~/openroad-mcp && git checkout 9dc80d3706fbcd8144cccb639fa21af7b933cbf5
cd typescript && npm install && npm run build
```

本目录的客户端**只用 Python 标准库**，不需要 `pip install` 任何东西。

## 你自己手动测试（三步）

```bash
cd ~/openroad-platform

# 1) 确认接的是官方服务器、工具数量对
python3 integrations/openroad-mcp/mcp_console.py ping

# 2) 看全部 15 个工具的说明与参数
python3 integrations/openroad-mcp/mcp_console.py tools

# 3) 全量跑一遍，每个工具都会打印它用的参数和服务器返回的原文
python3 integrations/openroad-mcp/verify.py
```

`verify.py` 默认是**只读为主**的快速巡检（ORFS 那步用 `--dry-run`，不会真的跑流程）。
要连真实流程一起验（会真的启动一次 `synth` 再取消掉它）：

```bash
python3 integrations/openroad-mcp/verify.py --orfs-run --raw --out /tmp/report.json
```

### 交互式手动调用（推荐）

有状态的序列必须在**同一个连接**里做，所以用 repl，而不是一条条 `call`：

```bash
python3 integrations/openroad-mcp/mcp_console.py repl
```

```
mcp> create_interactive_session          # 回车逐项填参数，可留空
mcp> interactive_openroad_query          # command 填 help
mcp> interactive_openroad_exec           # command 填 set_thread_count 1
mcp> get_session_history
mcp> describe read_orfs_metrics          # 看完整 schema
mcp> quit
```

也可以在命令行单次调用：

```bash
python3 integrations/openroad-mcp/mcp_console.py call list_interactive_sessions
python3 integrations/openroad-mcp/mcp_console.py call read_orfs_metrics '{"design":"gcd","platform":"sky130hd"}'
python3 integrations/openroad-mcp/mcp_console.py call run_orfs_stage \
    '{"design":"gcd","stage":"synth","platform":"sky130hd","dry_run":true}' --yes
python3 integrations/openroad-mcp/mcp_console.py call cancel_orfs_job '{"job_id":"..."}' --yes
```

`--yes` 只对会改变状态的 5 个工具要求（`interactive_openroad_exec`、
`create_interactive_session`、`terminate_interactive_session`、`run_orfs_stage`、
`cancel_orfs_job`）。**这是便利性保护，不是安全边界**——官方服务器没有认证也没有授权，
谁能跑这个 console，谁就能在这台机器上跑 OpenROAD。

## 覆盖情况（本机实测）

`verify.py` 输出：**16 OK / 0 FAIL / 0 SKIP / 1 KNOWN-UPSTREAM**

| 工具 | 实测用的参数 | 结果 |
|---|---|---|
| `tools/list` | — | 15 个工具 |
| `create_interactive_session` | `{}` | 返回 `session_id`、`is_alive=true` |
| `list_interactive_sessions` | — | 列出该会话 |
| `inspect_interactive_session` | `session_id` | 返回 metrics 与 state |
| `interactive_openroad_query` | `{"session_id","command":"help"}` | 49938 字符真实 OpenROAD 帮助 |
| `interactive_openroad_exec` | `{"session_id","command":"set_thread_count 1"}` | `[INFO ORD-0030] Using 1 thread(s).` |
| `get_session_history` | `session_id`, `limit` | 2 条命令 |
| `grep_session_output` | `pattern=thread` | 2 处命中 |
| `get_session_metrics` | — | manager/aggregate 均有数据 |
| `read_orfs_metrics` | `{"design":"gcd","platform":"sky130hd"}` | 14 个 stage、5 条 gate |
| `run_orfs_stage` | `design/stage/platform`,`dry_run` | 返回 `job_id` 与真实 `make -n synth ...` 命令行 |
| `get_orfs_job` | `job_id` | status/stage/耗时等 |
| `cancel_orfs_job` | `job_id` | `cancelled=true` |
| `list_report_images` | `sky130hd/ibex/base` | 10 张图 |
| `read_report_image` | 同上 + `image_name` | 返回 `image/webp` 图像块 |
| `terminate_interactive_session` | `session_id` | `terminated=true` |

## 发现的上游缺陷（不是我们接错）

`list_report_images` 与 `read_report_image` 对**嵌套目录**的处理不一致：

* `list_report_images` 用递归查找（`typescript/src/tools/report_images.ts:410` → `findImageFiles` 在 `:188`），
  所以 `reports/<platform>/<design>/<run_slug>/<variant-*>/xxx.webp` 能被列出来；
* `read_report_image` 只做 `path.join(runPath, imageName)`（`:561`），**不递归**，且
  `image_name` 明确禁止路径分隔符。

结果：这类图"列得出来、读不出来"，而且提示自相矛盾：

```
Image 'cts_clk.webp' not found. Available images: cts_clk.webp, ...
```

复现（`reports/nangate45/opv2_gcd_e31472cb2d95826f/v2-generated-smoke-5-tune` 下图在
`variant-AutoTunerBase-.../` 子目录里）：

```bash
python3 integrations/openroad-mcp/verify.py --raw | grep -A3 "nested run"
```

`reports/sky130hd/ibex/base` 下的图是**平铺**的，所以 `read_report_image` 在那里正常——
`verify.py` 用这个用例证明工具本身可用，同时把嵌套那种情况标成 `KNOWN-UPSTREAM` 而不是 FAIL。

## 实测踩到的两个坑（写下来省你时间）

1. **`read_orfs_metrics` 的 `design` 不能有路径分隔符，且重名时必须给 `platform`。**
   `{"design":"gcd"}` 会返回 `Design 'gcd' exists under multiple platforms (...)`；
   `{"design":"sky130hd/gcd"}` 会返回 `design cannot contain path separators`。
   正确写法：`{"design":"gcd","platform":"sky130hd"}`。

2. **`interactive_openroad_query` / `exec` 不传 `session_id` 时，服务器会另用一个会话。**
   实测连续调用后 `get_session_metrics` 报 `total_sessions: 3`，而你以为在用的那个会话
   history 是空的。要串起一段交互，**每次都显式带 `session_id`**，并尽量用 `repl`。

## 已知边界（官方本身就有的）

* 没有认证/授权：能连上就能执行。
* 官方 `session.ts` 的 `runCommand` 没有 per-session 锁，同一 session 并发调用会互相串输出；
  `cleanupIdleSessions()` 在官方代码里没有调用点，空闲会话不会被回收。这些是上游行为，
  本目录没有做任何规避——接入层不该偷偷改写上游语义。
