(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const serviceState = $("serviceState");
  const identityState = $("identityState");
  let session = null;
  let version = null;
  let runKind = null;

  function setServiceState(label, kind = "neutral") {
    serviceState.textContent = label;
    serviceState.className = "status-pill " + kind;
  }

  async function requestJson(path, options = {}) {
    const response = await fetch(path, {
      headers: { Accept: "application/json", "Content-Type": "application/json" },
      ...options,
    });
    const body = await response.json();
    if (!response.ok) throw new Error((body.error && body.error.message) || ("HTTP " + response.status));
    return body;
  }

  function showError(error) {
    $("specMessage").textContent = error.message;
    $("evidenceMessage").className = "callout unavailable";
    $("evidenceMessage").innerHTML = "<strong>Execution failed</strong><span>" + error.message + "</span>";
  }

  function renderSession() {
    const state = (session && session.state) || "draft";
    $("specState").textContent = state.replaceAll("_", " ");
    $("specMessage").textContent = session
      ? state === "needs_clarification"
        ? "Clarification is required before the specification can be frozen."
        : state === "specified"
          ? "Specification is complete. Freeze it before RTL generation."
          : state === "frozen"
            ? "Specification frozen. Generate or edit RTL."
            : state
      : "No specification assessed.";
    $("clarificationQuestions").textContent = (session && session.clarification_questions || []).join(" ");
    $("freezeButton").textContent = state === "specified" ? "Freeze specification" : "Assess specification";
    $("freezeButton").disabled = state === "needs_clarification" || state === "frozen";
    $("generateButton").disabled = state !== "frozen";
  }

  function renderVersion(source) {
    $("rtlState").textContent = version ? version.verification_status.replaceAll("_", " ") : "No version";
    $("rtlHash").textContent = version ? version.rtl_sha256 : "No staged input";
    $("selectedRtlVersion").textContent = (version && version.version_id) || "No version selected";
    $("verificationGate").textContent = version && version.simulation_status === "passed"
      ? "Verified and simulated" : (version && version.verification_status) || "Not verified";
    $("verifyButton").disabled = !version || version.verification_status === "running";
    $("simulateButton").disabled = !version || version.verification_status !== "passed";
    $("newVersionButton").disabled = !version;
    $("gdsButton").disabled = !version || version.simulation_status !== "passed";
    $("pdkSelect").disabled = !version || version.simulation_status !== "passed";
    if (source !== null && source !== undefined) $("rtlEditor").value = source;
  }

  async function refreshVersion() {
    if (!version) return;
    const data = await requestJson("/api/m1/rtl/" + version.version_id);
    version = data.rtl_version;
    renderVersion(data.source);
  }

  function renderRun(run) {
    $("runState").textContent = run.run_id + ": " + run.status;
    $("runStateDetail").textContent = run.status;
    $("workbenchAvailability").textContent = run.status === "succeeded" ? "Measured" : run.status;
  }

  async function refreshEvidence(id) {
    const values = await Promise.all([
      requestJson("/api/m1/runs/" + id + "/timeline"),
      requestJson("/api/m1/runs/" + id + "/artifacts"),
      requestJson("/api/m1/runs/" + id + "/metrics"),
    ]);
    $("artifactList").innerHTML = values[1].artifacts.map((item) =>
      "<li><span>" + item.kind + "</span><span class=\"artifact-state\">" + item.sha256 + "</span></li>"
    ).join("");
    $("metricsList").innerHTML = values[2].metrics.map((item) =>
      "<li><span>" + item.name + "</span><span class=\"artifact-state\">" + item.value + " " + (item.unit || "") + "</span></li>"
    ).join("");
    $("timeline").dataset.events = values[0].timeline.length;
  }

  async function pollRun(id) {
    const run = (await requestJson("/api/m1/runs/" + id)).run;
    renderRun(run);
    if (["succeeded", "failed", "cancelled", "timed_out"].includes(run.status)) {
      await refreshEvidence(id);
      await refreshVersion();
      if (run.status === "succeeded") {
        $("evidenceMessage").className = "callout";
        $("evidenceMessage").innerHTML = "<strong>" + runKind + " succeeded</strong><span>Run " + id + " is recorded by v2.</span>";
      }
      return;
    }
    window.setTimeout(() => pollRun(id).catch(showError), 1000);
  }

  async function submitRun(path, kind, payload = {}) {
    const data = await requestJson(path, { method: "POST", body: JSON.stringify(payload) });
    runKind = kind;
    $("runState").textContent = data.run_id + ": submitted";
    pollRun(data.run_id).catch(showError);
  }

  async function assessOrFreeze() {
    if (!session) {
      session = (await requestJson("/api/m1/specs", {
        method: "POST",
        body: JSON.stringify({ description: $("specInput").value }),
      })).session;
    } else if (session.state === "specified") {
      session = (await requestJson("/api/m1/specs/" + session.spec_id + "/freeze", {
        method: "POST", body: "{}",
      })).session;
    }
    renderSession();
  }

  $("studioTab").addEventListener("click", () => selectTab($("studioTab"), $("studioPanel"), $("workbenchTab"), $("workbenchPanel")));
  $("workbenchTab").addEventListener("click", () => selectTab($("workbenchTab"), $("workbenchPanel"), $("studioTab"), $("studioPanel")));
  $("refreshButton").addEventListener("click", refresh);
  $("freezeButton").addEventListener("click", () => assessOrFreeze().catch(showError));
  $("generateButton").addEventListener("click", async () => {
    try {
      version = (await requestJson("/api/m1/specs/" + session.spec_id + "/generate", { method: "POST", body: "{}" })).rtl_version;
      await refreshVersion();
    } catch (error) { showError(error); }
  });
  $("newVersionButton").addEventListener("click", async () => {
    try {
      version = (await requestJson("/api/m1/specs/" + session.spec_id + "/rtl", {
        method: "POST",
        body: JSON.stringify({ rtl_source: $("rtlEditor").value, generator: "user_edit", parent_version_id: version.version_id }),
      })).rtl_version;
      await refreshVersion();
    } catch (error) { showError(error); }
  });
  $("verifyButton").addEventListener("click", () => submitRun("/api/m1/rtl/" + version.version_id + "/verify", "Verification").catch(showError));
  $("simulateButton").addEventListener("click", () => submitRun("/api/m1/rtl/" + version.version_id + "/simulate", "Simulation").catch(showError));
  $("gdsButton").addEventListener("click", () => submitRun(
    "/api/m1/rtl/" + version.version_id + "/gds", "RTL-to-GDS",
    { pdk: $("pdkSelect").value }
  ).catch(showError));
  $("pdkSelect").addEventListener("change", () => {
    $("gdsButton").textContent = "Run " + $("pdkSelect").value + " to GDS";
  });

  function selectTab(button, panel, otherButton, otherPanel) {
    button.classList.add("selected");
    button.setAttribute("aria-selected", "true");
    otherButton.classList.remove("selected");
    otherButton.setAttribute("aria-selected", "false");
    panel.hidden = false;
    otherPanel.hidden = true;
  }

  async function refresh() {
    setServiceState("Checking v2…");
    try {
      const health = await requestJson("/api/m1/health");
      setServiceState(health.status === "ok" ? "v2 connected" : "v2 unavailable", health.status === "ok" ? "good" : "warn");
      identityState.textContent = health.identity || "v2 session not identified";
    } catch (error) {
      setServiceState("v2 unavailable", "warn");
      identityState.textContent = "No execution data loaded";
      showError(error);
    }
  }

  renderSession();
  renderVersion(null);
  refresh();
})();
