#!/usr/bin/env python3
"""Generate publication-grade, editable SVG and PNG research figures.

The figures deliberately separate proposal, protected execution, evidence,
review, and memory.  Every number is tied to the frozen v2 experiment files;
the drawings do not imply v3 repair tools have already been executed.
"""
from __future__ import annotations

import math
from pathlib import Path
from xml.sax.saxutils import escape

import cairosvg


OUT = Path("/share/home/yuanwenjie/Desktop/图片")
SRC = OUT / "可编辑源文件"
EN = OUT / "English"
OUT.mkdir(parents=True, exist_ok=True)
SRC.mkdir(parents=True, exist_ok=True)
EN.mkdir(parents=True, exist_ok=True)

W, H = 1920, 1200
INK = "#14243A"
MUTED = "#5F6F82"
NAVY = "#174A7E"
BLUE = "#2F73B7"
CYAN = "#2D8CA4"
TEAL = "#2D806D"
GREEN = "#4A9274"
ORANGE = "#E47A36"
PURPLE = "#7656A8"
RED = "#C94F58"
SLATE = "#718096"
PALE = "#F5F8FC"


def t(x, y, value, size=18, weight=400, color=INK, anchor="start", family="sans", italic=False):
    fam = "Georgia,serif" if family == "serif" else "SimHei,Noto Sans CJK SC,Microsoft YaHei,Arial,sans-serif"
    style = "italic" if italic else "normal"
    lines = str(value).split("\n")
    spans = "".join(f'<tspan x="{x}" dy="{0 if i == 0 else size*1.34}">{escape(line)}</tspan>' for i, line in enumerate(lines))
    return f'<text x="{x}" y="{y}" text-anchor="{anchor}" font-family="{fam}" font-size="{size}" font-weight="{weight}" font-style="{style}" fill="{color}">{spans}</text>'


def rr(x, y, w, h, fill="white", stroke="#CAD5E2", sw=1.5, r=14, dash="", shadow=False):
    flt = ' filter="url(#shadow)"' if shadow else ""
    ds = f' stroke-dasharray="{dash}"' if dash else ""
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{ds}{flt}/>'


def line(x1, y1, x2, y2, color=SLATE, sw=2.4, arrow=True, dash=""):
    ds = f' stroke-dasharray="{dash}"' if dash else ""
    marker = ' marker-end="url(#arrow)"' if arrow else ""
    return f'<path d="M{x1},{y1} L{x2},{y2}" fill="none" stroke="{color}" stroke-width="{sw}"{ds}{marker}/>'


def path(d, color=SLATE, sw=2.4, arrow=True, dash="", fill="none"):
    ds = f' stroke-dasharray="{dash}"' if dash else ""
    marker = ' marker-end="url(#arrow)"' if arrow else ""
    return f'<path d="{d}" fill="{fill}" stroke="{color}" stroke-width="{sw}"{ds}{marker}/>'


def pill(x, y, w, text, color=NAVY, fill="#EDF4FC"):
    return rr(x, y, w, 34, fill, color, 1.2, 17) + t(x+w/2, y+23, text, 13, 650, color, "middle")


def icon_circle(x, y, label, color=NAVY, r=23):
    return f'<circle cx="{x}" cy="{y}" r="{r}" fill="{color}"/>' + t(x, y+7, label, 18, 750, "white", "middle")


def head(num, title, subtitle):
    return (f'<rect x="0" y="0" width="{W}" height="18" fill="{NAVY}"/>'
            + t(64, 76, f"FIGURE {num:02d}", 17, 800, ORANGE)
            + t(64, 122, title, 34, 760)
            + t(64, 158, subtitle, 16, 400, MUTED)
            + f'<line x1="64" y1="182" x2="1856" y2="182" stroke="#D7E0EA"/>')


def base(num, title, subtitle, body, caption):
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">
<defs>
 <filter id="shadow" x="-20%" y="-20%" width="140%" height="150%"><feDropShadow dx="0" dy="5" stdDeviation="7" flood-color="#16324F" flood-opacity=".10"/></filter>
 <marker id="arrow" markerWidth="10" markerHeight="10" refX="8.5" refY="5" orient="auto"><path d="M0,0 L10,5 L0,10 Z" fill="context-stroke"/></marker>
 <linearGradient id="bluewash" x1="0" x2="1"><stop stop-color="#EDF5FD"/><stop offset="1" stop-color="#F9FBFE"/></linearGradient>
 <linearGradient id="greenwash" x1="0" x2="1"><stop stop-color="#ECF8F4"/><stop offset="1" stop-color="#FAFDFC"/></linearGradient>
 <linearGradient id="orangewash" x1="0" x2="1"><stop stop-color="#FFF2E9"/><stop offset="1" stop-color="#FFFBF8"/></linearGradient>
