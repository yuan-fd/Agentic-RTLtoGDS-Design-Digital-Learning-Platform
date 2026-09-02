# P5 L2 产品路径重新定基

status: active
date: 2026-09-02

## Boundary

P5 的产品 L2 优化入口是固定上游的 `ORFS-Agent`，能力为
`orfs-agent / optimizer.l2.propose`。这与 dependency-free
`ProductSurface` 的唯一 `product.l2_optimization` rule 一致。

`AgenticPD` 不属于产品入口：其 `integrations/agenticpd/` 已在
`LEGACY_CLEANUP_INVENTORY.md` 分类为 `INVALID`（无许可证声明），历史
P5 evidence、demo 和源码仅作为不可删除的历史/研究证据保留。它不得被新增
API、Web、TaskFactory、默认 Registry 或产品文档引用为可执行 L2 能力。

## Problem

旧 `docs/ROADMAP.md` 的 P5 行和历史 P5 evidence 把 AgenticPD 写成当前智能
优化接入；这与 P1 批准的唯一 L2 产品身份冲突。另一方面，现有 ORFS-Agent
原型存在于未提交工作树，涉及 contracts、analysis、execution、scheduler、
integration、script 和 test 多个边界，不能把未知归属的改动连同 P5 证据一起
静默提交。

## Evidence

- `packages/contracts/.../product_surface.py`：唯一 L2 rule 为
  `orfs-agent / optimizer.l2.propose`。
- `docs/governance/LEGACY_CLEANUP_INVENTORY.md`：AgenticPD 是 `INVALID`，
  限于 source audit。
- 当前主工作树的未提交 ORFS-Agent 原型包含 source lock、adapter、script 和
  test；这些内容**不在本提交的 Git tree 中**，因此不能作为当前产品准入、
  可执行插件或 bounded Runtime smoke 的证据。
- `git status --short`：ORFS-Agent 原型及其依赖当前尚未进入提交历史；在形成
  单独的实现提交前，已提交 inventory 对未来 ORFS-Agent intake 的分类仍是
  `UNKNOWN`。

## Required next implementation slice

在一个新的、显式文件清单的实现提交中，且只在其依赖均审查完成后，完成：

1. contracts 保持无 Runtime/插件反向 import；仅加入有版本的 L2 task/provenance
   契约（若确有缺口）。
2. ORFS-Agent adapter 只能调用锁定 upstream 入口；不得重写 GP/EI、RTL
   生成、评估器或 scheduler。Runtime 必须继续拥有 attempt、终态、工件、取消
   和恢复。
3. 每个 proposed candidate 必须经参数 allowlist 和冻结协议后，才由 Runtime
   创建 ORFS `TaskSpec`；预测/提案与受保护 evaluator 的观测 QoR 严格分开。
4. 先将 upstream URL、固定 commit、license、native entrypoint、依赖/安全审查
   和最小 adapter 映射提交为 intake lock；再用 clean pinned ORFS-Agent external
   worktree（不使用有未跟踪文件的 checkout）做 bounded smoke，保留原始 logs、
   候选、Runtime snapshot 和所有失败。
5. 对比只在 RTL hash、PDK、toolchain、SDC、seed policy、search space、预算和
   evaluator version 冻结一致时报告；smoke 不声明 QoR 优越性或论文复现。

## Options

- A：把现有未提交 ORFS-Agent 原型及所有跨层依赖直接纳入 P5。
- B：先对其依赖图逐文件审计，选取最小闭包，形成独立实现提交与真实 bounded
  smoke，再由新的 merge gate 审核。

## Recommendation

采用 B。它保持外部算法归 upstream、平台归 Runtime 的边界，同时不会丢弃或
删除用户已有的 ORFS-Agent 原型。该重新定基提交本身不把 P5 标记完成，也不
变更任何可执行插件、Runtime、受保护评估资产或历史原始证据。

## Rollback

revert 本重新定基提交即可恢复旧 roadmap 文案；不会删除历史代码或证据。
