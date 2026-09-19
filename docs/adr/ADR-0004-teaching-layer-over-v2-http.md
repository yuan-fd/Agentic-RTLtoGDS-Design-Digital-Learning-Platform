# ADR-0004：教学层通过 HTTP 使用 v2 执行底座

状态：Accepted · 2026-09-19

## Context

教学平台需要把 SpecIR、RTL candidate、验证包和可视化组织成教学体验，
而 `openroad-platform-v2` 已经拥有经过 guardrail 约束的任务、进程、产物、
指标、证据和身份边界。若复制 v2 Runtime 或直接访问其数据库，产品会出现
第二个事实来源，并重新引入旧平台的耦合。

## Decision

教学模块通过稳定的 v2 HTTP client/API 提交 TaskSpec、查询 Run 和读取
artifact/metric/evidence。教学模块维护自己的数据库和教学对象，但只保存
v2 ID、哈希和声明范围。v2 不导入教学模块，也不承担 Course Lab、Direct
LLM、RTLScout 或 UI 策略。

## Consequences

- v2 可以保持领域中立并独立升级；
- 教学模块可以独立测试、部署和演进；
- 网络契约、身份和 artifact 引用需要明确版本化；
- 没有 v2 服务或工具链时，模块必须显示真实 unavailable/failed 状态；
- 任何直接打开 v2 DB、复制 Runtime 或 sibling app import 都是架构违规。

## Rejected alternatives

- 将 v2 源码 vendoring 到教学平台；
- 在旧 `apps/api/app.py` 中继续增加教学分支；
- 让浏览器直接执行 EDA 或携带模型 API key；
- 用兼容路由维持第二条旧产品主链路。
