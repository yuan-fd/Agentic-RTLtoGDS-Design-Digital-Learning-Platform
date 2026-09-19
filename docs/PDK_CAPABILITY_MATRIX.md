# PDK 能力矩阵

状态：首版登记；2026-09-19

首版登记 `nangate45`、`sky130hd`、`asap7`。每个“题目 × PDK”是独立记录，
不能因为另一个 PDK 成功而改变本记录。

## 状态定义

```text
registered → toolchain_ready → recipe_ready → rtl_smoke_passed
→ gds_smoke_passed → available
```

任意阶段也可以是 `blocked`，但必须记录具体原因和复查条件。只有真实
GDS smoke 通过后才能展示为 `available`；未安装 KLayout 等渲染依赖不影响
原始 GDS 是否存在，但必须在视图中明确显示渲染不可用。

## 初始登记

| PDK | Course Lab | 首条验收优先级 | 当前产品声明 |
| --- | --- | --- | --- |
| nangate45 | 10 题逐项登记 | M1 固定题目 + 自然语言 FSM | 第一条完整纵向切片 |
| sky130hd | 10 题逐项登记 | M1 后逐题 smoke | 仅真实 smoke 后可用 |
| asap7 | 10 题逐项登记 | M1 后逐题 smoke | 仅真实 smoke 后可用 |

能力状态必须包含 `recipe_id`；`gds_smoke_passed` 和 `available` 必须绑定
smoke evidence。UI 展示状态和阻塞原因，不显示推测的可用性。
