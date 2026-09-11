"""Build portable, offline HTML reports from authored chapter fragments."""
from __future__ import annotations

import html
import json
import re
from pathlib import Path

OUT = Path(__file__).resolve().parents[1]
SRC = OUT / "source"
PAGES = [
    ("index", "今天的汇报", "先交付可信闭环，再谈自主进化", "五分钟阅读：项目定位、已完成内容、关键缺口与近期决策。", "5 MIN"),
    ("01-proposal", "Tutorial 要做什么", "从会用工具，到能改进工具", "把两页 proposal 拆成可讲授、可演示、可验收的目标；区分教程承诺与平台扩展。", "10 MIN"),
    ("02-architecture", "平台架构与工作流", "让专业插件协作，而不是重造算法", "从用户确认 spec 的下一秒开始，逐步解释功能模块、代码职责、状态和执行链路。", "18 MIN"),
    ("03-intelligence", "算法机制与智能工作台", "让证据改变下一步行动", "理解参数优化、有限动作、源码演化与诊断；知道“智能”来自哪里，又该如何验证。", "22 MIN"),
    ("04-audit-roadmap", "现状锐评与行动", "地基已有，能力边界必须讲清", "基于当前工作树和验收产物的差距分析；按单一迁移切片安排后续工作。", "15 MIN"),
    ("05-contributors", "贡献者指南", "多人并行开发，一条可信执行链", "选任务、划边界、接插件、写测试、交证据、发起评审；不给后来者留下隐形接线工作。", "15 MIN"),
    ("06-workshop", "汇报与 Workshop", "把原理、代码和真实证据串成故事", "可直接使用的汇报讲稿、三小时议程、演示步骤、练习和问答。", "12 MIN"),
    ("07-evidence", "证据与参考资料", "每个结论都有出处和适用范围", "审计方法、16 份验收摘要、159 个产物引用复核、代码定位、原始文献和术语表。", "REFERENCE"),
]


def render_refs(text):
    return re.sub(r"\[\[([CER]\d{2})\]\]", lambda m: f'<a class="ref" href="07-evidence.html#{m[1]}" aria-label="证据 {m[1]}">{m[1]}</a>', text)


