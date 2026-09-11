# LLM Teaching Platform：共识规格 v0.1

状态：已批准；2026-09-11 进入目标模式实施
日期：2026-09-11

## 目标

将 OpenROAD Platform 改造成一个服务器托管、面向教学和开放探索的 LLM-assisted EDA 平台。第一阶段只聚焦核心功能跑通，不做课程发布、教师管理、公网产品化或复杂账号体系。

平台同时提供两种学习路径：

1. Guided Lab：预制实验保证学生能够完成 RTL、后端和优化闭环；
2. Open Lab / Challenge：学生可以提出自定义设计、参数和目标，由 AI 助教协助形成可执行实验，并在受控沙盒中自由探索。

## 已确认的产品边界

- 服务器集中提供工具链和运行环境，目标支持约 5–10 人同时在线。
- 用户不执行任意 shell，不修改服务器工具链，不提交任意 config。
- 用户可以输入自然语言规格、上传/粘贴 RTL，并使用登记过的参数白名单。
- RTL 教学同时保留 Direct LLM 与 RTLScout 对比，但两者必须共用验证和后端评估协议。
- DSE 首版提供四种可比较模式：Rule Batch、Bayesian/GP、A2-ORFO、Random Baseline。
- 规则 batch 默认 3 个候选，上限 6 个；baseline 可独立执行。算法对比必须计入各方法原生初始化和反馈预算，不能将完整 A2 强行简化成 3 点算法。
- A2-ORFO 是优化策略；ORFS/ORFS-Agent 是执行器。
- 前端核心对象压缩为 Project、Experiment、Run、Evidence。
- 正式产品只保留一条主链路：
  `创建实验 → RTL/Spec → 验证 → baseline → 候选搜索 → QoR → Agent 反馈 → Dashboard`。
- 页面收敛为 Dashboard、RTL Studio、DSE Lab、Results & Evidence。
- Dashboard 显示阶段状态机、Agent 当前动作、决策摘要、QoR 曲线、算法比较和下一步建议，不展示隐藏推理、密钥、内部路径或无过滤的系统日志。
- 第一版实时更新使用短轮询，后续再评估 SSE/WebSocket。
- 旧 API 和旧数据先盘点、兼容和迁移，最后删除或归档；未确认无用的资产先归档，不直接删除。

## 自由探索模型

### Guided Lab

参数和任务受控，提供固定 benchmark、验证 oracle、预算和预期现象。

### Open Lab

学生可以复制实验并修改自己的 RTL、Spec、目标、参数、候选数和算法组合，但所有任务必须经过 schema、资源和验证边界检查。

### Challenge

学生可以提出自己的优化假设和目标，AI 帮助将问题转换为实验计划；执行仍然只能使用已登记的指标、参数和受限 ActionSpec。

AI 助教可在实验前帮助形成计划，实验中解释 Agent 当前动作，实验后基于 Evidence 生成分析和报告。AI 可以提出下一步，但必须由学生确认后执行。开放实验先进入个人实验历史，经过证据完整性和独立验证后才可进入公共知识库。

## UI 方向

视觉参考为 Linear 的简洁工作台、GitHub Actions 的运行状态、MLflow/W&B 的实验比较和 Prefect 的阶段状态。目标是白底、浅灰分区、单一强调色、少卡片、结论优先、细节按需展开。

Dashboard 分为全局实验总览和单实验详情：

```text
理解需求 → 形成规格 → 生成 RTL → 验证
→ 建立 baseline → 搜索参数 → 评估 QoR → 沉淀经验
```

## 架构方向

- `apps/api/app.py` 拆为路由、应用服务、schema 和 read model；
- `apps/l1_workbench/service.py` 收敛为 ExperimentService；
- 前端只依赖统一 Dashboard Read Model；
- 运行状态由统一 Runtime/Experiment 状态机负责；
- A2-ORFO、BO/GP、Rule Batch、Random 只负责提出候选，统一 ORFS 执行器负责运行，统一 evaluator 负责 QoR；
- 核心状态使用 `draft / queued / running / paused / waiting_for_user / succeeded / failed / cancelled / expired`；
- Agent 阶段使用 `understand / specify / generate / verify / baseline / search / evaluate / learn`；
- 失败必须分类并给出下一步建议，不生成伪 QoR；
- 学习记录必须绑定 Run/Evidence，区分观察、假设、负例、拒绝和已验证知识。

## 非目标

第一阶段不做：公网发布、教师后台、课程评分、用户自带 API Key、任意 shell、任意 config、完整终端替代、无限资源、复杂多租户和大规模研究调度。

## 成功标准

1. 新用户无需在本机安装 EDA 工具即可完成最小 RTL→QoR 实验；
2. 同一冻结 baseline 下四种 DSE 模式能够并排运行和比较；
3. Dashboard 能展示运行阶段、Agent 动作、QoR 和证据；
4. 学生可以从 Guided Lab 复制到 Open Lab，并由 AI 辅助提出下一步实验；
5. 失败、取消、超时和服务器重启不会伪造或丢失实验状态；
6. 旧入口不会继续作为第二条产品主链路。
