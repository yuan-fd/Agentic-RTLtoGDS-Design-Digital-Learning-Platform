# Agentic RTL-to-GDS 教学平台

> [English](README.md) · **中文**

本项目是面向数字电路教学和工程演示的 Agentic RTL-to-GDS Learning
Platform，核心演示链路为：

```text
自然语言规格 → RTL → 验证 → ORFS → GDS → 可追溯证据
```

它不再定位为论文研究平台、优化算法发表平台，也不是组内所有项目的
总入口。历史实验和既有集成会按目录归类为展示内容或历史证据，不会默默
成为新的产品主链路。

## 执行底座与边界

`openroad-platform-v2` 是独立执行底座。教学层只通过 HTTP 与 v2 通信，
不导入 v2 源码、不打开 v2 数据库、不复制 Runtime，也不持有原始 RTL、
GDS、日志和报告。v2 保持领域中立，负责：

- Task、输入 staging 和隔离工作区；
- 进程生命周期、取消和超时；
- artifact、metric、evidence 和 provenance；
- identity/session 与 Toolkit 准入。

教学层负责 `SpecIR`、RTLVersion、VerificationPackage、CandidateRecord、
PDKCapability、ScriptProposal 和 EvidenceRef。浏览器不接收模型 API key；
无认证模式只允许本机开发，不能用于课堂服务器。

## 教学模块

| 模块 | 作用 | 阶段 |
| --- | --- | --- |
| Teaching Hub | 入口、题库、历史和 Evidence Exchange 视图 | 基础层 |
| M1：LLM → RTL → GDS | 从冻结规格到真实 GDS 的完整教学实验 | 第一条完整切片 |
| M2：Direct LLM vs RTLScout | 相同 SpecIR、验证包和后端协议下比较两个独立生成器 | 独立最小切片 |
| M3：Fixed Baseline vs ORFS-Agent | 固定协议下展示全部观测、失败、预算和 QoR 曲线 | 独立最小切片 |
| M4：Flow / Recipe Scripting Lab | 仅执行已登记且经用户确认的 Tcl/Python patch | 独立最小切片 |

第一阶段先完成 M1：一个固定 Course Lab 题目和一个自然语言单时钟 FSM，
在 Nangate45 上真实跑通 RTL-to-GDS。生成、验证、工具链、PDK、评估器或
GDS 任一步失败，都必须显示真实失败/不完整状态；禁止默认 PDK、旧结果、
隐藏 fallback 或伪造 QoR。

## 两类设计目录

**Course Lab** 首批十题：Mux/Decoder、Priority Encoder、Adder/Subtractor、
ALU、Edge Detector、Counter、Shift Register、FIFO、UART TX、
Sequence Detector/Moore-Mealy FSM。每题都有冻结 Spec、人工冻结 oracle、
参考 RTL、recipe、难度、PDK 支持和真实 smoke 状态。

**ORFS Showcase** 收录 GCD、AES、Ibex、RISC-V、JPEG、SPI、I2C GPIO、UART、
Ethernet MAC、TinyRocket/CVA6 等固定 RTL。它们用于展示真实 IP、版图和
工具链能力，不承诺可由任意自然语言稳定生成。

## UI 原则

采用紧凑的 Teaching Hub + 工作台布局：左侧 Spec/RTL，中间阶段流程和
当前运行，右侧证据/错误/解释/下一步，底部网表、真实 DEF/GDS、报告和 QoR。

视觉上使用白底、黑字、高对比度等宽代码字体和少量状态色；去除蓝色大底、
模糊灰字、渐变、装饰性阴影和无限长页面。所有图形都引用真实 artifact
hash；缺少 KLayout 或其他渲染依赖时显示明确的不可用状态，不生成假图。

## Slice 0 文档

- [教学平台规格](docs/TEACHING_PLATFORM_SPEC.md)
- [模块目录](docs/TEACHING_MODULE_CATALOG.md)
- [PDK 能力矩阵](docs/PDK_CAPABILITY_MATRIX.md)
- [Evidence Exchange](docs/EVIDENCE_EXCHANGE.md)
- [旧代码清理清单](docs/governance/LEGACY_CLEANUP_INVENTORY.md)
- [HTTP 边界 ADR](docs/adr/ADR-0004-teaching-layer-over-v2-http.md)

## 开发验证

```bash
python3 -m pytest -q tests/test_teaching_contracts.py
python3 -m pytest -q
```

当前 active 主干只保留独立的 M1 模块和教学 contracts。旧 API、旧 Web、
旧 Workbench、旧 Runtime 与研究入口已从 active 主干移除，保存在 Git 标签
`archive/pre-teaching-platform` 中，不作为兼容服务运行。教学模块只能通过
HTTP 访问 v2，不能导入 sibling app，也不能打开 v2 数据库。

## 固定部署与独立验收

启动入口是 `scripts/start_teaching_platform.sh`。默认状态目录为
`.local/state/openroad-teaching`；管理员创建系统目录后可设置
`M1_STATE_ROOT=/var/lib/openroad-teaching`。v2 和 worker 继续只监听
`127.0.0.1`，M1 默认监听 `127.0.0.1:8101`。

SQLite 在线备份使用：

```bash
python3 scripts/teaching_platform_ops.py backup \
  --database .local/state/openroad-teaching/m1.sqlite \
  --output .local/state/openroad-teaching/backups/$(date +%Y%m%d-%H%M%S)
```

独立验收目录 `acceptance/` 会从当前 release commit 创建 clean checkout，
运行全量测试和浏览器四种 viewport 检查，并分别输出：

```text
Functional acceptance: PASS/FAIL
Production deployment readiness: PASS/FAIL
```

临时公网 IP 只能作为教师查看演示，不能被报告为生产部署；正式分享需要
HTTPS、每用户 v2 session、owner isolation、备份、限流和可回滚服务配置。