def evidence_tables():
    audit = json.loads((OUT / "verification/source-audit.json").read_text())
    research = json.loads((OUT / "verification/research-sources.json").read_text())
    out = ['<h2 id="audit-method">核验方法与边界</h2>', '<p>本轮读取当前工作树，不把 HEAD 当作完整版本。复核 16 份现有 summary.json 的内容和 SHA-256，重新计算其中可直接定位的 159 个产物引用（159 个不同路径）的哈希，全部一致；不是重新执行这些 EDA 实验。没有直接枚举产物路径的摘要，仅核对摘要及其声明，不推断完成了全量传递依赖复核。</p>',
           '<p>另运行 51 项针对性测试，全部通过；静态扫描 contracts 未发现其导入 scheduler、execution、analysis、apps 或 integrations 的边。这个扫描不等于证明整个仓库完全无循环依赖。4 份摘要的治理文档未内嵌对应哈希，本轮补充计算，不能称为“与既有签名核对通过”。</p>',
           '<p><a href="verification/source-audit.json">机器可读源证据清单</a> · <a href="verification/focused-tests.log">本轮测试输出</a> · <a href="verification/research-sources.json">公开文献访问记录</a></p>',
           '<h2 id="evidence-records">现有验收证据</h2>']
    for row in audit['evidence']:
        f = row['facts']
        terminal = f.get('statuses', f.get('status', 'accepted=' + str(f.get('accepted', '未统一声明'))))
        terminal = json.dumps(terminal, ensure_ascii=False) if isinstance(terminal, dict) else str(terminal)
        counts = len(row['checked_artifacts'])
        docs = '、'.join(row['matching_governance_docs']) or '未找到同时包含该路径与本次 SHA-256 的治理文档；本轮仅补充记录。'
        out += [f'<article class="evidence-card" id="{row["id"]}"><span class="badge">{row["id"]} · 已核摘要</span><h3>{html.escape(row["title"])}</h3>',
                f'<p><a href="../../{html.escape(row["path"])}"><code>{html.escape(row["path"])}</code></a></p>',
                f'<span class="hash">SHA-256 {row["sha256"]}</span>',
                f'<p class="small">摘要终态：{html.escape(terminal)}。本轮直接产物引用复核：{counts} 项。</p>',
                f'<p class="small">声明边界：{html.escape(str(f.get("claim_boundary", "以原摘要中的各子检查为准，不将缺失的统一终态补写为成功。")))}</p>',
                f'<details><summary>运行编号、对应文档与关键事实</summary><p class="small">{html.escape(docs)}</p><pre>{html.escape(json.dumps({"runs": row["runs"], "facts": f}, ensure_ascii=False, indent=2))}</pre></details></article>']
    out += ['<h2 id="code-records">代码定位：当前工作树，不只 HEAD</h2>', '<p class="small">点击本地路径需保留报告在仓库内。把单文件发送给老师后，正文仍可离线阅读；源代码与原始运行产物不随报告打包。</p>', '<div class="table-wrap"><table><thead><tr><th>ID</th><th>路径 / 入口</th><th>本次文件哈希</th></tr></thead><tbody>']
    for row in audit['code']:
        out += [f'<tr id="{row["id"]}"><td>{row["id"]}</td><td><a href="../../{row["path"]}"><code>{row["path"]}:{row["line"]}</code></a><br>{html.escape(row["anchor"])}</td><td><span class="hash">{row["sha256"]}</span></td></tr>']
    out += ['</tbody></table></div>', '<h2 id="research-records">原始论文和作者项目</h2>', '<p>截至 2026-09-05 检查公开页面的标题与内容，保存页面哈希和访问状态。论文主张仅用于解释研究方向，不作为本平台能力验收。预印本不写成已正式发表；作者仓库页面可访问，不等于已完成 commit、许可和原生 smoke 的接入审查。外部链接仅在主动点击时联网。</p>', '<div class="table-wrap"><table><thead><tr><th>ID / 项目</th><th>原始来源</th><th>采用范围</th></tr></thead><tbody>']
    scopes = {
        'R01':'自然语言任务规划与工具使用；不直接搬入自由脚本执行路径。',
        'R02':'NAACL 2025：多候选协作与决策选择；不是通用物理诊断保证。',
        'R03':'作者 RTL 生成/优化实现；支持范围需另行适配与验证。',
        'R04':'原生 A2 搜索策略；平台不是它的本地等价实现。',
        'R05':'有限动作的时序优化研究；候选接入对象，未宣称本平台已接入。',
        'R06':'2026 年 8 月预印本：目标差距驱动源码演化；本轮未核实可执行发布与许可。',
        'R07':'跨阶段评价协议；本平台当前为 Red/source-audit-only。',
        'R08':'DRC/PPA 评价研究；本平台单题派生诊断分不等于官方指标。',
        'R09':'OpenROAD 文档 RAG；不等于 run-aware 根因定位。',
        'R10':'OpenROAD 原生修复能力说明；在线文档版本不是本平台 toolchain 版本。',
    }
    for row in research:
        out += [f'<tr id="{row["id"]}"><td>{row["id"]}<br><strong>{html.escape(row["name"])}</strong></td><td><a href="{html.escape(row["url"])}">{html.escape(row.get("title", row["name"]))}</a><br><span class="small">访问状态 {row["status"]} · 2026-09-05</span></td><td>{scopes[row["id"]]}</td></tr>']
    out += ['</tbody></table></div>', '<h2 id="attachment-records">用户材料与版本</h2>']
    for row in audit['attachments']:
        out += [f'<p><strong>{html.escape(row["name"])}</strong><br><span class="hash">{html.escape(row["path"])}<br>SHA-256 {row["sha256"]}</span></p>']
    out += [f'<p class="small">仓库 HEAD：<code>{audit["head"]}</code>。开始审计时工作树有 193 条状态记录（87 个已跟踪修改、106 个未跟踪项）；提交哈希不能单独复现本次看到的状态。此前已有的 930 个非忽略文件哈希另存于本地核验清单。本报告没有修改其中的业务代码。</p>']
    return '\n'.join(out)


