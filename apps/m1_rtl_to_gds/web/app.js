(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const serviceState = $("serviceState");
  const identityState = $("identityState");
  let token = null;
  let authSession = null;
  let specSession = null;
  let version = null;
  let versions = [];
  let runKind = null;

  const terminalStates = new Set(["succeeded", "failed", "cancelled", "timed_out"]);

  function setText(id, value) {
    $(id).textContent = value == null ? "" : String(value);
  }

  function setStatus(id, label, kind = "neutral") {
    const element = $(id);
    element.textContent = label;
    element.className = "status-pill " + kind;
  }

  function setServiceState(label, kind = "neutral") {
    serviceState.textContent = label;
    serviceState.className = "status-pill " + kind;
  }

  function clearNode(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  function setSvg(id, source) {
    const parsed = new DOMParser().parseFromString(source, "image/svg+xml").documentElement;
    if (parsed.nodeName.toLowerCase() !== "svg") throw new Error("v2 preview is not SVG");
    const output = $(id);
    clearNode(output);
    output.append(document.importNode(parsed, true));
  }

  function appendArtifact(list, kind, value) {
    const row = document.createElement("li");
    const name = document.createElement("span");
    const state = document.createElement("span");
    name.textContent = kind;
    state.className = "artifact-state";
    state.textContent = value;
    row.append(name, state);
    list.append(row);
  }

  async function requestJson(path, options = {}) {
    const headers = { Accept: "application/json", "Content-Type": "application/json" };
    if (token) headers.Authorization = "Bearer " + token;
    const response = await fetch(path, { headers, ...options });
    const body = await response.json();
    if (!response.ok) throw new Error((body.error && body.error.message) || ("HTTP " + response.status));
    return body;
  }

  function showError(error) {
    setText("specMessage", error.message);
    const callout = $("evidenceMessage");
    clearNode(callout);
    callout.className = "callout unavailable";
    const title = document.createElement("strong");
    title.textContent = "Execution unavailable";
    const detail = document.createElement("span");
    detail.textContent = error.message;
    callout.append(title, detail);
  }

  function setStage(id, label, kind) {
    setStatus(id, label, kind);
  }

  function renderAuth() {
    $("loginForm").hidden = Boolean(authSession);
    $("logoutButton").hidden = !authSession;
    identityState.textContent = authSession && authSession.user
      ? authSession.user.username || authSession.user.id
      : "v2 session unavailable";
  }

  function renderSession() {
    const state = (specSession && specSession.state) || "draft";
    setText("specState", state.replaceAll("_", " "));
    setText("specMessage", specSession
      ? state === "needs_clarification"
        ? "Clarification is required before the specification can be frozen."
        : state === "specified"
          ? "Specification is complete. Freeze it before RTL generation."
          : state === "frozen"
            ? "Specification frozen. Generate or edit RTL."
            : specSession.unsupported_reason || state
      : "No specification assessed.");
    setText("clarificationQuestions", (specSession && specSession.clarification_questions || []).join(" "));
    $("freezeButton").textContent = state === "specified" ? "Freeze specification" :
      state === "needs_clarification" ? "Re-assess specification" : "Assess specification";
    $("freezeButton").disabled = !specSession && !$("specInput").value.trim();
    if (specSession) $("freezeButton").disabled = state === "frozen" || state === "unsupported_scope";
    $("generateButton").disabled = state !== "frozen";
  }

  function renderVersion(source) {
    const verification = version && version.verification_status;
    setText("rtlState", version ? verification.replaceAll("_", " ") : "No version");
    setText("rtlHash", version ? version.rtl_sha256 : "No staged input");
    setText("selectedRtlVersion", version ? version.version_id : "No version selected");
    setText("verificationGate", version && version.simulation_status === "passed"
      ? "Verified and simulated" : verification || "Not verified");
    $("verifyButton").disabled = !version || verification === "running";
    $("simulateButton").disabled = !version || verification !== "passed" || version.simulation_status === "running";
    $("newVersionButton").disabled = !version;
    $("gdsButton").disabled = !version || version.simulation_status !== "passed";
    $("pdkSelect").disabled = !version || version.simulation_status !== "passed";
    if (source !== null && source !== undefined) $("rtlEditor").value = source;
    renderVerification();
    renderVersionList();
  }

  function renderVerification() {
    const verification = version ? version.verification_status : "not_run";
    const simulation = version ? version.simulation_status : "not_run";
    const state = simulation === "passed" ? "Verified" :
      verification === "passed" ? "Compile passed" :
      ["failed", "invalidated"].includes(verification) ? verification.replaceAll("_", " ") :
      verification === "running" ? "Running" : "Not run";
    const kind = state === "Verified" || state === "Compile passed" ? "good" :
      ["failed", "invalidated"].includes(verification) ? "warn" : "neutral";
    setStatus("verificationState", state, kind);
    setText("compileMark", verification === "passed" ? "✓" : verification === "failed" ? "×" : "—");
    setText("compileDetail", version ? verification.replaceAll("_", " ") : "Waiting for a version");
    setText("simulationMark", simulation === "passed" ? "✓" : simulation === "failed" ? "×" : "—");
    setText("simulationDetail", version ? simulation.replaceAll("_", " ") : "Frozen oracle required");
    setText("mutationMark", "—");
    setText("mutationDetail", "Not registered for this M1 package");
  }

  function renderVersionList() {
    const list = $("versionList");
    clearNode(list);
    setText("versionCount", versions.length);
    if (!versions.length) {
      const empty = document.createElement("li");
      empty.className = "empty-list";
      empty.textContent = "No versions yet.";
      list.append(empty);
      return;
    }
    versions.forEach((item) => {
      const row = document.createElement("li");
      const button = document.createElement("button");
      button.type = "button";
      button.className = item.version_id === (version && version.version_id) ? "selected" : "";
      button.textContent = item.version_id + " · " + item.generator + " · " + item.verification_status;
      button.addEventListener("click", () => selectVersion(item.version_id).catch(showError));
      row.append(button);
      list.append(row);
    });
  }

  async function selectVersion(versionId) {
    const data = await requestJson("/api/m1/rtl/" + encodeURIComponent(versionId));
    version = data.rtl_version;
    renderVersion(data.source);
    await renderDiff(version.version_id, version.parent_version_id);
  }

  async function renderDiff(leftId, rightId) {
    const output = $("versionDiff");
    if (!leftId || !rightId) {
      output.textContent = "Select a version with a parent to inspect the version boundary.";
      return;
    }
    const [left, right] = await Promise.all([
      requestJson("/api/m1/rtl/" + encodeURIComponent(leftId)),
      requestJson("/api/m1/rtl/" + encodeURIComponent(rightId)),
    ]);
    const leftLines = left.source.split("\n");
    const rightLines = right.source.split("\n");
    const lines = [];
    const count = Math.max(leftLines.length, rightLines.length);
    for (let index = 0; index < count; index += 1) {
      if (leftLines[index] === rightLines[index]) lines.push("  " + (leftLines[index] || ""));
      else {
        if (leftLines[index] !== undefined) lines.push("- " + leftLines[index]);
        if (rightLines[index] !== undefined) lines.push("+ " + rightLines[index]);
      }
    }
    output.textContent = lines.join("\n");
  }

  function clearEvidence() {
    setText("runState", "No run selected");
    setText("runStateDetail", "No run selected");
    setStatus("workbenchAvailability", "Unavailable");
    const artifactList = $("artifactList");
    clearNode(artifactList);
    ["gds", "def", "odb", "netlist", "report"].forEach((kind) => appendArtifact(artifactList, kind, "Unavailable"));
    clearNode($("metricsList"));
    setText("netlistOutput", "A verified run is required before the netlist can be read.");
    setText("layoutOutput", "GDS / DEF renderings will cite their v2 artifact hash.");
    setText("qorOutput", "No area, timing, power or DRC values are available.");
    setStatus("netlistStatus", "Unavailable");
    setStatus("layoutStatus", "Unavailable");
    setStatus("qorStatus", "No measurement");
    setText("evidenceMetadata", "No EvidenceRef registered.");
    setStage("stageInputStatus", version ? "Ready" : "Unavailable", version ? "good" : "neutral");
    setStage("stageOrfsStatus", "Unavailable", "neutral");
    setStage("stageEvidenceStatus", "Unavailable", "neutral");
  }

  function renderRun(run) {
    setText("runState", run.run_id + ": " + run.status);
    setText("runStateDetail", run.status);
    setStatus("workbenchAvailability", run.status === "succeeded" ? "Measured" : run.status,
      run.status === "succeeded" ? "good" : run.status === "failed" ? "warn" : "neutral");
    const active = ["queued", "running", "retry_wait"].includes(run.status);
    const terminal = terminalStates.has(run.status);
    setStage("stageInputStatus", version ? "Ready" : "Unavailable", version ? "good" : "neutral");
    setStage("stageOrfsStatus", active ? "Running" : terminal ? run.status : "Unavailable",
      active ? "warn" : terminal && run.status === "succeeded" ? "good" : "neutral");
    setStage("stageEvidenceStatus", run.status === "succeeded" ? "Ready" : "Unavailable",
      run.status === "succeeded" ? "good" : "neutral");
  }

  async function refreshVersion() {
    if (!version) return;
    const data = await requestJson("/api/m1/rtl/" + encodeURIComponent(version.version_id));
    version = data.rtl_version;
    renderVersion(data.source);
  }

  async function refreshVersions() {
    if (!specSession) {
      versions = [];
      renderVersionList();
      return;
    }
    const data = await requestJson("/api/m1/specs/" + encodeURIComponent(specSession.spec_id) + "/versions");
    versions = data.versions;
    renderVersionList();
  }

  async function refreshEvidence(id) {
    const [timeline, artifactsReply, metricsReply, logsReply] = await Promise.all([
      requestJson("/api/m1/runs/" + encodeURIComponent(id) + "/timeline"),
      requestJson("/api/m1/runs/" + encodeURIComponent(id) + "/artifacts"),
      requestJson("/api/m1/runs/" + encodeURIComponent(id) + "/metrics"),
      requestJson("/api/m1/runs/" + encodeURIComponent(id) + "/logs"),
    ]);
    const artifacts = artifactsReply.artifacts || [];
    const metrics = metricsReply.metrics || [];
    const eventList = $("timelineEvents");
    clearNode(eventList);
    if (!timeline.timeline.length) eventList.append(document.createTextNode("No stage events returned by v2."));
    timeline.timeline.forEach((event) => {
      const item = document.createElement("li");
      item.textContent = [event.timestamp || "", event.event_type || event.status || "", event.message || ""].filter(Boolean).join(" · ");
      eventList.append(item);
    });
    setText("runLogs", (logsReply.logs || []).map((item) => "[" + item.stream + "] " + item.text).join("\n") || "No logs returned by v2.");
    const artifactList = $("artifactList");
    clearNode(artifactList);
    if (!artifacts.length) appendArtifact(artifactList, "all artifacts", "Unavailable");
    artifacts.forEach((item) => appendArtifact(artifactList, item.kind, item.sha256 || "hash unavailable"));
    const metricsList = $("metricsList");
    clearNode(metricsList);
    metrics.forEach((item) => appendArtifact(metricsList, item.name, String(item.value) + (item.unit ? " " + item.unit : "")));
    setText("qorOutput", metrics.length ? metrics.map((item) => item.name + ": " + item.value + (item.unit ? " " + item.unit : "")).join("\n") : "No area, timing, power or DRC values are available.");
    setStatus("qorStatus", metrics.length ? "Measured" : "Unavailable", metrics.length ? "good" : "neutral");

    const netlist = artifacts.find((item) => item.kind === "netlist");
    if (netlist) {
      const rendered = await requestJson("/api/m1/runs/" + encodeURIComponent(id) + "/artifacts/" + encodeURIComponent(netlist.artifact_id) + "/netlist");
      if (rendered.status === "ready") {
        setSvg("netlistOutput", rendered.content);
        setStatus("netlistStatus", "Rendered · " + (netlist.sha256 || "").slice(0, 12), "good");
      } else {
        setText("netlistOutput", "Unavailable: " + (rendered.reason || "renderer returned no content"));
        setStatus("netlistStatus", "Unavailable");
      }
    }
    const layout = artifacts.find((item) => item.kind === "gds") || artifacts.find((item) => item.kind === "def");
    if (layout) {
      const preview = await requestJson("/api/m1/runs/" + encodeURIComponent(id) + "/artifacts/" + encodeURIComponent(layout.artifact_id) + "/preview");
      const value = preview.preview || preview;
      if (value.status === "ready") {
        setSvg("layoutOutput", value.content);
        setStatus("layoutStatus", "Rendered · " + (layout.sha256 || "").slice(0, 12), "good");
      } else {
        setText("layoutOutput", "Unavailable: " + (value.reason || "v2 did not return a preview"));
        setStatus("layoutStatus", "Unavailable");
      }
    }
    try {
      const evidence = await requestJson("/api/m1/evidence/evidence:" + encodeURIComponent(id));
      setText("evidenceMetadata", JSON.stringify(evidence.evidence, null, 2));
    } catch (error) {
      setText("evidenceMetadata", "No succeeded EvidenceRef: " + error.message);
    }
    setStage("stageEvidenceStatus", artifacts.length ? "Ready" : "Unavailable", artifacts.length ? "good" : "neutral");
  }

  async function pollRun(id) {
    const run = (await requestJson("/api/m1/runs/" + encodeURIComponent(id))).run;
    renderRun(run);
    if (terminalStates.has(run.status)) {
      await refreshEvidence(id);
      await refreshVersion();
      const callout = $("evidenceMessage");
      clearNode(callout);
      callout.className = "callout" + (run.status === "succeeded" ? "" : " unavailable");
      const title = document.createElement("strong");
      title.textContent = runKind + " " + run.status;
      const detail = document.createElement("span");
      detail.textContent = "Run " + id + " is recorded by v2.";
      callout.append(title, detail);
      return;
    }
    window.setTimeout(() => pollRun(id).catch(showError), 1000);
  }

  async function submitRun(path, kind, payload = {}) {
    const data = await requestJson(path, { method: "POST", body: JSON.stringify(payload) });
    runKind = kind;
    setText("runState", data.run_id + ": submitted");
    renderRun({ run_id: data.run_id, status: "queued" });
    await pollRun(data.run_id);
  }

  async function assessOrFreeze() {
    if (!specSession || specSession.state === "needs_clarification") {
      specSession = (await requestJson("/api/m1/specs", {
        method: "POST", body: JSON.stringify({ description: $("specInput").value }),
      })).session;
      version = null;
      versions = [];
      renderVersion(null);
      clearEvidence();
    } else if (specSession.state === "specified") {
      specSession = (await requestJson("/api/m1/specs/" + encodeURIComponent(specSession.spec_id) + "/freeze", {
        method: "POST", body: "{}",
      })).session;
    }
    renderSession();
    await refreshVersions();
  }

  async function refreshCatalog() {
    const [courses, pdks] = await Promise.all([
      requestJson("/api/m1/catalog/courses"),
      requestJson("/api/m1/catalog/pdks"),
    ]);
    const courseList = $("courseCatalog");
    clearNode(courseList);
    courses.courses.forEach((course) => {
      const item = document.createElement("li");
      const title = document.createElement("span");
      const meta = document.createElement("span");
      title.textContent = course.exercise.title;
      meta.className = "artifact-state";
      meta.textContent = course.exercise.level;
      item.append(title, meta);
      courseList.append(item);
    });
    const body = $("pdkCatalog");
    clearNode(body);
    pdks.capabilities.forEach((record) => {
      const row = document.createElement("tr");
      [record.exercise_id, record.pdk_id, record.status, record.reason || "—"].forEach((value) => {
        const cell = document.createElement("td");
        cell.textContent = value;
        row.append(cell);
      });
      body.append(row);
    });
    setText("catalogState", courses.courses.length + " exercises · " + pdks.capabilities.length + " capability records");
  }

  async function refreshSession() {
    const data = await requestJson("/api/auth/session");
    authSession = data.session;
    renderAuth();
    if (authSession) {
      const records = await requestJson("/api/m1/specs");
      specSession = records.sessions[0] || null;
      if (specSession) {
        $("specInput").value = specSession.spec ? specSession.spec.functionality : "";
        renderSession();
        await refreshVersions();
      }
    }
  }

  async function refresh() {
    setServiceState("Checking v2…");
    try {
      const health = await requestJson("/api/m1/health");
      setServiceState(health.status === "ok" ? "v2 connected" : "v2 unavailable", health.status === "ok" ? "good" : "warn");
      if (health.identity) setText("identityState", health.identity);
      await refreshCatalog();
      if (token) await refreshSession();
    } catch (error) {
      setServiceState("v2 unavailable", "warn");
      showError(error);
    }
  }

  function selectTab(button, panel, otherButton, otherPanel) {
    button.classList.add("selected");
    button.setAttribute("aria-selected", "true");
    otherButton.classList.remove("selected");
    otherButton.setAttribute("aria-selected", "false");
    panel.hidden = false;
    otherPanel.hidden = true;
  }

  $("studioTab").addEventListener("click", () => selectTab($("studioTab"), $("studioPanel"), $("workbenchTab"), $("workbenchPanel")));
  $("workbenchTab").addEventListener("click", () => selectTab($("workbenchTab"), $("workbenchPanel"), $("studioTab"), $("studioPanel")));
  $("refreshButton").addEventListener("click", () => refresh().catch(showError));
  $("loginForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const result = await requestJson("/api/auth/login", { method: "POST", body: JSON.stringify({
        username: $("usernameInput").value, password: $("passwordInput").value,
      }) });
      token = result.token;
      authSession = result.session;
      renderAuth();
      await refresh();
    } catch (error) { showError(error); }
  });
  $("logoutButton").addEventListener("click", async () => {
    await requestJson("/api/auth/logout", { method: "POST", body: "{}" });
    token = null;
    authSession = null;
    specSession = null;
    version = null;
    versions = [];
    renderAuth();
    renderSession();
    renderVersion(null);
    clearEvidence();
  });
  $("freezeButton").addEventListener("click", () => assessOrFreeze().catch(showError));
  $("generateButton").addEventListener("click", async () => {
    try {
      version = (await requestJson("/api/m1/specs/" + encodeURIComponent(specSession.spec_id) + "/generate", { method: "POST", body: "{}" })).rtl_version;
      clearEvidence();
      await refreshVersion();
      await refreshVersions();
    } catch (error) { showError(error); }
  });
  $("newVersionButton").addEventListener("click", async () => {
    try {
      version = (await requestJson("/api/m1/specs/" + encodeURIComponent(specSession.spec_id) + "/rtl", {
        method: "POST", body: JSON.stringify({ rtl_source: $("rtlEditor").value, generator: "user_edit", parent_version_id: version.version_id }),
      })).rtl_version;
      clearEvidence();
      await refreshVersion();
      await refreshVersions();
    } catch (error) { showError(error); }
  });
  $("verifyButton").addEventListener("click", () => submitRun("/api/m1/rtl/" + version.version_id + "/verify", "Verification").catch(showError));
  $("simulateButton").addEventListener("click", () => submitRun("/api/m1/rtl/" + version.version_id + "/simulate", "Simulation").catch(showError));
  $("gdsButton").addEventListener("click", () => submitRun("/api/m1/rtl/" + version.version_id + "/gds", "RTL-to-GDS", { pdk: $("pdkSelect").value }).catch(showError));
  $("pdkSelect").addEventListener("change", () => { $("gdsButton").textContent = "Run " + $("pdkSelect").value + " to GDS"; });

  renderAuth();
  renderSession();
  renderVersion(null);
  clearEvidence();
  refresh().catch(showError);
})();
