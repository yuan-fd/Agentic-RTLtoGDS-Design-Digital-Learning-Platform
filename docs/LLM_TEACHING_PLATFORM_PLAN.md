# LLM Teaching Platform：执行计划 v0.1（待审批）

本计划只描述顺序和验收，不代表已开始实施。

## 阶段 0：基线冻结与资产盘点

- 建立可回滚的 clean baseline 和审计快照；
- 盘点 endpoint、service、worker、script、plugin、数据库和运行目录；
- 将资产标记为 product、compatibility、research、archive、generated、external；
- 明确当前测试命令和缺失依赖。

验收：有一份旧入口清单、依赖清单、数据目录清单和回滚点；不删除未知资产。

## 阶段 1：环境和最小运行闭环

- 统一 Python/EDA/Graphviz/Optuna/BoTorch/RTL 工具链入口；
- 提供单一启动命令和环境自检；
- 跑通一个小设计的 RTL→验证→ORFS→QoR→网页结果；
- 将普通回归和真实 EDA/nightly 回归分离。

验收：干净环境中无需手工设置 PYTHONPATH 即可启动；最小闭环有可复现 acceptance artifact。

## 阶段 2：ExperimentService 与统一状态模型

- 定义 Project、Experiment、Run、Evidence 的最小契约；
- 统一实验状态和 Agent 阶段；
- 将 `l1_workbench/service.py` 收敛为 ExperimentService；
- 建立统一 Dashboard Read Model；
- 旧 API 进入兼容/弃用清单。

验收：前端可以只通过一个实验状态接口显示一项实验的完整进度。

## 阶段 3：RTL Studio

- 统一自然语言 Spec、Direct LLM、RTLScout、上传 RTL 的输入模型；
- 建立同一验证 oracle 和候选证据；
- 展示两条 RTL 生成路径的功能和 QoR 对比；
- 把验证失败转成可理解的教学反馈。

验收：至少一个小设计可比较 Direct LLM 与 RTLScout，功能结果与后端 QoR 分开报告。

## 阶段 4：DSE Lab 四模式

- 统一冻结 baseline、参数白名单、候选预算和 evaluator；
- 实现 Rule Batch、Bayesian/GP、A2-ORFO、Random Baseline 的并列运行；
- 默认 3 个候选，上限 6 个；
- 支持选择部分模式，但明确显示未运行模式；
- 展示 Pareto/QoR/收敛和失败原因。

验收：同一实验内四种模式可复现、可比较、共享 baseline，且候选数和资源约束生效。

## 阶段 5：Agent Dashboard 与 AI 助教

- 实现总览和单实验详情；
- 短轮询更新阶段状态、动作、耗时、QoR 和估计剩余时间；
- 生成结构化决策摘要；
- 增加实验前计划、实验中解释、实验后分析和下一步建议；
- 保证每个结论回指 Evidence。

验收：用户不看终端也能理解 Agent 在做什么、为什么做、结果如何、下一步是什么。

## 阶段 6：Guided → Open → Challenge

- Guided Lab 提供固定实验模板；
- Open Lab 支持复制实验和受控自定义；
- Challenge 支持假设、目标和实验计划；
- AI 建议必须经用户确认后执行；
- 个人实验历史与公共知识分级，验证后才晋级。

验收：用户能从预制实验复制出开放实验，并完成一次有假设、有证据、有结论的探索。

## 阶段 7：旧入口迁移与发布前清理

- 前端全部迁移到正式 API；
- 旧 API 只读/弃用；
- 无调用方的旧逻辑归档或删除；
- 生成物、运行目录和外部源码脱离产品源码；
- 补齐 README、运维、自检和验收文档。

验收：只有一条正式产品主链路；全量产品测试、最小真实 EDA、前端语法和环境自检通过。

## 实施规则

- 每个阶段拆成可回滚的垂直切片；
- 每个切片先写契约，再实现，再测试，再提交；
- 不在功能切片中顺手重构无关代码；
- 不删除未确认的旧资产；
- 每阶段结束提供检查点，下一阶段需经确认后开始。

## 待审批事项

请审批：阶段顺序、四种 DSE 模式、统一状态模型、Guided/Open/Challenge 三层模型，以及“先基线和环境、后功能、最后清理”的实施策略。
