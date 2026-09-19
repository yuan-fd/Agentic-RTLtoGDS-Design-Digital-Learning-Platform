# 外部插件事实清单

审计日期：2026-08-06

## Teaching-platform rebaseline

| Integration | Classification | Current boundary |
| --- | --- | --- |
| `rtl_verify/` | TEACHING_MODULE | First-party v2 Toolkit candidate for fixed Verilator/Yosys compile/lint; not admitted until operator review and native smoke. |
| `rtl_sim/` | TEACHING_MODULE | First-party v2 Toolkit candidate for fixed Icarus/vvp simulation against a frozen oracle artifact; not admitted until operator review and native smoke. |

本文件记录官方源码与项目补充材料的交叉核验结果。固定版本的机器可读真相源是 `plugins.lock.json`；第三方源码位于被 Git 忽略的 `.external-src/`，平台仓库不得复制第三方私有依赖。

## RTLScout

- 官方仓库：`huawei-csl/rtlscout`
- 固定 commit：`87a00edf6b9208f657dd9ffdda170004024c08ae`
- 许可证：BSD-3-Clause-Clear。
- 主入口：`run_benchmark.py`；平台托管 Codex 只适配上游 `LLMClient`，候选
  create/edit/evaluate/feedback/best-design/stop 均由原生 `core.agent.RTLAgent`
  的 Python ReAct backend 执行。
- 输出真相源：每次运行的 `result.json` 与 `best_design/`。
- Python：`pyproject.toml` 要求 `>=3.10`，高于主机系统 Python 3.9.9。
- 依赖：LLM SDK、Amaranth，以及 `tech_eval`、`spire-hdl` 等项目依赖；`spire-hdl` 是固定 commit 的 Git submodule。
- 已有验证：ARM64 源码环境完成真实 SpecIR→原生 Agent→独立 lint/simulation/
  mutation→ORFS finish/GDS 验收；canonical evidence 为
  `var/evidence/rtlscout-native-spec-to-gds-20260905-r8/summary.json`。fake smoke
  仅保留为测试，不代表产品能力。
- P3 增量核验：建立独立 Python 环境，初始化固定 submodule，验证源码级 ARM 安装；不得把镜像架构失败等同于源码不兼容。

接入结论：采用 provider-only thin adapter 调用固定 `run_benchmark.py`，保留
其内部 ReAct 和 correctness/cost gate。平台 Runtime 负责外层进程、超时、
取消、状态、独立验证、后端交付与产物登记。旧的平台自写候选循环不是原生
RTLScout，已退出 active path。

## AgenticPD

- 官方仓库：`Cheatnut/AgenticPD`
- 固定 commit：`4322a25c1d57bc88d576fd2ce6898a52d30d92c7`
- 当前官方 commit 已包含 `multi_agent_gwtw.py`、Doomed predictor、GWTW scheduler 与实验 YAML，与用户提供报告一致。
- 服务器旧副本停留在 `073ed6d...`，不能作为本轮适配基线。
- 依赖：OpenAI-compatible SDK、Matplotlib、PyYAML；报告基线为 Python 3.10。
- 证据模型：Trial、StageResult、CheckpointRef、ExecutionResolution、decision trace、optimization tree。
- 风险：仓库当前没有 LICENSE/COPYING 声明。许可证澄清前只做内部审计和适配验证，不复制、修改后再分发其源码。

接入结论：仅保留 Judge/StageAgent/Doomed/GWTW 的 source-audit 记录和历史
`ExperimentPlan`/`ActionProposal` 转换证据。Python manifest factory 与静态
manifest 均 fail closed；获得并审查许可证或作者许可之前，不得注册、执行、
复制、修改或再分发该项目。

## TaiWei-Pin-3D

- 官方仓库：`CODA-Team/TaiWei-Pin-3D`
- 固定 commit：`db20136711ed8c0cdfed67a6123d059875764abd`
- 许可证：BSD-3-Clause；设计与 PDK 子目录还包含各自许可证，打包产物时必须逐项保留。
- 主入口：`run_experiments.py`，支持 ORD/CDS、多任务、状态文件、监控和 kill/retry。
- 官方 README 声明的测试基线：ORFS-Research `568eb04...`、OpenROAD `305d3ba...`。
- 当前平台 2D 基线为 ORFS `51ad123...`、OpenROAD `63ed2e0...`，两者不能假设兼容。
- 输出：GDS、DEF/ODB/Verilog handoff、`openroad_eval.json`、`final_summary.txt`、3D views 与阶段日志。

接入结论：首版整体黑箱适配，使用独立工具链 profile 和工作区；内部阶段只作为带来源的子阶段事件，不进入平台状态主键。真实验证从 `gcd` ORD 流程开始。

P8 状态：`taiwei-pin-3d@1.0.0` 协议接入完成；固定 3D 工具链因 GitHub 连接超时且本机可见版本不匹配而 fail closed。详见 `docs/evidence/P8_TAIWEI_ACCEPTANCE.md`，不得将 fixture 视为真实 gcd。

