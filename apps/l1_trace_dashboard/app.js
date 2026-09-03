const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));
const missing = label => `<p class="missing">Historical trace: ${esc(label)} not stored.</p>`;
const refs = items => {
  const valid = (items || []).filter(x => x && typeof x.ref === "string" && x.ref);
  return valid.length ? valid.map(x => `<code>${esc(x.ref)}</code>`).join(" · ") : "missing";
};
const pairs = value => Object.entries(value || {}).map(([key, item]) => `${esc(key)}=${esc(typeof item === "object" ? JSON.stringify(item) : item)}`).join(", ") || "none";
const eventRef = event => event ? `event #${event.sequence} (${esc(event.kind)})` : "missing";
async function api(path) { const response = await fetch(path); if (!response.ok) throw Error(await response.text()); return response.json(); }

function goalPanel(draft, goal) {
  const ir = goal?.facts.goal_ir, questions = draft?.facts.clarification_questions, answers = draft?.facts.clarification_answers;
  const validQuestions = Array.isArray(questions) ? questions.filter(q => q && q.field && q.prompt) : [];
  const validAnswers = Array.isArray(answers) ? answers.filter(a => a && a.field && a.value) : [];
  const questionText = questions === undefined ? missing("clarification questions") : validQuestions.length ? `<p>${pairs(Object.fromEntries(validQuestions.map(q => [q.field, q.prompt])))}</p>` : questions.length ? missing("complete clarification questions") : "<p>None requested.</p>";
  const answerText = answers === undefined ? missing("clarification answers") : validAnswers.length ? `<p><b>Answers:</b> ${pairs(Object.fromEntries(validAnswers.map(a => [a.field, a.value])))}</p>` : answers.length ? missing("complete clarification answers") : "<p>None recorded.</p>";
  return `<h2>① User / Goal IR</h2><h3>User request</h3><blockquote>${esc(draft?.facts.request_text || "Historical trace: request text not stored.")}</blockquote><p><b>Parsed intent:</b> ${esc(draft?.facts.intent || "missing")}</p><h3>Clarification</h3>${questionText}${answerText}<h3>Final typed Goal IR</h3>${ir ? `<p><b>Design/platform:</b> ${esc(ir.design_id)} / ${esc(ir.platform)}</p><p><b>Objective:</b> ${esc(ir.preference)} · <b>constraints:</b> ${pairs(Object.fromEntries((ir.hard_constraints || []).map(x => [x.metric, `${x.operator} ${x.threshold}`])))}</p><p><b>PDK/toolchain:</b> ${esc(ir.pdk_id)} / ${esc(ir.toolchain_id)}</p><p><b>Budget:</b> ${pairs(ir.budget)} · <b>allowed tools:</b> ${esc((ir.allowed_tools || []).join(", "))}</p><p><b>RTL evidence:</b> ${refs([ir.rtl_artifact])}</p>` : missing("full Goal IR")}`;
}
function toolPanel(calls, policies, receipts, transitions) {
  return `<h2>② Typed Tool → Policy → Runtime Receipt</h2>${calls.map((call, index) => {
    const id = call.facts.call_id, policy = policies.find(x => x.facts.call_id === id), receipt = receipts.find(x => x.facts.call_id === id), transition = transitions.find(x => x.sequence > (receipt?.sequence ?? Number.MAX_SAFE_INTEGER)), identity = policy?.facts.policy;
    return `<div class="step"><b>Step ${index + 1}: ${esc(call.tool)}</b><p><b>Planner-visible tool choice (not hidden reasoning):</b> ${call.planner_summary ? esc(call.planner_summary) : "Historical trace: tool-choice summary not stored."}</p><p><b>Typed inputs:</b> ${pairs(call.facts.arguments)}</p><p><b>Precondition:</b> current typed Goal + DesignState. <b>Policy:</b> ${esc(policy?.policy_verdict || "missing")}${identity ? ` (${esc(identity.policy_id)}@${esc(identity.policy_version)}, ${esc(identity.issuer)})` : ""}</p><p><b>Policy provenance:</b> ${refs(policy?.evidence)} · <b>Postcondition:</b> Runtime receipt required.</p><p><b>Receipt:</b> ${esc(receipt?.facts.status || "missing")} · evidence ${refs(receipt?.evidence)} · <b>Next fact:</b> ${eventRef(transition)}</p></div>`;
  }).join("") || "<p>No typed tool call.</p>"}`;
}
function statePanel(transitions) {
  return `<h2>③ Verified DesignState</h2>${transitions.map(event => {
    const before = event.facts.state_before, after = event.facts.state_after;
    if (!before || !after) return `<div class="step">${missing("DesignState snapshots")}</div>`;
    const keys = new Set([...Object.keys(before.metrics || {}), ...Object.keys(after.metrics || {})]);
    const delta = [...keys].map(key => `${key}: ${before.metrics?.[key] ?? "—"} → ${after.metrics?.[key] ?? "—"}`).join("; ") || "no metrics";
    return `<div class="step"><b>Runtime ${esc(event.facts.terminal_status)}</b> · run <code>${esc(event.facts.run_id)}</code> · attempt <code>${esc(event.facts.attempt_id)}</code><p><b>State:</b> ${esc(before.status)} → ${esc(after.status)} · revision ${esc(before.revision)} → ${esc(after.revision)} · stage ${esc(before.completed_stage || "none")} → ${esc(after.completed_stage || "none")}</p><p><b>Measured metrics:</b> ${esc(delta)}</p><p><b>Remaining budget:</b> ${esc(pairs(before.remaining_budget))} → ${esc(pairs(after.remaining_budget))}</p><p><b>Evidence:</b> ${refs(event.evidence)}</p></div>`;
  }).join("") || "<p>No verified transition.</p>"}`;
}
function decisionPanel(reflection, events) {
  if (!reflection) return "<h2>④ Evidence-based Decision</h2><p>No recorded next decision.</p>";
  const bases = (reflection.facts.basis_event_ids || []).map(id => events.find(x => x.event_id === id)).filter(Boolean), facts = bases.filter(x => x.kind === "state_transition");
  return `<h2>④ Evidence-based Decision</h2><p><b>Proven facts:</b> ${facts.length ? facts.map(x => `${eventRef(x)}: ${esc(x.facts.terminal_status)}; ${esc(pairs(x.facts.metrics))}`).join(" · ") : "missing durable state basis"}</p><p><b>Recorded hypotheses (unverified):</b> ${Object.keys(reflection.hypotheses || {}).length ? esc(pairs(reflection.hypotheses)) : "none recorded"}</p><p><b>Decision:</b> ${esc(reflection.facts.decision)} · <b>basis:</b> ${bases.map(eventRef).join(" · ") || "missing"}</p><p><b>Evidence refs:</b> ${refs(reflection.evidence)}</p><p><em>Planner-visible summary, not hidden reasoning:</em> ${esc(reflection.planner_summary)}</p>`;
}
function audit(events) { return events.map(event => `<article class="event ${esc(event.kind)}"><b>#${event.sequence} ${esc(event.kind)}</b><details><summary>Durable audit references</summary><p>event id: <code>${esc(event.event_id)}</code> · parent: <code>${esc(event.parent_event_id || "none")}</code></p><p>Evidence: ${refs(event.evidence)}</p></details></article>`).join(""); }
function loadView(data) {
  const events = data.events, draft = events.find(x => x.kind === "goal_drafted"), goal = events.find(x => x.kind === "goal_finalized"), calls = events.filter(x => x.kind === "tool_called"), policies = events.filter(x => x.kind === "policy_decided"), receipts = events.filter(x => x.kind === "tool_receipt"), transitions = events.filter(x => x.kind === "state_transition"), reflection = events.filter(x => x.kind === "reflection_recorded").at(-1);
  $("#goal").innerHTML = goalPanel(draft, goal); $("#tools").innerHTML = toolPanel(calls, policies, receipts, transitions); $("#state").innerHTML = statePanel(transitions); $("#decision").innerHTML = decisionPanel(reflection, events); $("#timeline").innerHTML = audit(events); $("#status").textContent = `${data.event_count} durable events`;
}
async function go() { try { loadView(await api("/api/traces/" + $("#traces").value)); } catch (error) { $("#status").textContent = error.message; } }
async function init() { const data = await api("/api/traces"); $("#traces").innerHTML = data.traces.map(x => `<option>${esc(x)}</option>`).join(""); go(); }
$("#load").onclick = go; init();
