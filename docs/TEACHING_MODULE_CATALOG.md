# 教学模块目录

状态：Slice 0 登记表；2026-09-19

## Teaching Hub

Teaching Hub 只做身份后的导航、题库目录、运行历史和 Evidence Exchange
的只读投影。它不执行 EDA、不读取 v2 数据库、不生成 RTL、不实现优化器。

## M1：LLM → RTL → GDS

```text
自然语言需求 → 澄清/SpecIR freeze → Direct LLM RTL
→ RTL 编辑版本 → lint/compile/simulation/mutation
→ ORFS → GDS/DEF/ODB/netlist/reports → QoR/evidence/view
```

首版要求固定题目和自然语言 FSM 各有一条真实端到端证据。编辑 RTL 永远
创建新 `RTLVersion`，不覆盖旧 candidate。

## M2：Direct LLM vs RTLScout

两个 generator adapter 接收相同 SpecIR，使用相同 VerificationPackage 和
RTL-to-GDS 协议。结果按成功率、验证质量、Mutation、面积/时序/功耗/DRC、
失败阶段和运行成本比较。一个 adapter 失败时不能使用另一个 adapter 的
RTL 或结果。

## M3：Fixed Baseline vs ORFS-Agent

比较协议固定 RTL、PDK、SDC、工具链、evaluator、搜索空间、预算和停止条件。
视图必须展示 trajectory、全部失败、观测成本和协议摘要，而不是只展示两个
最终数字，也不得改写 ORFS-Agent 的原生协议来适配 UI。

## M4：Flow / Recipe Scripting Lab

模型生成 Tcl/Python 和登记 recipe 的 patch proposal。用户看到 diff、参数
解释和允许路径后才能确认。确认后的 proposal 通过 v2 隔离工作区执行并登记
日志、artifact、metric 和 evidence。

## Course Lab 首批题目

| ID | 题目 | 主要教学概念 |
| --- | --- | --- |
| course-mux-decoder | Mux / Decoder | 组合逻辑 |
| course-priority-encoder | Priority Encoder | 优先级与编码 |
| course-adder-subtractor | Adder / Subtractor | 算术与位宽 |
| course-alu | ALU | 组合 datapath |
| course-edge-detector | Edge Detector | 时序采样 |
| course-counter | Counter | 复位、使能、计数 |
| course-shift-register | Shift Register | 移位与时钟 |
| course-fifo | FIFO | 握手和边界条件 |
| course-uart-tx | UART TX | 协议时序 |
| course-sequence-fsm | Sequence Detector / FSM | Moore/Mealy |

每题必须登记冻结 Spec、人工 oracle、参考 RTL、验证包、recipe、难度、支持
PDK 和真实 smoke 证据后，才可在 UI 显示为可运行。

## ORFS Showcase

固定 RTL 展示项：GCD、AES、Ibex、RISC-V、JPEG、SPI、I2C GPIO、UART、
Ethernet MAC、TinyRocket/CVA6。它们与 Course Lab 分区呈现；Showcase 的
规模或版图证据不能推导出自然语言生成能力。
