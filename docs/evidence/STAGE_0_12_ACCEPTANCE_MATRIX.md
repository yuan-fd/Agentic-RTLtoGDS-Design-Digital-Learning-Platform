# 阶段 0–12 验收矩阵（2026-09-13）

| 阶段/能力 | 当前结论 | 证据 |
|---|---|---|
| 0 环境与仓库审计 | 已证实 | `teaching_platform_doctor.py`；审计报告 |
| 1–3 Labs、三入口、教学骨架 | 已证实 | 网页静态入口、真实认证浏览器回放、教学 API 回归 |
| 4 Ibex baseline | Runtime 已证实，页面命令检查已回放，实际页面启动待验收 | Ibex ORFS run `fbfbb60abfae43a8aa1a922567f96af4`；浏览器 command-check `accepted=true` |
| 5 参数比较 | Runtime 已证实，页面回放待验收 | 比较 run `5ffcbb58de464496ba8e046f1bfeb171` |
| 6 DSE 四模式与批量约束 | 已证实（API/回归） | DSE 相关测试与计划文档 |
| 7 Dashboard、Agent 状态、证据投影 | 已证实（API/静态渲染） | Dashboard 测试；Runtime artifact projection |
| 8–9 自然语言 EDA Console | 已证实（受控路径） | 浏览器 command-check 返回 `accepted=true`；session 回归 |
| 10 OpenROAD-MCP 只读探索 | 已证实 | stdio probe、query adapter、历史隔离、报告图像 smoke |
| 11 MCP→Runtime 升级 | 已证实（门禁与代码路径） | `upgrade-plan`/`upgrade-run`、确认和隔离测试 |
| 12 RTLScout→mutation→ORFS→GDS | 有界 `and2` 已证实 | mutation `90b025d43e0747cea56ad83f3ccb6a8f`；ORFS `909786433f0d4f4ea13b467f43027389` |
| 并发能力 | 8 用户 smoke 已证实 | `run_teaching_http_concurrency_smoke.py`：8/8 |

## 尚未关闭的验收门

- 主机缺少可用的无头浏览器，因此 Ibex 页面端到端回放、MCP 图像页面回放尚未取得浏览器证据。
- 尚未完成更复杂设计上的 P12 多轮晋级；当前证据是有界 `and2`。
- 尚未进行持续生产负载测试；8 用户结果是短时 smoke，不代表长期容量上限。

这些限制不会被代码存在、静态页面或 API 响应替代；在取得对应运行证据前保持未完成状态。