## 共通准入门

每个插件在实现前必须具备：固定 commit、许可证结论、独立环境、manifest、输入输出 Schema、超时与取消语义、最小 smoke、产物 allowlist、错误传播测试和不包含凭据的环境快照。

## DPLEvolve

- 私有仓库：`CODA-Team/DPLEvolve`；固定 commit `96d8c613d62bf3431083bb5e52c7df8853d5a622`。
- 许可证：BSD-3-Clause；365 个文件的稳定内容清单 SHA-256 为 `4680820b...`。
- 历史锚点：ORFS `dcded683...`、OpenROAD `d14d526...`；OpenSTA/ABC 子模块另行固定。
- `dplevolve@1.0.0` 当前只执行 read-only release-readiness/source-lock audit，不运行 EDA、不修改源码。
- Tool-Evolve 候选只能修改 `tools/OpenROAD/src/dpl_evolve/`，且必须通过 metrics、liveness、legality、full-flow 与人工晋级门。
- P15 已完成固定构建和 patch 前像检查；两份完整 from-clean 候选可应用，两份 framework delta 失配。
- 尚未执行 evolved candidate 的真实 full-flow/QoR 对照，不得宣称代码优化效果已验证。

## ORFS-Agent

- 官方仓库：`ABKGroup/ORFS-Agent`，固定 commit
  `730f1fa11f9c17c0aaac332412af2b2538f42e9b`，BSD-3-Clause。
- 上游的完整 campaign 假设特定 ORFS revision、三个设计、远程 SSH 主机和
  Anthropic；不能直接成为本平台的 scheduler。
- 已接入的第一边界是 `orfs-agent@2025.1` dataset bridge：将完整的、带
  observation id 和 artifact 引用的 Runtime observations 转成上游
  `output.json` 行格式，并校验 source lock。它不替代上游算法，更不会悄悄
  回退到旧 `stateful-l2-portfolio-v1`。
- 已通过平台托管 `codex-cli:gpt-5.6-terra` 的窄适配调用上游 analyst：模型只
  选择实测训练子集，上游 `scikit-optimize` GP/EI 产生数值候选。真实 OpenROAD
  baseline → candidate → repeated evaluation 已作为 smoke 跑通；这证明链路，
  不构成跨设计 PPA 优势声明。

## A2-ORFO

- 官方仓库：`CODA-Team/TaiWei-flow-Agent`，固定 commit
  `8b20a3c1f22934a39c7ba51ed0ec6dffe730da2d`，BSD-3-Clause。
- A2-ORFO 扩展了 ORFS-Agent，原生 `OptimizationWorkflow.run_iteration()`
  包含 RAG、inspection/model/selection、ReAct GPR feedback、supervisor 与
  TextGrad prompt update。
- 原生 shell/SSH/`eval` launcher 不被接纳；平台只接入 policy 边界，候选仍由
  Runtime 调用受控 ORFS 并由 protected evaluator 产生 QoR。
- 12-D 正式域取自同 commit 的 `constraints.json`；不会采用
  `optimize.py` 中与之冲突的旧硬编码范围，也不会事后夹断候选。
- RAG 模型固定为 `mixedbread-ai/mxbai-embed-large-v1` commit
  `b33106f585b9ce46904ad7443a3b52b7a63e231c`，Apache-2.0。
- 已完成一个真实 proposal→ORFS→evaluator→feedback→next proposal 闭环；候选
  signoff 不可行的事实仍被保留。该 smoke 不构成完整 campaign 或 PPA 优势声明。
- 当前产品角色是唯一 L2 optimizer
  `optimizer.l2.a2-orfo-feedback`；ORFS-Agent 仅作为其完整 12-D、variable-clock
  EDA executor。默认原生预算为 26 个 bootstrap 加 5 轮各 25 个 feedback
  candidate，共 151 次 EDA measurement。完整 campaign 已配置但未启动。

## ORAssistant

- 官方仓库：`The-OpenROAD-Project/ORAssistant`，固定 commit
  `a5df2dfe54869fd929d966a4ce335b9d0892f676`，GPL-3.0-only（Yellow：独立进程
  使用；不把上游源码链接或复制进平台核心）。
- 当前只接入 `knowledge.openroad.retrieve`：上游原生 `process_md`、
  `BM25RetrieverChain` 和 `format_docs`；不接入 MCP、数据库、前端、云模型或
  ORFS 执行。
- 官方 Hugging Face RAG Dataset 在 intake 时无法取得可核验 commit/license，
  因此未下载。首个 corpus 是独立固定的 OpenROAD commit `63ed2e0f...`，每个
  返回 chunk 同时带源文件 URL、document SHA-256 和 chunk SHA-256。
- Python 3.13.7 retrieval-only 环境使用上游 `uv.lock` 的固定版本。未调用的
  Google/Vertex/Ollama/HuggingFace provider 以 fail-closed import shim 隔离；
  Runtime audit hook 拒绝网络与新 subprocess。