def shell(slug, label, title, deck, duration, body, *, full=False):
    css = (SRC / 'style.css').read_text()
    links = ''.join(f'<a class="{"active" if s == slug else ""}" href="{("#" + s) if full else (s + ".html")}"><small>{i:02}</small>{l}</a>' for i,(s,l,*_) in enumerate(PAGES))
    nav = f'<nav aria-label="报告章节"><div class="label">Field Notes / 2026</div>{links}<p class="nav-note">绿色：有界证据<br>琥珀：部分完成<br>蓝色：建议设计<br>红色：停止 / 未满足<br><br>不以 smoke 宣称 PPA 优势。</p></nav>'
    head = f'<header class="pagehead motion"><div class="eyebrow">AGENTIC EDA / {label}</div><h1>{title}</h1><p class="deck">{deck}</p><span class="readtime">{duration} · 2026-09-05 · 文档审计，不是新增平台功能</span></header>'
    return f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light"><meta name="description" content="{html.escape(deck)}"><title>{html.escape(label)} | Agentic EDA 平台报告</title><style>{css}</style></head>
<body><a class="skip" href="#main">跳到正文</a><header class="topbar"><a class="brand" href="{'#index' if full else 'index.html'}">OPENROAD / RESEARCH PLATFORM</a><div class="topmeta">2026.09.05<br><span class="optional">PROPOSAL → ARCHITECTURE → EVIDENCE</span></div></header><div class="layout">{nav}<main id="main">{'' if full else head}<div class="actions"><a class="button secondary" href="{'index.html' if full else '完整报告.html'}">{'返回分专题首页' if full else '完整单文件 / 适合发送老师'}</a><button class="secondary" type="button" onclick="document.querySelectorAll('details').forEach(x=>x.open=true);window.print()">打印 / 导出 PDF</button></div>{body}<footer class="pagefoot"><span>编制基线：用户 proposal + 当前工作树 + 原始运行证据。</span><span>结论、研究主张、设计建议分别标注。</span></footer></main></div></body></html>'''


def main():
    bodies = {}
    for slug, label, title, deck, duration in PAGES:
        raw = (SRC / 'chapters' / (slug + '.html')).read_text()
        raw = raw.replace('<!-- EVIDENCE_TABLES -->', evidence_tables())
        raw = render_refs(raw)
        # Stable chapter-local anchors simplify the portable all-in-one edition.
        counter = [0]
        def heading(match):
            counter[0] += 1
            return f'<h2 id="section-{counter[0]}">{match[1]}</h2>'
        raw = re.sub(r'<h2>(.*?)</h2>', heading, raw, flags=re.S)
        bodies[slug] = raw
        (OUT / (slug + '.html')).write_text(shell(slug,label,title,deck,duration,raw))
    full = []
    for slug,label,title,deck,duration in PAGES:
        body = bodies[slug]
        body = re.sub(r'\bid="([^"]+)"', lambda m:f'id="{slug}-{m[1]}"', body)
        body = re.sub(r'url\(#([^)]+)\)', lambda m:f'url(#{slug}-{m[1]})', body)
        full += [f'<article class="all-chapter" id="{slug}"><header class="pagehead"><div class="eyebrow">{label}</div><h1>{title}</h1><p class="deck">{deck}</p></header>{body}</article>']
    combined = '\n'.join(full)
    for slug,*_ in PAGES:
        combined = re.sub(r'href="'+re.escape(slug)+r'\.html(?:#([^"]+))?"', lambda m:f'href="#{slug}'+('-'+m[1] if m[1] else '')+'"', combined)
    (OUT / '完整报告.html').write_text(shell('index','完整报告','Agentic EDA 平台报告','完整离线版本：从 tutorial 目标到平台架构、证据与贡献者实践。','COMPLETE',combined,full=True))
    print('Built',len(PAGES)+1,'self-contained HTML files.')


if __name__ == '__main__':
    main()
