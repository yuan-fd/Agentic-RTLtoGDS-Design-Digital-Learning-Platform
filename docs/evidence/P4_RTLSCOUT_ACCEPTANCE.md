# P4 RTLScout 插件验收

status: completed
captured_at: 2026-09-02
platform_commit: `5f3a7369064002b0bbb0748373c5c9cb5377c8e6`

## 本次可复核结果

在 clean detached platform worktree 中，固定 RTLScout
`87a00edf6b9208f657dd9ffdda170004024c08ae` 经标准子进程 Adapter 运行
官方离线 `fake:simple_adder_pass`，再由同一 Workflow Runtime 把生成 RTL 的
SHA-256 写入新 TaskSpec，提交给受管本机 ORFS。真实 Nangate45 `finish` 流程
成功完成并产出非空 GDS。

组合验收耗时 384.202 秒；RTLScout 源码与递归 submodule 在运行前后均保持
clean 和不变。Runtime 核验了 4 个 RTLScout 工件和 19 个 ORFS 工件的大小及
SHA-256，包含两侧原始日志。机器可读事实见
`P4_RTLSCOUT_ACCEPTANCE.json`；原始、可审计的运行目录为节点本地
`/tmp/openroad-platform-p4-clean.T01f7F/output/`，SQLite snapshot SHA-256 为
`9fb30a0ab423fa9c4924f92fbaaf336ef8b2fa711c26b518523428dd0fb83b88`。

## 关键工件

- RTL：82 bytes，`4b4fe1e2f61672c0fb5b440e4361881a07cbc0c51172d1a0fee1acc5c2010e7d`
- RTLScout 原始日志：1,759 bytes，`ee60ebae9cba7554e210cce0f5cdebc8bf4daa655dee149f0708c9d304d8b5a4`
- ORFS 原始 flow 日志：103,718 bytes，`ae6ddf1738711aacceb78792a3c0a0d1df7d38af2e610a5d0580e1e7cf6cba76`
- GDS：164,296 bytes，`a61f6ab3d265349186115546c00641b365a47eb5b1c93d6d47750040d0099af0`
- DEF：104,255 bytes，`e2d86871fce4dbc463e34db39ab85d8cb135e8781d02b74f34971290a76c2973`

## 边界和不作出的声明

- 这是 pinned external adapter、离线官方 fake model、RTL gate 和真实
  RTL-to-GDS 组合链的 smoke，不是 QoR 优越性结论。
- 本次没有执行付费/真实 LLM：没有用户提供的 provider 凭据或调用预算。
  该事实是 `not-run`，而不是把 fake 结果写成真实 LLM 证据。
- Runtime 而非 RTLScout/ORFS 是 run、attempt、artifact、metrics 和终态的
  权威；外部项目不写平台状态。
- 执行使用 server-local 受管 ORFS/OpenROAD 环境；没有 vendor、修改或重新
  分发外部工具链。

## 回滚

本切片仅更新本证据 Markdown 与 JSON。回滚方法是 revert 包含这两个文件的
P4 evidence commit；不会影响 Runtime、插件或任何受保护评估资产。
