/* OpenROAD Workbench dashboard.
 *
 * The dashboard owns no state: everything is read from the daemon and every
 * clickable element opens a real object.  Terminal frames are rendered on the
 * server, so the browser needs no terminal emulator.
 */
'use strict';

const STAGE_ORDER = ['synth', 'floorplan', 'place', 'cts', 'grt', 'route', 'finish'];

const S = {
  state: null,
  activeSession: null,
  ws: null,
  selected: null,
  mode: 'log',
  events: [],
  toolCatalog: null,
  previewArtifact: null,
  previewText: null,
};

const $ = (sel) => document.querySelector(sel);

function esc(value) {
  return String(value == null ? '' : value).replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

async function api(path, options) {
  const response = await fetch(path, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || ('HTTP ' + response.status));
  return data;
}

function toast(message) {
  const node = document.createElement('div');
  node.className = 'toast';
  node.textContent = message;
  document.body.appendChild(node);
  setTimeout(() => node.remove(), 4200);
}

function fmtTime(ts) {
  if (!ts) return '-';
  const d = new Date(ts * 1000);
  return d.toTimeString().slice(0, 8);
}

/* ------------------------------------------------------------------ loading */
async function refresh() {
  try {
    S.state = await api('/api/state');
  } catch (error) {
    $('#status-pill').textContent = 'DAEMON DOWN';
    $('#status-pill').className = 'pill failed';
    return;
  }
  const sessions = S.state.sessions || [];
  if (!S.activeSession || !sessions.some((s) => s.id === S.activeSession)) {
    S.activeSession = sessions.length ? sessions[0].id : null;
    if (S.activeSession) connectTerminal(S.activeSession);
  }
  renderAll();
}

/* ----------------------------------------------------------------- rendering */
function renderAll() {
  renderTop();
  renderTree();
  renderTimeline();
  renderInspector();
  renderBottom();
}

function activeSession() {
  return (S.state.sessions || []).find((s) => s.id === S.activeSession) || null;
}

function activeRun() {
  const session = activeSession();
  if (!session) return null;
  return (S.state.runs || []).find((r) => r.id === session.current_run_id) || null;
}

function renderTop() {
  const session = activeSession();
  const designs = S.state.designs || [];
  $('#design-btn').textContent = designs.length ? designs[0].name : '未登记';
  $('#session-btn').textContent = session ? session.name : '—';
  const run = activeRun();
  $('#run-text').textContent = run ? (run.command + '  ' + run.elapsed_text) : '空闲';
  const pill = $('#status-pill');
  const status = session ? session.status : 'exited';
  pill.textContent = status.toUpperCase();
  pill.className = 'pill ' + status;
  $('#cwd-text').textContent = session ? session.cwd : '—';
  $('#pid-text').textContent = session ? session.pid : '—';
  const mcp = S.state.mcp || {};
  $('#mcp-text').textContent = mcp.available ? '已连接' : '未找到';
  document.querySelector('#mcp-text').className = 'v ' + (mcp.available ? '' : 'muted');
}

function renderTree() {
  const parts = [];
  const designs = S.state.designs || [];
  parts.push('<div class="group">设计</div>');
  if (!designs.length) {
    parts.push('<div class="empty">未登记设计目录</div>');
  } else {
    designs.forEach((d) => {
      parts.push(node('design', d.id, d.name, '<span class="tag mono">' + esc(shortPath(d.path)) + '</span>'));
    });
  }

  parts.push('<div class="group">终端</div>');
  (S.state.sessions || []).forEach((s) => {
    parts.push(node(
      'session', s.id, s.name,
      '<span class="dot ' + esc(s.status) + '"></span><span class="tag">' + esc(s.status) +
      (s.pid ? ' · ' + s.pid : '') + '</span>'
    ));
  });

  parts.push('<div class="group">运行</div>');
  const runs = S.state.runs || [];
  if (!runs.length) parts.push('<div class="empty">暂无运行记录</div>');
  runs.slice(0, 14).forEach((r) => {
    parts.push(node(
      'run', r.id, (r.command || '(unknown)').slice(0, 34),
      '<span class="dot ' + esc(r.status) + '"></span><span class="tag">' + esc(r.started_text || '') + '</span>'
    ));
  });

  const counts = S.state.artifacts || {};
  const kinds = [['report', '报告'], ['image', '图像'], ['metric', '指标'], ['log', '日志'], ['script', '脚本'], ['data', '数据']];
  parts.push('<div class="group">结果</div>');
  const present = kinds.filter(([k]) => counts[k]);
  if (!present.length) parts.push('<div class="empty">尚未索引到产物</div>');
  present.forEach(([kind, label]) => {
    parts.push(node('kind', kind, label, '<span class="tag">' + counts[kind] + '</span>'));
  });

  $('#tree').innerHTML = parts.join('');
}

function shortPath(path) {
  if (!path) return '';
  const bits = String(path).split('/').filter(Boolean);
  return bits.length > 2 ? '…/' + bits.slice(-2).join('/') : path;
}

function node(kind, id, label, extra) {
  const selected = S.selected && S.selected.kind === kind && S.selected.id === id;
  return '<div class="node' + (selected ? ' selected' : '') + '" data-kind="' + esc(kind) +
    '" data-id="' + esc(id) + '"><span class="name">' + esc(label) + '</span>' + (extra || '') + '</div>';
}

function renderTimeline() {
  const session = activeSession();
  const run = activeRun();
  const rows = [];
  if (run) {
    const observed = run.stages || [];
    const current = observed.length ? observed[observed.length - 1] : null;
    STAGE_ORDER.forEach((stage) => {
      const index = observed.indexOf(stage);
      const active = stage === current && run.status === 'running';
      const done = index >= 0 && !active;
      const cls = done ? 'done' : (active ? 'active' : 'wait');
      const text = done ? 'DONE' : (active ? 'RUNNING' : 'WAITING');
      rows.push('<div class="stage-row" data-stage="' + stage + '"><span class="stage-name">' + stage +
        '</span><span class="stage-status ' + cls + '">' + text + '</span></div>');
    });
    rows.push('<div class="stage-row"><span class="stage-name muted">command</span><span class="mono">' +
      esc(run.command) + '</span></div>');
    rows.push('<div class="stage-row"><span class="stage-name muted">elapsed</span><span class="mono">' +
      esc(run.elapsed_text) + '</span></div>');
  } else {
    rows.push('<div class="empty">' + (session ? '当前终端空闲 · 命令在 TUI 中输入' : '无终端') + '</div>');
  }
  $('#timeline').innerHTML = rows.join('');
}

function kv(pairs) {
  const rows = pairs.filter(Boolean).map(([k, v, cls]) => (
    '<div class="k">' + esc(k) + '</div><div class="v ' + (cls || '') + '">' + v + '</div>'
  ));
  return '<div class="kv">' + rows.join('') + '</div>';
}

function pathLink(path) {
  return '<span class="clickable mono" data-path="' + esc(path) + '">' + esc(path) + '</span>';
}

function renderInspector() {
  const box = $('#inspector');
  const selection = S.selected;
  if (!selection) {
    const session = activeSession();
    $('#inspector-kind').textContent = session ? 'current terminal' : '';
    if (!session) { box.innerHTML = '<div class="empty">选择一个对象</div>'; return; }
    box.innerHTML = sessionInspector(session);
    return;
  }
  const found = lookup(selection.kind, selection.id);
  if (!found) { box.innerHTML = '<div class="empty">对象已不存在</div>'; return; }
  $('#inspector-kind').textContent = selection.kind;
  if (selection.kind === 'session') box.innerHTML = sessionInspector(found);
  else if (selection.kind === 'run') box.innerHTML = runInspector(found);
  else if (selection.kind === 'artifact') box.innerHTML = artifactInspector(found);
  else if (selection.kind === 'design') box.innerHTML = designInspector(found);
  else if (selection.kind === 'kind') box.innerHTML = kindInspector(found);
}

function lookup(kind, id) {
  if (!S.state) return null;
  if (kind === 'session') return (S.state.sessions || []).find((s) => s.id === id);
  if (kind === 'run') return (S.state.runs || []).find((r) => r.id === id);
  if (kind === 'design') return (S.state.designs || []).find((d) => d.id === id);
  if (kind === 'artifact') return (S.artifactCache || []).find((a) => a.path === id || a.id === id);
  if (kind === 'kind') return { kind: id };
  return null;
}

function sessionInspector(session) {
  return kv([
    ['终端', esc(session.name)],
    ['状态', '<span class="pill ' + esc(session.status) + '">' + esc(session.status) + '</span>'],
    ['PID', esc(session.pid), 'mono'],
    ['cwd', pathLink(session.cwd)],
    ['shell', esc(session.shell)],
    ['尺寸', esc(session.cols + '×' + session.rows), 'mono'],
    ['启动', esc(session.started_text || fmtTime(session.started_at))],
    ['空闲时长', esc(session.last_activity_text || '-')],
    ['退出码', esc(session.exit_code == null ? '-' : session.exit_code), 'mono'],
    ['', '<button class="mini" data-action="interrupt">中断 Ctrl-C</button> ' +
         '<button class="mini danger" data-action="terminate">终止</button> ' +
         '<button class="mini" data-action="close-session">关闭</button>'],
  ]) + '<div class="group">该终端最近的运行</div>' + runChips(session.id);
}

function runChips(sessionId) {
  const runs = (S.state.runs || []).filter((r) => r.session_id === sessionId).slice(0, 10);
  if (!runs.length) return '<div class="empty">暂无</div>';
  return runs.map((r) => (
    '<div class="node" data-kind="run" data-id="' + esc(r.id) + '"><span class="dot ' + esc(r.status) +
    '"></span><span class="name mono">' + esc((r.command || '').slice(0, 30)) +
    '</span><span class="tag">' + esc(r.started_text || '') + '</span></div>'
  )).join('');
}

function runInspector(run) {
  return kv([
    ['运行', esc(run.name)],
    ['命令', '<span class="mono">' + esc(run.command) + '</span>'],
    ['状态', '<span class="pill ' + esc(run.status) + '">' + esc(run.status) + '</span>'],
    ['退出码', esc(run.exit_code == null ? '-' : run.exit_code), 'mono'],
    ['cwd', run.cwd ? pathLink(run.cwd) : '-'],
    ['开始', esc(run.started_text || fmtTime(run.started_at))],
    ['耗时', esc(run.elapsed_text || '-'), 'mono'],
    ['阶段', esc((run.stages || []).join(' → ') || '未观察到')],
    ['终端', '<span class="clickable" data-kind="session" data-id="' + esc(run.session_id) + '">' +
             esc((S.state.sessions || []).find((s) => s.id === run.session_id)?.name || run.session_id) + '</span>'],
    ['', '<button class="mini" data-action="cancel-run" data-id="' + esc(run.id) + '">停止该运行</button> ' +
         '<button class="mini" data-action="session-log" data-id="' + esc(run.session_id) + '">查看终端日志</button>'],
  ]);
}

function artifactInspector(artifact) {
  return kv([
    ['文件', esc(artifact.name)],
    ['类型', esc(artifact.kind)],
    ['阶段', esc(artifact.stage || '-')],
    ['大小', esc(artifact.size_text || '-'), 'mono'],
    ['修改', esc(artifact.mtime_text || '-')],
    ['路径', pathLink(artifact.path)],
    ['', '<button class="mini" data-action="open-artifact" data-id="' + esc(artifact.path) + '">在下方打开</button>'],
  ]);
}

function designInspector(design) {
  const counts = S.state.artifacts || {};
  const rows = Object.keys(counts).map((k) => k + '=' + counts[k]).join('  ') || '无';
  return kv([
    ['设计', esc(design.name)],
    ['路径', pathLink(design.path)],
    ['平台', esc(design.platform || '-')],
    ['存在', design.exists ? '是' : '否'],
    ['产物', esc(rows), 'mono'],
    ['', '<button class="mini" data-action="switch-design" data-id="' + esc(design.id) + '">设为当前</button> ' +
         '<button class="mini" data-action="refresh-artifacts" data-id="' + esc(design.id) + '">重扫产物</button>'],
  ]);
}

function kindInspector(found) {
  return '<div class="group">' + esc(found.kind) + ' 类产物</div>' +
    '<div class="empty">在下方列表中选择一个文件</div>';
}

function renderBottom() {
  const body = $('#bottom-body');
  const title = $('#bottom-title');
  document.querySelectorAll('.tab').forEach((tab) => {
    tab.classList.toggle('active', tab.dataset.mode === S.mode);
  });
  if (S.mode === 'events') {
    title.textContent = S.events.length + ' 条事件';
    body.innerHTML = '<div class="events">' + S.events.slice().reverse().slice(0, 200).map((e) => (
      '<div><span class="t">' + esc(new Date(e.ts * 1000).toTimeString().slice(0, 8)) +
      '</span><span class="type">' + esc(e.type) + '</span>' + esc(summarize(e)) + '</div>'
    )).join('') + '</div>';
    return;
  }
  if (S.mode === 'tools') { renderTools(body, title); return; }
  if (S.mode === 'log') {
    const session = activeSession();
    title.textContent = session ? (session.name + ' · 原始输出') : '无终端';
    if (!session) { body.innerHTML = '<div class="empty">没有终端</div>'; return; }
    return; // filled by loadLog()
  }
  renderArtifacts(body, title, S.mode);
}

function summarize(event) {
  const d = event.data || {};
  if (d.run) return (d.run.command || '') + ' [' + (d.run.status || '') + ']';
  if (d.session) return d.session.name || d.session.id || '';
  if (d.stage) return d.stage;
  if (d.design) return d.design.name || '';
  if (d.design_ids) return (d.design_ids || []).join(',');
  if (d.session_id) return d.session_id;
  return '';
}

async function renderArtifacts(body, title, kind) {
  let artifacts = [];
  try {
    artifacts = (await api('/api/artifacts?kind=' + encodeURIComponent(kind))).artifacts || [];
  } catch (error) {
    body.innerHTML = '<div class="empty">读取失败：' + esc(error.message) + '</div>';
    return;
  }
  S.artifactCache = artifacts;
  title.textContent = kind + ' · ' + artifacts.length + ' 项';
  if (S.previewArtifact) { renderPreview(body, S.previewArtifact, title); return; }
  if (!artifacts.length) {
    body.innerHTML = '<div class="empty">没有 ' + esc(kind) + ' 类产物。' +
      '在 TUI 里运行一次流程后，工作台会自动索引结果。</div>';
    return;
  }
  body.innerHTML = '<div class="grid">' + artifacts.map((a) => (
    '<div class="chip" data-action="open-artifact" data-id="' + esc(a.path) + '">' +
    '<span>' + esc(a.name) + '</span><span class="size">' + esc(a.stage || a.size_text || '') + '</span></div>'
  )).join('') + '</div>';
}

async function renderPreview(body, artifact, title) {
  title.textContent = artifact.path;
  body.innerHTML = '<div class="muted">加载中…</div>';
  const url = '/api/artifact?path=' + encodeURIComponent(artifact.path);
  if ((artifact.kind === 'image') || /\.(png|webp|jpe?g|gif|svg)$/i.test(artifact.path)) {
    body.innerHTML = '<div><button class="mini" data-action="close-preview">← 返回列表</button></div>' +
      '<div style="margin-top:6px"><img src="' + url + '" alt="' + esc(artifact.name) + '"></div>';
    return;
  }
  try {
    const response = await fetch(url);
    const text = await response.text();
    const truncated = response.headers.get('x-owb-truncated') === '1';
    body.innerHTML = '<div><button class="mini" data-action="close-preview">← 返回列表</button>' +
      (truncated ? ' <span class="muted">（已截断）</span>' : '') + '</div><pre>' + esc(text) + '</pre>';
  } catch (error) {
    body.innerHTML = '<div class="empty">无法读取：' + esc(error.message) + '</div>';
  }
}

async function renderTools(body, title) {
  if (!S.toolCatalog) {
    try {
      S.toolCatalog = (await api('/api/tools')).tools || [];
    } catch (error) {
      body.innerHTML = '<div class="empty">无法读取 MCP 工具目录：' + esc(error.message) + '</div>';
      return;
    }
  }
  title.textContent = '官方 OpenROAD-MCP · ' + S.toolCatalog.length + ' 个工具';
  body.innerHTML = S.toolCatalog.map((tool) => (
    '<div class="tool"><span class="tool-name">' + esc(tool.name) + '</span>' +
    (tool.read_only ? '<span class="ro">只读</span>' : '<span class="rw">会修改状态</span>') +
    '<button class="mini" style="float:right" data-action="call-tool" data-id="' + esc(tool.name) + '">调用</button>' +
    '<div class="desc">' + esc((tool.description || '').slice(0, 220)) + '</div></div>'
  )).join('');
}

/* ------------------------------------------------------------------ terminal */
function connectTerminal(sessionId) {
  if (S.ws) { try { S.ws.close(); } catch (e) { /* ignore */ } S.ws = null; }
  const url = (location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host +
    '/ws/terminal/' + encodeURIComponent(sessionId) + '?lines=2000';
  const ws = new WebSocket(url);
  S.ws = ws;
  ws.onmessage = (event) => {
    let frame;
    try { frame = JSON.parse(event.data); } catch (e) { return; }
    if (frame.type === 'frame') renderTerminal(frame);
  };
  ws.onclose = () => { if (S.ws === ws) setTimeout(() => { if (S.activeSession === sessionId) connectTerminal(sessionId); }, 1500); };
}

function renderTerminal(frame) {
  const node = $('#terminal');
  const atBottom = node.scrollTop + node.clientHeight >= node.scrollHeight - 24;
  node.textContent = (frame.screen || []).join('\n');
  if (atBottom) node.scrollTop = node.scrollHeight;
}

async function loadLog() {
  const session = activeSession();
  const body = $('#bottom-body');
  if (!session) { body.innerHTML = '<div class="empty">没有终端</div>'; return; }
  try {
    const response = await fetch('/api/sessions/' + encodeURIComponent(session.id) + '/log');
    const text = await response.text();
    body.innerHTML = '<pre>' + esc(text.slice(-200000)) + '</pre>';
  } catch (error) {
    body.innerHTML = '<div class="empty">读取失败：' + esc(error.message) + '</div>';
  }
}

/* -------------------------------------------------------------------- events */
function connectEvents() {
  const source = new EventSource('/api/events');
  source.onmessage = (event) => {
    let parsed;
    try { parsed = JSON.parse(event.data); } catch (e) { return; }
    S.events.push(parsed);
    if (S.events.length > 600) S.events = S.events.slice(-400);
    if (S.mode === 'events') renderBottom();
    if (['run.started', 'run.completed', 'session.started', 'session.exited', 'session.updated',
         'artifacts.updated', 'design.registered'].includes(parsed.type)) {
      scheduleRefresh();
    }
  };
  source.onerror = () => { /* EventSource reconnects on its own */ };
}

let refreshTimer = null;
function scheduleRefresh() {
  if (refreshTimer) return;
  refreshTimer = setTimeout(() => { refreshTimer = null; refresh(); }, 350);
}

/* ------------------------------------------------------------------- actions */
async function action(name, id, element) {
  try {
    if (name === 'interrupt') {
      await api('/api/sessions/' + S.activeSession + '/interrupt', { method: 'POST' });
      toast('已发送 Ctrl-C');
    } else if (name === 'terminate') {
      await api('/api/sessions/' + S.activeSession + '/terminate', { method: 'POST' });
      toast('已终止终端进程');
    } else if (name === 'close-session') {
      await api('/api/sessions/' + S.activeSession + '/close', { method: 'POST' });
      toast('已关闭终端');
      S.activeSession = null;
    } else if (name === 'cancel-run') {
      await api('/api/runs/' + encodeURIComponent(id) + '/cancel', { method: 'POST' });
      toast('已请求停止该运行');
    } else if (name === 'session-log') {
      S.activeSession = id;
      S.mode = 'log';
      await loadLog();
      renderAll();
      return;
    } else if (name === 'open-artifact') {
      const artifact = (S.artifactCache || []).find((a) => a.path === id) || { path: id, kind: S.mode, name: id.split('/').pop() };
      S.previewArtifact = artifact;
      S.selected = { kind: 'artifact', id: id };
      renderAll();
      return;
    } else if (name === 'close-preview') {
      S.previewArtifact = null;
      renderBottom();
      return;
    } else if (name === 'switch-design') {
      const design = (S.state.designs || []).find((d) => d.id === id);
      if (design) await api('/api/designs/' + design.id, { method: 'GET' });
      toast('当前设计：' + (design ? design.name : id));
      return;
    } else if (name === 'refresh-artifacts') {
      const result = await api('/api/artifacts/refresh', {
        method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ design_id: id }),
      });
      toast('已重扫产物：' + JSON.stringify(result.counts || {}));
    } else if (name === 'call-tool') {
      const raw = window.prompt('工具 ' + id + ' 的 JSON 参数：', '{}');
      if (raw == null) return;
      let args = {};
      try { args = JSON.parse(raw || '{}'); } catch (e) { toast('参数不是合法 JSON'); return; }
      const tool = (S.toolCatalog || []).find((t) => t.name === id);
      const confirm = tool && !tool.read_only ? window.confirm('该工具会修改设计状态，确认调用？') : false;
      if (tool && !tool.read_only && !confirm) return;
      const result = await api('/api/tool', {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ tool: id, arguments: args, confirm: confirm }),
      });
      S.previewArtifact = null;
      S.mode = 'tools';
      $('#bottom-body').innerHTML = '<pre>' + esc(JSON.stringify(result.result, null, 2)) + '</pre>';
      toast('工具 ' + id + ' 调用完成');
      return;
    }
    await refresh();
  } catch (error) {
    toast('操作失败：' + error.message);
  }
  void element;
}

