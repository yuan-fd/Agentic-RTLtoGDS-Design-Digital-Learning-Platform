# ADR-0003：L2 改为“薄平台 + 外部优化器插件”

- status: Accepted
- accepted_by: user
- accepted_at: 2026-08-30

## 要解决的问题

旧 L2 将参数域、候选生成、BO/GP、记忆、实验状态机和 HTTP API 写在同一产品路径中。每增加一个补丁都同时影响搜索行为、恢复语义和网站逻辑；既难以公平复现实验，也无法替换为已发表的优化器。近期真实预检中，旧自研候选没有优于 baseline；该结果不能用“再调几个参数”掩盖。

## 决策

平台不再把自己定位为第九个优化算法项目。它只拥有以下公共边界：

1. `DesignGoalIR`、受限语义工具与权限；
2. Runtime：工作区、进程、并发、取消、种子、超时和产物哈希；
3. `ObservationBundle`：原始 EDA 产物引用、低失真 EDAIR、统一 QoR 与可行性；
4. `OptimizerPlugin`：固定版本的上游优化器负责 suggestion / observe /
   checkpoint；平台只负责启动、喂入观测、接收候选、执行评估和审计；
5. 公平实验协议：共同设计、共同参数域、共同预算、共同 evaluator、多 seed。

ORFS-Agent 是首个正式 L2 候选：BSD-3-Clause，使用独立 adapter；其原生
SSH、目录、Anthropic provider 假设不得越过平台 Runtime。StateTune 当前只作
源码审计，待许可证明确后再接入。旧 `stateful-l2-portfolio-v1` 与
`industrial-dse-portfolio-v1` 冻结为 legacy/reproduction，不再扩展，不得作为
新论文或产品默认优化器。

## 迁移顺序与验收

1. 每个外部项目先固定 commit、许可证、依赖、入口、输入输出和最小 smoke。
2. 在 Runtime 工作区构造上游的原生数据合同；保留原 observation id、日志和
   artifact 引用，不能只传摘要。
3. 验证上游候选能由平台执行并回收 QoR；再验证 checkpoint/recovery。
4. 只在 ORFS-Agent 单设计真实 smoke 成功后，将 L2 产品入口切到插件
   orchestrator；旧入口保留为只读历史查询，随后删除写入口。
5. 性能声明必须来自新协议下的多设计、多 seed、同预算对照；烟雾测试、旧
   预检和一次最好值一律不能作为优化结论。

## 不做什么

- 不把 L3/L4 的 ECO、DRC 修复或源码 diff 提前塞进 L2。
- 不让 LLM 直接执行 shell、改 OpenROAD 源码或写最终 QoR 状态。
- 不为“看起来有学习”另写一套弱 BO/GP 来替代已发表实现。
