# Agentic EDA 平台：2026-09-05 汇报交付

## 今天怎么用

1. 自己先打开 `index.html`，五分钟浏览结论和完成情况。
2. 发给老师可直接使用 `完整报告.html`：正文、样式和图示均内嵌，无外部字体、脚本或 CDN 依赖。
3. 讲汇报时用 `06-workshop.html`：提供 12 分钟讲稿、真实证据回放和三小时 workshop 目标议程。
4. 交给协作者用 `05-contributors.html`：贡献边界、插件协议、分工、测试和 PR 清单。
5. 浏览器中可点“打印 / 导出 PDF”。本次交付 HTML，不声称已生成 PDF。

## 专题

| 文件 | 内容 |
| --- | --- |
| `01-proposal.html` | 原文要求、L1—L4 对应、平台愿景与教程范围 |
| `02-architecture.html` | 功能架构、代码模块、spec 确认后的工作流 |
| `03-intelligence.html` | 诊断、参数搜索、有限动作、源码演化、工具编排和评测 |
| `04-audit-roadmap.html` | 现状锐评、协议问题、缺口、迁移切片和停止记录 |
| `05-contributors.html` | 可独立阅读的贡献者指南 |
| `06-workshop.html` | 汇报讲稿、演示、三小时课程、练习与问答 |
| `07-evidence.html` | 证据路径/哈希、代码行、文献与术语表 |

## 证据口径

- 复核 16 份已有验收摘要；重新核对 159 个直接可定位的不同产物引用，哈希全部一致。
- 本轮运行 51 项针对性测试，全部通过；没有重跑 EDA 或完整测试集。
- A2 完整 151 次测量 campaign 的状态是“已配置，未执行”。
- 8 位加法器、A2 单反馈、单故障恢复都属于有界验收，不是通用智能或 PPA 优势证明。
- 4 份摘要未在对应治理文档内找到同一 SHA-256；本轮补充计算，不冒充既有签名核验。
- 报告没有修改平台业务代码、评价器、RTL、PDK、SDC 或历史实验。

## 离线与可移植性

所有 HTML 可直接离线打开。外部论文链接只在主动点击时联网。
仓库源码和原始证据通过相对路径链接；如果只发送单个 HTML，这些本地文件不会随之发送，
但证据摘要、哈希、代码定位和正文仍完整可读。不要为方便发送而打包 PDK、原始模型轨迹、
凭据或共享运行目录。

打包文件 `教学汇报交付包.zip` 包含报告、阅读说明与筛选后的核验记录，
不包含完整仓库、上游源码、PDK、运行数据库或本地工作树基线清单。

## 本次交付核验

- `verification/focused-tests.log`：测试原始输出。
- `verification/source-audit.json`：源证据和直接产物引用核验。
- `verification/research-sources.json`：10 个原始文献/作者项目页面的访问记录。
- `verification/html-validation.json`：页面结构、引用、链接与示例代码检查。
- `verification/desktop-home.png`、`verification/mobile-home.png`：实际 Firefox 渲染截图。
- `verification/worktree-check.json`：现有工作树文件未变确认。
- `FILES.sha256`：对外分享文件的 SHA-256 清单（不含本地工作树快照、清单本身及压缩包）。

正文源片段和生成器位于 `source/`，仅用于维护这份文档。

```bash
python deliverables/2026-09-05-agentic-eda-report/source/build_report.py
python deliverables/2026-09-05-agentic-eda-report/source/validate_report.py
```

本次工作边界、每个新增文件及回滚方法见 `DOCUMENTATION_SLICE.md` 和 `FILE_INVENTORY.json`。