/* --------------------------------------------------------------------- wiring */
document.addEventListener('click', (event) => {
  const target = event.target.closest('[data-action]');
  if (target) {
    event.preventDefault();
    action(target.dataset.action, target.dataset.id, target);
    return;
  }
  const pathNode = event.target.closest('[data-path]');
  if (pathNode) {
    const path = pathNode.dataset.path;
    if (S.mode === 'log') { S.mode = 'log'; }
    toast(path + '（可在下方“数据/日志”标签中浏览同目录产物）');
    return;
  }
  const nodeEl = event.target.closest('[data-kind]');
  if (nodeEl) {
    const kind = nodeEl.dataset.kind;
    const id = nodeEl.dataset.id;
    if (kind === 'session') {
      S.activeSession = id;
      connectTerminal(id);
      loadLog();
    }
    S.selected = { kind: kind, id: id };
    renderAll();
  }
});

document.querySelectorAll('.tab').forEach((tab) => {
  tab.addEventListener('click', () => {
    S.mode = tab.dataset.mode;
    S.previewArtifact = null;
    renderBottom();
    if (S.mode === 'log') loadLog();
  });
});

$('#btn-refresh').addEventListener('click', refresh);
$('#btn-new-session').addEventListener('click', newSession);
$('#btn-new-session-2').addEventListener('click', newSession);
$('#btn-interrupt').addEventListener('click', () => action('interrupt'));
$('#btn-add-design').addEventListener('click', () => $('#add-design').classList.toggle('hidden'));
$('#btn-do-add-design').addEventListener('click', async () => {
  const path = $('#design-path').value.trim();
  if (!path) return;
  try {
    await api('/api/designs', {
      method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ path: path }),
    });
    $('#design-path').value = '';
    $('#add-design').classList.add('hidden');
    toast('已登记设计：' + path);
    refresh();
  } catch (error) { toast('登记失败：' + error.message); }
});

async function newSession() {
  try {
    await api('/api/sessions', {
      method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({}),
    });
    toast('已新建终端');
    refresh();
  } catch (error) { toast('新建失败：' + error.message); }
}

window.addEventListener('resize', () => { /* layout is CSS-driven */ });

refresh().then(() => { loadLog(); });
connectEvents();
setInterval(() => { refresh(); if (S.mode === 'log') loadLog(); }, 8000);