- native smoke 与静态 manifest 的 Runtime smoke 均通过；canonical evidence：
  `var/evidence/orassistant-platform-20260905-r3/summary.json`。这只证明检索与引用
  连续性，不代表完整 hybrid/reranker、广域问答正确率或对用户 run 的根因诊断。

## PostEDA-Bench

- 官方仓库：`pengjas/posteda-bench`，固定 commit
  `51884e5f20e6e199219cec87c1c779a3dfab95bc`，CC BY 4.0。
- 接入边界只有 `benchmark.posteda.public-case` 与
  `benchmark.posteda.evaluate-diagnosis` 两个隔离 Runtime capability；不进入默认
  产品表面，也不接入参考 agent 或自动修复。
- 第一阶段仅读取公开 prompt/DRC report，拒绝 `info.json`；平台封存
  `DiagnosisReport` 和 typed decision 后，第二个 scorer 进程才读取隐藏标签。
- native KLayout smoke 与平台两阶段 acceptance 均通过；canonical evidence 为
  `var/evidence/posteda-platform-diagnostic-20260905-r1/summary.json`。派生分数不是
  官方 SR/ERR/VRR，也不证明修复成功或广泛诊断准确率。

## CLOSER-Bench

- 可核验公开资产仅有 arXiv `2607.16632v1`；论文 PDF SHA-256 为
  `84280d8b1a79924c5742fa1536fd1c48622cf93b7dd407d348b02c5b4750ac28`。
- 未发现可验证的官方源码/数据仓库、commit、源码许可证、冻结 A/B/C task、
  container digest、hidden oracle 或 native entrypoint，故 intake 为 Red，禁止
  注册或执行，平台没有 CLOSER-Bench plugin。
- 当前只做非官方 paper-protocol alignment。加入一次独立冻结的平台自有真实
  backend→RTL checkpoint recovery 后为 5 met / 2 partial / 3 missing；canonical
  evidence 为 `var/evidence/closer-protocol-alignment-20260905-r2/summary.json`。
  这不是官方 benchmark result。

## Seeded Random Control

- `seeded-random-control@1.0.0` 不是外部研究项目，也不替代 ORFS-Agent；它是
  论文比较协议所需的内部、非自适应对照插件。
- 入口：`seeded_random_control_adapter.py`；仅使用独立 Python 3.9 标准库环境，
  无网络、无 QoR 读取能力、无 ORFS 启动能力。
- 输入是预检已经收缩后的有限参数域、固定 seed 与已用坐标指纹。它只做无放回
  抽样；可用坐标不足时明确失败，绝不以重复配置补足预算。
- 输出候选、输入清单和抽样 trace；实际 OpenROAD 调用、工件哈希和 QoR 真相仍由
  Runtime 与 protected evaluator 负责。

## StateTune（用户口中的 StateTuner）

- 官方仓库：`C-YuLong/stateTune`，固定 commit
  `66ea6061128afcb389ae36dab51e29bd0847f268`；论文为 ICCAD 2026，
  DOI `10.1145/3831252.3834031`。
- 技术上它提供完整的 typed persistent memory、evidence gating、multi-fidelity
  qEHVI 和 runtime-aware promotion，可作为 L2 目标实现，而非让平台重写。
- 该 commit 实际没有 LICENSE/COPYING/NOTICE；目前只作 read-only source audit，
  没有 Runtime 插件，也不复制或修改其源码。获得许可证/作者许可后才可正式接入。

## EDACraft Extension Pack

- 官方仓库：`ephonic/EDACraft`；固定 commit `739eee0f3ced8fc3cbb6f01b6cc89414758fd898`。
- 根许可证是 MIT-like 加 Non-Commercial 限制；仅允许本机私有非商业验收。
- 平台按六个独立插件接入，而不是把整个 monorepo 包装为一个含糊的 “IC Craft”：
  - `edacraft-rtlcraft`：前端白盒 Python DSL、SystemVerilog 生成和验证表面；
  - `edacraft-edacode`：模拟/混合信号 Agent 与 VS Code 表面，当前禁止暴露上游任意 shell/file-write；
  - `edacraft-tcadcraft`：器件级 3D TCAD，当前执行真实几何 smoke，不声称完整求解；
  - `edacraft-momcraft`：互连电磁与 S 参数，当前执行真实 Touchstone I/O smoke，不声称全波求解；
  - `edacraft-cktcraft`：SPICE/RF 求解器表面，固定版 v0.2 使用 Verilog-A→C++ 静态模型，当前为源码准入；
  - `edacraft-implcraft`：保留原 P11 数字后端 dry-run 脚本生成接入。
- P11 上游回归 220 项：215 passed、5 个固定已知失败。
- 本机无商业 EDA binary/license；`edacraft-implcraft@1.0.0` 只声明 `eda.implcraft.scriptgen` 和 `eda.backend.plan`，禁止宣称商业 GDS/signoff。
- P17 六组件均经 Workflow Runtime 产生独立 run 和哈希证据；能力等级详见 `docs/evidence/P17_EDACRAFT_WEB_ACCEPTANCE.md`。
