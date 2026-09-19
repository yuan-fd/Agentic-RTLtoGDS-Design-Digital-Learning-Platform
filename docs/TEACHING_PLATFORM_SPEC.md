# 教学平台规格 v0.1

状态：Slice 0 基线；2026-09-19

## 1. 定位

平台面向数字电路教学和工程演示，解释 LLM 如何参与从 RTL 到 GDS 的
受控流程。论文研究、优化算法发表、任意组内项目聚合和公网多租户不在
首版范围内。

## 2. 首版成功标准

1. 用户不安装 EDA 工具即可从教学题目或自然语言规格开始。
2. 一个固定题目真实完成 lint/compile/simulation/ORFS/GDS。
3. 一个自然语言生成的单时钟 FSM 真实完成同一条链路。
4. 每个阶段显示真实状态、输入、输出、失败原因和证据引用。
5. 用户编辑 RTL 后产生新版本，旧验证证据不能继续绑定。
6. PDK 不可用、工具链缺失或 GDS 缺失时明确失败，不改用另一个 PDK。

## 3. 系统边界

教学服务通过 v2 HTTP API 发送带身份、输入、recipe 和预期 artifact 的
TaskSpec，并读取 Run、Artifact、Metric、Evidence 和 Provenance。v2 是
运行事实来源。教学服务只保存教学对象和引用，不复制原始文件。

教学层的持久对象：

| 对象 | 责任 |
| --- | --- |
| SpecIR | 冻结的可执行设计意图 |
| RTLVersion | 某次编辑或生成的 RTL 版本及其父版本 |
| VerificationPackage | 人工冻结的编译、仿真、形式/Mutation 检查 |
| CandidateRecord | 生成器、输入版本和验证状态 |
| PDKCapability | 题目×PDK 的真实能力状态 |
| ScriptProposal | 已登记入口上的待确认 patch |
| EvidenceRef | v2 artifact/metric 的元数据引用 |

## 4. M1 状态规则

规格不完整时只能返回 `needs_clarification`，不能猜测并创建执行任务。
首版只接收可综合 SystemVerilog、单时钟域、有限端口/位宽、常见组合/时序
逻辑、counter、FIFO、UART、握手和 Moore/Mealy FSM。多时钟、模拟模块、
厂商 IP、存储器宏、未登记外部 IP 或不能形成可执行验证条件的请求返回
`unsupported_scope`。

状态顺序为：

```text
draft → frozen → generated → rtl_versioned → verified → submitted → measured
```

任一失败状态必须保留失败阶段和原因。验证未通过不能提交 RTL-to-GDS。

## 5. 后续模块协议

- M2 固定一个 SpecIR、VerificationPackage、PDK、工具链和评估协议；Direct
  LLM、RTLScout 是两个独立 candidate source，禁止互相回退或共享生成结果。
- M3 固定 RTL、PDK、SDC、工具链、evaluator、搜索空间、预算和停止条件；
  保留 baseline 与 ORFS-Agent 的全部观测、失败和成本。
- M4 只允许登记的入口和路径，先生成 proposal 和 diff，用户确认后在 v2
  隔离工作区执行；浏览器不得执行任意 shell。

## 6. 验收门禁

每个模块需要独立进程、数据库、smoke、contract tests 和 integration tests。
新增模块不得导入 sibling app、访问 v2 数据库或实现第二套 Runtime。
“兼容旧路径”“静默 fallback”“吞掉异常”“伪造 QoR”都属于验收失败。