</defs><rect width="100%" height="100%" fill="white"/>{head(num,title,subtitle)}{body}
<line x1="64" y1="1120" x2="1856" y2="1120" stroke="#D7E0EA"/>{t(64,1152,caption,14,500,MUTED)}
</svg>'''


def fig1():
    b = ""
    # Three architectural planes, with a protected runtime spine.
    b += rr(64, 215, 1792, 220, "url(#bluewash)", "#A7C2DE", 1.4, 18)
    b += t(88, 249, "A  RTL CONSTRUCTION PLANE", 15, 800, NAVY)
    b += pill(1450, 228, 360, "AUTHOR ≠ VERIFIER · frozen checks", PURPLE, "#F3EEFA")
    rtl = [(100,"NL specification","ports · behavior · constraints",BLUE),(370,"SpecIR contract","assumptions · acceptance",CYAN),(640,"Verification Agent","TB/SVA · mutation plan",PURPLE),(940,"RTL Author Agent","candidate branches · repair",ORANGE),(1250,"RTLScout evaluator","compile · lint · sim · mutation",TEAL),(1580,"promoted RTL","lineage · SHA · evidence",GREEN)]
    for i,(x,a,c,col) in enumerate(rtl):
        b += rr(x, 286, 230 if i<5 else 210, 105, "white", col, 1.8, 13, shadow=True)
        b += icon_circle(x+27, 313, str(i+1), col, 17)+t(x+52,315,a,16,720)+t(x+18,350,c,12,450,MUTED)
        if i < len(rtl)-1: b += line(x+(230 if i<5 else 210),338,rtl[i+1][0]-10,338,col,2.2)
    b += path("M1470,391 C1470,421 1080,421 1080,391", ORANGE, 2, True, "7 6")
    b += t(1270, 404, "diagnostic feedback → candidate repair", 12, 650, ORANGE, "middle")

    b += rr(64, 468, 1792, 366, "url(#greenwash)", "#9BC6B7", 1.4, 18)
    b += t(88, 503, "B  PROTECTED PHYSICAL-DESIGN LOOP", 15, 800, TEAL)
    # central runtime boundary
    b += rr(720, 525, 480, 255, "white", TEAL, 2.4, 22, "9 6", shadow=True)
    b += t(960,560,"PROTECTED RUNTIME",20,800,TEAL,"middle")
    b += t(960,589,"fixed toolchain · checkpoint · run ID · artifact SHA",13,500,MUTED,"middle")
    stages=[("synth",790,637),("floorplan",875,637),("place",960,637),("CTS",1045,637),("route",1130,637)]
    for name,x,y in stages:
        b += f'<circle cx="{x}" cy="{y}" r="26" fill="#E8F5F1" stroke="{TEAL}" stroke-width="1.5"/>'+t(x,y+5,name,10,700,TEAL,"middle")
    for i in range(4): b += line(stages[i][1]+26,637,stages[i+1][1]-26,637,TEAL,1.8)
    b += pill(785, 698, 350, "hard gates: WNS ≥ 0 · DRC = 0", RED, "#FFF0F1")
    # surrounding actors
    b += rr(105, 550, 250, 160, "white", BLUE, 1.7, 14, shadow=True)+t(230,582,"Baseline",18,760,BLUE,"middle")+t(230,615,"same RTL / PDK / tool commit\npaired OR_SEED replicas",13,450,MUTED,"middle")
    b += rr(410, 550, 250, 160, "white", PURPLE, 1.7, 14, shadow=True)+t(535,582,"BO / GP proposer",18,760,PURPLE,"middle")+t(535,615,"joint parameter vector\nEI × feasibility",13,450,MUTED,"middle")
    b += rr(1260, 550, 250, 160, "white", CYAN, 1.7, 14, shadow=True)+t(1385,582,"Typed EDAIR",18,760,CYAN,"middle")+t(1385,615,"stage · object graph · source span\nloss manifest + raw fallback",13,450,MUTED,"middle")
    b += rr(1560, 550, 250, 160, "white", ORANGE, 1.7, 14, shadow=True)+t(1685,582,"Reviewer",18,760,ORANGE,"middle")+t(1685,615,"constraints → statistics → promote\n3 stalled batches → redirect",13,450,MUTED,"middle")
    b += line(355,630,410,630,BLUE); b += line(660,630,720,630,PURPLE); b += line(1200,630,1260,630,TEAL); b += line(1510,630,1560,630,CYAN)
    b += path("M1685,710 L1685,804 L535,804 L535,710", PURPLE,2.2,True,"8 6")+t(1110,797,"next experiment / redirected subspace",12,650,PURPLE,"middle")

    b += rr(64, 865, 1792, 218, "url(#orangewash)", "#EAB18D", 1.4, 18)
    b += t(88, 900, "C  EVIDENCE → CAUSAL CHECK → MEMORY", 15, 800, ORANGE)
    items=[("EvidencePacket","run + artifact + context",BLUE),("2×2 intervention","main / interaction effect",ORANGE),("holdout replay","direction + uncertainty",PURPLE),("knowledge state","validated / refuted",TEAL),("retrieval only","execution_allowed = false",RED)]
    xs=[110,440,770,1100,1430]
    for i,((a,c,col),x) in enumerate(zip(items,xs)):
        b += rr(x,930,280,105,"white",col,1.6,14,shadow=True)+t(x+140,964,a,17,740,col,"middle")+t(x+140,995,c,12,480,MUTED,"middle")
        if i<4: b += line(x+280,982,xs[i+1]-10,982,col,2)
    b += path("M1570,1035 C1570,1090 340,1090 340,1035", ORANGE,2,True,"7 6")
    return base(1,"OpenROAD–Evolve：从自然语言规格到受保护自演化的完整闭环","三条平面共享同一证据合同；模型负责提案，固定 Runtime 负责执行，Reviewer 负责晋级。",b,"总览图｜实线表示受保护执行；虚线表示反馈或学习；图中 repair 仅为诊断换向，未声称已执行 v3 工具。")


def fig2():
    b = rr(64,215,1792,830,"#FBFCFE","#D2DCE7",1.3,20)
    cx,cy=960,635
    # central authority nucleus
    b += f'<circle cx="{cx}" cy="{cy}" r="150" fill="#ECF8F4" stroke="{TEAL}" stroke-width="3"/>'
    b += f'<circle cx="{cx}" cy="{cy}" r="105" fill="white" stroke="{TEAL}" stroke-width="1.6" stroke-dasharray="8 6"/>'
    b += t(cx,605,"RUNTIME",24,820,TEAL,"middle")+t(cx,638,"AUTHORITY",18,740,TEAL,"middle")
    b += t(cx,676,"sandbox · checkpoint\nrun_id · artifact SHA",13,500,MUTED,"middle")
    labels=[("MAP","design / tool / stage",-90,BLUE),("SEMANTICS","typed evidence",-45,CYAN),("EXPERIMENT","budget / controls",0,PURPLE),("HYPOTHESIS","claim / falsifier",45,ORANGE),("IMPLEMENT","ActionSpec only",90,ORANGE),("VALIDATE","paired full-flow",135,TEAL),("REVIEW","gates / statistics",180,RED),("MEMORY","validated / refuted",225,PURPLE)]
    b += f'<circle cx="{cx}" cy="{cy}" r="330" fill="none" stroke="#B6C3D1" stroke-width="2" stroke-dasharray="5 9"/>'
    pos=[]
    for i,(a,c,ang,col) in enumerate(labels):
        rad=math.radians(ang); x=cx+330*math.cos(rad); y=cy+330*math.sin(rad); pos.append((x,y))
        b += rr(x-115,y-58,230,116,"white",col,1.8,16,shadow=True)+icon_circle(x-86,y-28,str(i+1),col,16)+t(x-58,y-24,a,15,760,col)+t(x,y+18,c,12,450,MUTED,"middle")
        b += line(cx+150*math.cos(rad),cy+150*math.sin(rad),x-120*math.cos(rad),y-60*math.sin(rad),col,1.7,False,"5 6")
    # The outer dotted orbit communicates ordered cognition without drawing
    # a dense all-to-all graph through the authority nucleus.
    # role and constraint rails
    b += rr(100,260,300,160,"#EEF5FD",BLUE,1.5,14)+t(125,294,"ROLE SEPARATION",15,800,BLUE)+t(125,328,"Spec Agent ≠ RTL Author\nVerifier cannot edit RTL\nObserver has no execute right",13,500,MUTED)
    b += rr(1520,260,300,160,"#FFF2E9",ORANGE,1.5,14)+t(1545,294,"EXECUTION CONTRACT",15,800,ORANGE)+t(1545,328,"schema + whitelist + budget\nHypothesis.execution_allowed=false\nReviewer alone promotes",13,500,MUTED)
    b += rr(100,860,300,130,"#FFF0F1",RED,1.5,14)+t(125,894,"WITHOUT GATES",15,800,RED)+t(125,928,"remove checkpoint → 2 duplicate runs\nremove authority → 12 unsafe hypotheses",13,500,MUTED)
    b += rr(1520,860,300,130,"#F3EEFA",PURPLE,1.5,14)+t(1545,894,"WITHOUT REVIEW",15,800,PURPLE)+t(1545,928,"8 sub-threshold fluctuations\nwould be promoted incorrectly",13,500,MUTED)
    return base(2,"Agent 框架：八阶段推理围绕一个受保护执行核","八阶段不是八个随意聊天的 Agent；权限、产物类型与晋级权在 Runtime 边界内被硬编码。",b,"Agent 消融｜完整架构：0 duplicate、0 unsupported executable hypothesis、0 below-threshold promotion、100% evidence completeness。")


def fig3():
    b=""
    b += rr(64,215,1792,170,"#F1F6FC","#A9C3DD",1.4,18)+t(90,250,"01  OBSERVE — 形成可证伪的问题",15,800,BLUE)
    b += t(105,295,"OpenROAD trajectory",15,700,NAVY)+t(105,326,"stage KPI · failures · object path",12,450,MUTED)
    b += line(330,310,430,310,BLUE)
    b += rr(430,270,520,80,"white",BLUE,1.5,12)+t(455,300,"Observation card",15,750,BLUE)+t(455,330,"context + anomaly + source spans + uncertainty",12,450,MUTED)
    b += line(950,310,1060,310,BLUE)
    b += rr(1060,270,690,80,"white",ORANGE,1.5,12)+t(1085,300,"Hypothesis = claim + mechanism + falsifier + stop rule",15,750,ORANGE)+t(1085,330,"不是“这个参数好像更好”，而是预注册怎样证伪",12,450,MUTED)
    # 2x2 matrix
    b += rr(64,420,930,425,"#FFFBF8","#EAB18D",1.4,18)+t(90,455,"02  INTERVENE — 2×2 组合干预",15,800,ORANGE)
    x0,y0=170,535; cw,ch=300,115
    b += t(435,505,"Factor B",15,700,ORANGE,"middle")+t(98,650,"Factor A",15,700,ORANGE,"middle")
    vals=[["y--\nA- / B-","y-+\nA- / B+"],["y+-\nA+ / B-","y++\nA+ / B+"]]
    for r in range(2):
        for c in range(2):
            fill="#FFF4EA" if (r+c)%2 else "white"; b+=rr(x0+c*(cw+16),y0+r*(ch+16),cw,ch,fill,ORANGE,1.5,10)
            b+=t(x0+c*(cw+16)+cw/2,y0+r*(ch+16)+45,vals[r][c],18,720,INK,"middle")
    b += rr(150,795,760,38,"#FFF0E8",ORANGE,1.2,18)+t(530,820,"interaction Delta = y++ - y+- - y-+ + y--",15,700,ORANGE,"middle")
    # holdout split
    b += rr(1030,420,826,425,"#F7F4FC","#B8A5D4",1.4,18)+t(1056,455,"03  CHALLENGE — 留出设计复验",15,800,PURPLE)
    b += rr(1080,510,230,110,"white",PURPLE,1.5,12)+t(1195,548,"source design",15,740,PURPLE,"middle")+t(1195,580,"effect +1.862",16,760,TEAL,"middle")
    b += line(1310,565,1420,565,PURPLE)
    b += rr(1420,490,360,150,"white",PURPLE,1.5,12)+t(1600,525,"unseen holdout",15,740,PURPLE,"middle")+t(1600,558,"same direction? magnitude? CI?",12,500,MUTED,"middle")+t(1600,598,"full-flow hard gates still pass?",12,500,MUTED,"middle")
    b += path("M1600,640 L1600,690 L1320,690",TEAL,2,True)+path("M1600,640 L1600,760 L1320,760",RED,2,True)
    b += pill(1090,672,230,"VALIDATED",TEAL,"#EAF7F2")+pill(1090,742,230,"REFUTED",RED,"#FFF0F1")
    # state machine
    b += rr(64,880,1792,175,"#F1F8F5","#9BC6B7",1.4,18)+t(90,915,"04  ADMIT — 状态机而非成功日志",15,800,TEAL)
    states=[("candidate",BLUE),("tested",ORANGE),("validated",TEAL),("refuted",RED),("retired",SLATE)]
    for i,(s,col) in enumerate(states):
        x=210+i*310; b+=pill(x,955,205,s.upper(),col,"white")
        if i<4: b+=line(x+205,972,x+295,972,col,2)
    b += t(960,1032,"所有状态保留 run IDs、artifact SHA、context key、falsifier；知识只影响检索，不直接获得执行权。",13,600,MUTED,"middle")
    return base(3,"自演化不是“记住成功”：它是一条可证伪、可拒绝的知识准入链","观察 → 假设 → 组合干预 → 留出复验 → 状态机；负迁移与成功经验同等重要。",b,"冻结学习矩阵｜12 个 source→holdout 方向，288/288 真实 ORFS runs；6 validated，6 refuted，并阻止 6 条错误迁移。")


def fig4():
    b=""
    b += t(64,225,"同一条来源经验，在不同上下文中可以得到相反结论。卡片记录的是证据边界，不是万能规则。",16,500,MUTED)
    def card(x,y,title,status,scol,source,hold,effect,reason):
        q=rr(x,y,820,735,"white",scol,2,20,shadow=True)
        q+=f'<rect x="{x}" y="{y}" width="820" height="74" rx="20" fill="{scol}"/>'+t(x+28,y+46,title,20,760,"white")+pill(x+610,y+20,180,status,"white",scol)
        fields=[("CONTEXT KEY","source=GCD · mechanism=parameter interaction · same protocol"),("SOURCE EVIDENCE",source),("HOLDOUT CHALLENGE",hold),("EFFECT / DIRECTION",effect),("FALSIFIER",reason),("PROVENANCE","run IDs · artifact SHA-256 · tool commit · parser version"),("AUTHORITY","action_eligible = "+("true" if status=="VALIDATED" else "false")+"\nexecution_allowed = false")]
        yy=y+115
        for label,val in fields:
            q+=t(x+30,yy,label,11,800,scol)+t(x+205,yy,val,13,520,INK); q+=f'<line x1="{x+30}" y1="{yy+25}" x2="{x+790}" y2="{yy+25}" stroke="#E1E7EE"/>'; yy+=82 if "\n" in val else 72
        return q
    b+=card(100,270,"Knowledge Card A · 可迁移条件","VALIDATED",TEAL,"GCD interaction = +1.862","GCD → UART TX = +0.532","same positive direction on unseen design","reject if sign flips, hard gate fails, or protocol mismatches")
    b+=card(1000,270,"Knowledge Card B · 负迁移边界","REFUTED",RED,"GCD interaction = +1.862","GCD → FIFO = -1.596","direction reversed on unseen design","observed sign reversal is the falsifier; block retrieval as action")
    b += path("M920,620 C960,580 960,580 1000,620",PURPLE,2.3,True,"7 6")+t(960,558,"same source\ndifferent context",12,700,PURPLE,"middle")
    return base(4,"知识卡到底学到了什么？—— 两张真实卡片的对照","知识卡同时保存正证据、反证、适用上下文、复验条件和执行权限。",b,"实例｜validated 只允许作为下一轮提案的证据；refuted 会主动阻止错误迁移；两者 execution_allowed 均为 false。")


def fig5():
    b=""
    # main design-space map
    b += rr(64,220,1080,810,"#FBFCFE","#CAD5E2",1.4,18)+t(90,258,"A  GP posterior over a joint parameter space",15,800,PURPLE)
    x0,y0,w,h=150,350,860,560
    # contour heat field from layered translucent ellipses
    b += rr(x0,y0,w,h,"#F4F0FA","#8F7BB4",1.4,8)
    colors=["#D9EAF7","#B7DCCF","#F7D6B7","#EAA36F"]
    for i,(cx,cy,rx,ry) in enumerate([(390,690,260,175),(650,560,240,155),(800,720,180,130),(520,480,150,100)]):
        b+=f'<ellipse cx="{cx}" cy="{cy}" rx="{rx}" ry="{ry}" fill="{colors[i]}" fill-opacity=".58" stroke="{colors[i]}"/>'
    # grid and observed points
    for i in range(1,6): b+=line(x0+i*w/6,y0,x0+i*w/6,y0+h,"#D9E0EA",1,False)+line(x0,y0+i*h/6,x0+w,y0+i*h/6,"#D9E0EA",1,False)
    pts=[(250,780),(340,610),(430,760),(520,520),(600,670),(720,470),(820,610),(900,800),(760,760),(470,420)]
    for i,(x,y) in enumerate(pts): b+=f'<circle cx="{x}" cy="{y}" r="8" fill="white" stroke="{NAVY}" stroke-width="3"/>'
    b += f'<circle cx="{720}" cy="{470}" r="19" fill="none" stroke="{ORANGE}" stroke-width="4"/>'+t(745,454,"best observed",12,700,ORANGE)
    b += f'<path d="M835,505 l16,30 h-32 z" fill="{RED}"/>'+t(865,535,"argmax EI",12,700,RED)
    b += t(580,948,"parameter 1 (normalized)",14,650,MUTED,"middle")+t(104,650,"parameter 2",14,650,MUTED,"middle")
    b += pill(180,292,220,"○ observed run",NAVY,"white")+pill(420,292,250,"△ next candidate",RED,"white")+pill(690,292,390,"color = GP mean / uncertainty",PURPLE,"white")
    # algorithm rail
    b += rr(1180,220,676,505,"#F7F4FC","#B8A5D4",1.4,18)+t(1205,258,"B  One BO/GP iteration",15,800,PURPLE)
    steps=[("aggregate replicas","mean + sample variance / n"),("fit 3 exact RBF GPs","area · WNS · power"),("scalarize preference","balanced / area / timing / power"),("EI × feasibility","512 deterministic LHS pool"),("run 3 paired seeds","real OpenROAD full-flow")]
    yy=300
    for i,(a,c) in enumerate(steps):
        b+=icon_circle(1230,yy+24,str(i+1),PURPLE,17)+t(1260,yy+18,a,15,720)+t(1260,yy+44,c,12,450,MUTED)
        if i<4:b+=line(1230,yy+44,1230,yy+78,PURPLE,1.8)
        yy+=82
    # campaign result
    b += rr(1180,755,676,275,"#F1F8F5","#9BC6B7",1.4,18)+t(1205,793,"C  Frozen campaign result",15,800,TEAL)
    b += t(1220,842,"BO/GP wins",14,650,MUTED)+t(1510,842,"33 / 40",28,820,TEAL)
    b += t(1220,890,"paired mean Δ",14,650,MUTED)+t(1510,890,"+0.001614",24,800,NAVY)
    b += t(1220,934,"bootstrap 95% CI",14,650,MUTED)+t(1510,934,"[0.000923, 0.002354]",17,760,NAVY)
    b += t(1220,978,"sign-flip p",14,650,MUTED)+t(1510,978,"0.000490",20,800,NAVY)
    return base(5,"BO 与 GP 如何在组合参数空间中选择下一次实验？","代理模型给出均值与不确定性，EI 选择值得尝试的联合配置；真实 OpenROAD 结果再回填模型。",b,"边界｜40 个 design×policy-seed 配对单元；逐设计 Holm 仅 GCD 与 ibex_alu 显著，四设计聚类敏感性 exact p=0.125。")


def fig6():
    b=""
    # Four transformation strata
    xs=[64,430,850,1280]; widths=[320,370,380,576]
    heads=[("RAW ARTIFACTS",NAVY),("PROVENANCE",BLUE),("TYPED EDAIR",CYAN),("AGENT QUERY",PURPLE)]
    for (x,w),(label,col) in zip(zip(xs,widths),heads):
        b+=rr(x,220,w,760,"white",col,1.7,18,shadow=True)+f'<rect x="{x}" y="{220}" width="{w}" height="58" rx="18" fill="{col}"/>'+t(x+22,257,label,15,800,"white")
    raw=[("timing.rpt","slack -0.083  U17/Q → U42/D"),("route.log","[WARN] overflow at GCell (41,18)"),("design.def","- U42 NAND2_X1 + PLACED (1240 880)"),("constraints.sdc","create_clock -period 2.0 clk"),("netlist.v","NAND2_X1 U42 (.A(n17), .ZN(n22))")]
    yy=310
    for a,c in raw:
        b+=rr(84,yy,280,95,"#F7F9FC","#D5DEE8",1,10)+t(100,yy+27,a,13,760,NAVY)+t(100,yy+55,c,10,450,MUTED);yy+=118
    prov=[("artifact_id","sha256: 91ad…"),("tool_commit","openroad @ 4f82…"),("flow_seed","OR_SEED = 17"),("parser_version","timing/v3"),("source_span","timing.rpt : 812–816"),("stage","route / finish")]
    yy=315
    for a,c in prov:
        b+=t(455,yy,a,12,760,BLUE)+t(590,yy,c,12,520,INK);b+=f'<line x1="455" y1="{yy+17}" x2="{770}" y2="{yy+17}" stroke="#E0E7EF"/>';yy+=76
    b += rr(455,790,320,140,"#FFF0F1",RED,1.3,10)+t(475,820,"LOSS MANIFEST",13,800,RED)+t(475,850,"parser dropped 2 optional fields\nUNKNOWN preserved; never guessed",12,500,MUTED)
    typed=[("metric","setup_wns = -0.083 ns"),("timing_path","U17/Q → U42/D"),("instance","U42 : NAND2_X1"),("physical","(1240, 880) · GCell(41,18)"),("relation","pin → net → cell → path"),("confidence","parsed / source-backed")]
    yy=315
    for a,c in typed:
        b+=rr(875,yy,330,72,"#EFF8F8",CYAN,1.1,10)+t(895,yy+27,a.upper(),10,800,CYAN)+t(895,yy+52,c,12,570,INK);yy+=92
    # query ladder and mini result
    levels=[("L0","KPI","Is timing closed?"),("L1","STAGE","Where did WNS regress?"),("L2","OBJECT GRAPH","Which cell/net/path explains it?"),("L3","RAW EXCERPT","Show exact source bytes")]
    yy=310
    for i,(lv,a,c) in enumerate(levels):
        b+=icon_circle(1320,yy+25,lv,PURPLE,23)+rr(1360,yy,455,58,"#F7F4FC",PURPLE,1.2,10)+t(1380,yy+23,a,12,800,PURPLE)+t(1505,yy+23,c,12,500,INK)
        if i<3:b+=line(1320,yy+48,1320,yy+78,PURPLE,1.7)
        yy+=92
    b += path("M1780,650 C1840,650 1840,920 1210,920",ORANGE,2.2,True,"8 6")+t(1530,905,"insufficient evidence → artifact byte fallback",12,700,ORANGE,"middle")
    b += rr(1310,745,500,125,"#F1F8F5",TEAL,1.4,12)+t(1335,780,"240 diagnostic questions",13,750,TEAL)+t(1335,815,"KPI-only 4.17%  →  Typed EDAIR 93.33%",18,820,INK)+t(1335,845,"false-answer rate: 3.75% → 1.67%",12,550,MUTED)
    for i in range(3):b+=line(xs[i]+widths[i],600,xs[i+1]-12,600,heads[i][1],2.4)
    return base(6,"EDA 数据如何变成 AI 可查询、低失真的证据？","不是把长日志压成一段摘要；原始字节、解析来源、对象关系和信息损失同时保留。",b,"QA 消融｜224/240 vs 10/240；调用级 exact p=3.81e-6。该结果证明诊断可读性，不等价于 PPA 必然提升。")


def fig7():
    b=""
    # dual lanes
    b += rr(64,220,1792,200,"#F2F6FC","#A9C3DD",1.4,18)+t(90,255,"SPEC CONTRACT",15,800,BLUE)
    b += rr(100,290,320,80,"white",BLUE,1.5,12)+t(260,320,"Natural-language request",15,720,BLUE,"middle")+t(260,348,"ports · behavior · reset · constraints",12,450,MUTED,"middle")
    b += line(420,330,530,330,BLUE)+rr(530,275,410,110,"white",CYAN,1.6,12)+t(735,310,"Spec Agent → SpecIR",17,760,CYAN,"middle")+t(735,343,"explicit assumptions + acceptance criteria",12,450,MUTED,"middle")
    b += line(940,330,1060,330,CYAN)
    b += path("M1060,330 L1170,275",PURPLE,2.2,True)+path("M1060,330 L1170,385",ORANGE,2.2,True)
    b += rr(1170,235,300,90,"#F5F1FA",PURPLE,1.6,12)+t(1320,270,"Verification Agent",16,760,PURPLE,"middle")+t(1320,298,"TB · SVA · mutation plan",12,450,MUTED,"middle")
    b += rr(1170,345,300,90,"#FFF4EC",ORANGE,1.6,12)+t(1320,380,"RTL Author Agent",16,760,ORANGE,"middle")+t(1320,408,"candidate RTL branches",12,450,MUTED,"middle")
    b += rr(1530,275,280,110,"white",RED,1.6,12)+t(1670,310,"Isolation contract",16,760,RED,"middle")+t(1670,342,"Author cannot edit tests\nVerifier cannot edit RTL",12,500,MUTED,"middle")
    # scout candidate tree
    b += rr(64,455,1792,450,"#FFFCF9","#E7B894",1.4,18)+t(90,492,"RTLSCOUT CANDIDATE EVOLUTION",15,800,ORANGE)
    b += rr(110,570,190,90,"white",ORANGE,1.6,12)+t(205,606,"parent C0",16,760,ORANGE,"middle")+t(205,634,"lineage + SHA",12,450,MUTED,"middle")
    candidates=[(430,530,"C1","compile fail",RED),(430,650,"C2","sim mismatch",RED),(720,530,"C3","mutation weak",PURPLE),(720,650,"C4","all functional gates",TEAL),(1030,590,"C5","lower cost",GREEN)]
    for x,y,a,c,col in candidates:
        b+=rr(x,y,210,80,"white",col,1.7,12,shadow=True)+t(x+105,y+31,a,16,780,col,"middle")+t(x+105,y+58,c,11,500,MUTED,"middle")
    b+=path("M300,615 C350,615 350,570 430,570",ORANGE,2,True)+path("M300,615 C350,615 350,690 430,690",ORANGE,2,True)
    b+=path("M640,570 L720,570",RED,2,True)+path("M640,690 L720,690",RED,2,True)+path("M930,690 C980,690 980,630 1030,630",TEAL,2,True)
    # gates
    gates=[("1","compile / elaborate",BLUE),("2","lint / structural",CYAN),("3","frozen-TB simulation",PURPLE),("4","mutation adequacy",ORANGE),("5","Yosys/ABC cost",TEAL)]
    xx=1280
    for i,(n,a,col) in enumerate(gates):
        b+=icon_circle(xx,540+i*65,n,col,16)+t(xx+28,546+i*65,a,13,650,col)
    b += path("M825,530 C825,465 1320,465 1320,325",PURPLE,1.8,True,"6 6")+t(1060,458,"weak tests → Verification Agent",12,700,PURPLE,"middle")
    b += path("M535,530 C535,445 1320,495 1320,435",RED,1.8,True,"6 6")+t(760,472,"RTL failure → Author Agent",12,700,RED,"middle")
    # promotion/result
    b += rr(64,940,1792,125,"#F1F8F5","#9BC6B7",1.4,18)+t(92,976,"PROMOTION",14,800,TEAL)
    b += t(250,1005,"C5",25,820,TEAL)+line(310,998,430,998,TEAL)+t(455,990,"independent replay",15,720,INK)+line(610,998,730,998,TEAL)+t(755,990,"OpenROAD baseline / PPA",15,720,INK)
    b += pill(1120,968,210,"18 / 20 pass",TEAL,"white")+pill(1345,968,210,"65% first-pass",BLUE,"white")+pill(1570,968,210,"5 rescued",ORANGE,"white")
    return base(7,"RTL 生成链：写 RTL、写测试、固定评估三者怎样协作？","双 Agent 隔离避免“自己出题自己判卷”；RTLScout 是候选演化与多层质量门，不是一个黑盒名词。",b,"冻结 RTL 矩阵｜FIFO 5/5、GCD 5/5、ibex_alu 4/5、UART TX 4/5；ibex_alu 是子模块，四题不代表任意芯片。")


def fig8():
    b=""
    panels=[(64,220,560,350,"A  RTL reliability",BLUE),(656,220,560,350,"B  BO/GP vs random",PURPLE),(1248,220,608,350,"C  EDAIR fidelity",CYAN),(64,605,860,430,"D  Knowledge transfer matrix",ORANGE),(956,605,900,430,"E  Agent gate ablation",TEAL)]
    for x,y,w,h,title,col in panels:b+=rr(x,y,w,h,"white",col,1.4,16,shadow=True)+t(x+22,y+34,title,15,800,col)
    # RTL bars
    vals=[("FIFO",5,5),("GCD",5,5),("ibex_alu",4,5),("UART TX",4,5)]
    for i,(a,v,n) in enumerate(vals):
        y=300+i*54;b+=t(95,y+15,a,12,650);b+=rr(190,y,350,26,"#EEF2F6","#EEF2F6",0,13);b+=rr(190,y,350*v/n,26,BLUE,BLUE,0,13);b+=t(555,y+19,f"{v}/{n}",12,750,BLUE,"end")
    b+=t(95,530,"20 trials · 18 complete passes · 5 iterative rescues",12,600,MUTED)
    # paired BO counts and CI
    b+=t(690,292,"paired units",12,650,MUTED)+t(1135,292,"40",19,800,PURPLE,"end")
    b+=rr(700,330,430,40,"#EEE8F6","#EEE8F6",0,20)+rr(700,330,355,40,PURPLE,PURPLE,0,20)+t(878,356,"BO/GP wins 33",13,750,"white","middle")+t(1095,356,"random 7",12,700,PURPLE,"middle")
    b+=line(750,440,1090,440,NAVY,3,False);b+=line(840,425,840,455,NAVY,3,False)+line(1050,425,1050,455,NAVY,3,False)+f'<circle cx="945" cy="440" r="9" fill="{ORANGE}"/>'
    b+=t(945,410,"mean Δ +0.001614",13,750,ORANGE,"middle")+t(945,480,"bootstrap 95% CI [0.000923, 0.002354]",11,550,MUTED,"middle")
    # EDAIR paired accuracy
    for i,(a,v,col) in enumerate([("KPI-only",4.17,SLATE),("Typed EDAIR",93.33,CYAN)]):
        y=330+i*100;b+=t(1285,y+20,a,13,700,col)+rr(1410,y,370,36,"#EEF2F6","#EEF2F6",0,18)+rr(1410,y,370*v/100,36,col,col,0,18)+t(1795,y+25,f"{v:.2f}%",13,800,col,"end")
    b+=t(1285,520,"224/240 vs 10/240 · exact p=3.81e-6",12,600,MUTED)
    # matrix 4x4, diagonal unavailable
    designs=["FIFO","GCD","ibex","UART"]
    gridx,gridy=290,710;cell=112
    for i,d in enumerate(designs):b+=t(gridx+i*cell+cell/2,690,d,12,700,MUTED,"middle")+t(250,gridy+i*65+35,d,12,700,MUTED,"end")
    matrix=[[None,"+","−","+"],["−",None,"+","+"],["+","−",None,"−"],["−","+","+",None]]
    count=0
    for r in range(4):
        for c in range(4):
            val=matrix[r][c]; x=gridx+c*cell;y=gridy+r*65
            if val is None: fill="#EEF2F6";lab="—";col=SLATE
            elif count<6: fill="#E6F5EF";lab="VALID";col=TEAL;count+=1
            else: fill="#FDEBED";lab="REFUTED";col=RED
            b+=rr(x,y,100,52,fill,col,1,7)+t(x+50,y+32,lab,10,750,col,"middle")
    b+=t(825,740,"12 directed",13,750,ORANGE,"middle")+t(825,775,"holdouts",13,750,ORANGE,"middle")+t(825,825,"6 validated",17,820,TEAL,"middle")+t(825,865,"6 refuted",17,820,RED,"middle")+t(825,910,"6 wrong transfers",12,650,MUTED,"middle")+t(825,935,"blocked",12,650,MUTED,"middle")
    # ablation lollipops
    rows=[("Full architecture",0,TEAL,"0 violations"),("remove checkpoint",2,BLUE,"2 duplicate runs"),("remove authority gate",12,ORANGE,"12 unsafe hypotheses"),("remove review gate",8,RED,"8 false promotions")]
    for i,(a,v,col,lab) in enumerate(rows):
        y=710+i*72;b+=t(995,y+18,a,12,650);b+=line(1180,y+12,1720,y+12,"#DCE3EB",2,False);x=1180+v/12*540;b+=line(1180,y+12,x,y+12,col,6,False)+f'<circle cx="{x}" cy="{y+12}" r="9" fill="{col}"/>'+t(1740,y+18,lab,11,700,col)
    b+=t(995,1000,"Unit of analysis is explicitly stated in each panel; no repair regression is folded into the frozen 18/20 RTL statistic.",11,550,MUTED)
    return base(8,"论文结果总览：五个研究问题对应五类证据","不只展示最好值：每个面板注明统计单位、对照、置信区间或反例边界。",b,"结果边界｜OR_SEED 不是独立设计；Typed EDAIR 的 QA 提升不等于 PPA 提升；Agent 安全性不等于 QoR 自动提高。")


ENGLISH_TEXT = {
"OpenROAD–Evolve：从自然语言规格到受保护自演化的完整闭环":"OpenROAD–Evolve: A Protected Self-Evolving Loop from Natural-Language Specification",
"三条平面共享同一证据合同；模型负责提案，固定 Runtime 负责执行，Reviewer 负责晋级。":"Three planes share one evidence contract: models propose, protected Runtime executes, and Reviewer promotes.",
"总览图｜实线表示受保护执行；虚线表示反馈或学习；图中 repair 仅为诊断换向，未声称已执行 v3 工具。":"Overview | Solid lines denote protected execution; dashed lines denote feedback or learning. Repair is diagnostic redirection, not v3 tool execution.",
"Agent 框架：八阶段推理围绕一个受保护执行核":"Agent Architecture: Eight-Stage Reasoning around a Protected Execution Kernel",
"八阶段不是八个随意聊天的 Agent；权限、产物类型与晋级权在 Runtime 边界内被硬编码。":"The stages are typed roles, not free-form chat; authority and promotion are encoded at the Runtime boundary.",
"Agent 消融｜完整架构：0 duplicate、0 unsupported executable hypothesis、0 below-threshold promotion、100% evidence completeness。":"Agent ablation | Full architecture: 0 duplicates, 0 unsupported executable hypotheses, 0 sub-threshold promotions, 100% evidence completeness.",
"自演化不是“记住成功”：它是一条可证伪、可拒绝的知识准入链":"Self-Evolution Is Not Success Logging: A Falsifiable Knowledge-Admission Chain",
"观察 → 假设 → 组合干预 → 留出复验 → 状态机；负迁移与成功经验同等重要。":"Observe → hypothesize → intervene → holdout-test → state transition; negative transfer is first-class evidence.",
"冻结学习矩阵｜12 个 source→holdout 方向，288/288 真实 ORFS runs；6 validated，6 refuted，并阻止 6 条错误迁移。":"Frozen learning matrix | 12 directed holdouts, 288/288 real ORFS runs; 6 validated, 6 refuted, 6 erroneous transfers blocked.",
"形成可证伪的问题":"construct a falsifiable question","2×2 组合干预":"2x2 factorial intervention","留出设计复验":"unseen-design holdout","状态机而非成功日志":"state machine, not success log","不是“这个参数好像更好”，而是预注册怎样证伪":"Pre-register how the claim can fail.","所有状态保留 run IDs、artifact SHA、context key、falsifier；知识只影响检索，不直接获得执行权。":"Every state preserves run IDs, artifact SHA, context key, and falsifier; memory informs retrieval but never executes.",
"知识卡到底学到了什么？—— 两张真实卡片的对照":"What Does the System Learn? Two Contrasting Evidence Cards",
"知识卡同时保存正证据、反证、适用上下文、复验条件和执行权限。":"A card stores support, refutation, context, replay conditions, and authority.","同一条来源经验，在不同上下文中可以得到相反结论。卡片记录的是证据边界，不是万能规则。":"The same source experience can reverse under a new context. Cards record evidence boundaries, not universal rules.","Knowledge Card A · 可迁移条件":"Knowledge Card A · transferable condition","Knowledge Card B · 负迁移边界":"Knowledge Card B · negative-transfer boundary","实例｜validated 只允许作为下一轮提案的证据；refuted 会主动阻止错误迁移；两者 execution_allowed 均为 false。":"Example | Validated evidence may guide proposals; refuted evidence blocks transfer. Both keep execution_allowed=false.",
"BO 与 GP 如何在组合参数空间中选择下一次实验？":"How BO and GP Select the Next Joint-Parameter Experiment",
"代理模型给出均值与不确定性，EI 选择值得尝试的联合配置；真实 OpenROAD 结果再回填模型。":"The surrogate predicts mean and uncertainty; EI selects a joint configuration; real OpenROAD results update the model.","边界｜40 个 design×policy-seed 配对单元；逐设计 Holm 仅 GCD 与 ibex_alu 显著，四设计聚类敏感性 exact p=0.125。":"Boundary | 40 paired design-by-policy-seed cells; Holm significance only for GCD and ibex_alu; four-design clustered exact p=0.125.",
"EDA 数据如何变成 AI 可查询、低失真的证据？":"How EDA Artifacts Become Queryable, Low-Loss AI Evidence",
"不是把长日志压成一段摘要；原始字节、解析来源、对象关系和信息损失同时保留。":"Raw bytes, parse provenance, object relations, and information loss are preserved instead of replaced by one summary.","QA 消融｜224/240 vs 10/240；调用级 exact p=3.81×10⁻⁶。该结果证明诊断可读性，不等价于 PPA 必然提升。":"QA ablation | 224/240 vs 10/240; invocation-level exact p=3.81e-6. This measures diagnostic usability, not guaranteed PPA gain.",
"QA 消融｜224/240 vs 10/240；调用级 exact p=3.81e-6。该结果证明诊断可读性，不等价于 PPA 必然提升。":"QA ablation | 224/240 vs 10/240; invocation-level exact p=3.81e-6. This measures diagnostic usability, not guaranteed PPA gain.",
"RTL 生成链：写 RTL、写测试、固定评估三者怎样协作？":"RTL Generation: How Authoring, Verification, and Fixed Evaluation Cooperate",
"双 Agent 隔离避免“自己出题自己判卷”；RTLScout 是候选演化与多层质量门，不是一个黑盒名词。":"Separated agents prevent self-grading; RTLScout is candidate evolution plus explicit quality gates, not a black-box label.","冻结 RTL 矩阵｜FIFO 5/5、GCD 5/5、ibex_alu 4/5、UART TX 4/5；ibex_alu 是子模块，四题不代表任意芯片。":"Frozen RTL matrix | FIFO 5/5, GCD 5/5, ibex_alu 4/5, UART TX 4/5; ibex_alu is a submodule and four tasks do not imply arbitrary-chip generality.",
"论文结果总览：五个研究问题对应五类证据":"Results Overview: Five Research Questions, Five Evidence Types",
"不只展示最好值：每个面板注明统计单位、对照、置信区间或反例边界。":"Beyond best values: each panel states its unit, control, uncertainty, or counterexample boundary.","结果边界｜OR_SEED 不是独立设计；Typed EDAIR 的 QA 提升不等于 PPA 提升；Agent 安全性不等于 QoR 自动提高。":"Boundaries | OR_SEED is not an independent design; EDAIR QA gain is not PPA gain; agent safety is not automatic QoR improvement.",
}


def english_variant(svg: str) -> str:
    for source, target in sorted(ENGLISH_TEXT.items(), key=lambda item: len(item[0]), reverse=True):
        svg = svg.replace(escape(source), escape(target))
    return svg


def main():
    figures=[fig1,fig2,fig3,fig4,fig5,fig6,fig7,fig8]
    names=["01_完整workflow_重制版","02_Agent框架与执行约束_重制版","03_自演化学习机制_重制版","04_知识卡实例_重制版","05_BO_GP参数探索_重制版","06_EDA到AI数据接口_重制版","07_RTL生成链_重制版","08_论文实验结果_重制版"]
    for make,name in zip(figures,names):
        svg=make(); sp=SRC/f"{name}.svg"; pp=OUT/f"{name}.png"
        sp.write_text(svg,encoding="utf-8")
        cairosvg.svg2png(bytestring=svg.encode(),write_to=str(pp),output_width=2880,output_height=1800)
        english=english_variant(svg); esp=SRC/f"{name}_English.svg"; epp=EN/f"{name}_English.png"
        esp.write_text(english,encoding="utf-8")
        cairosvg.svg2png(bytestring=english.encode(),write_to=str(epp),output_width=2880,output_height=1800)
    (OUT/"README_重制版.md").write_text("科研图重制版：PNG为交付文件；可编辑源文件/中保存SVG。颜色编码：蓝=系统，绿=受保护证据，橙=提案，紫=学习，红=拒绝/越权。\n",encoding="utf-8")


if __name__ == "__main__":
    main()
