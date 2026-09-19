(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const serviceState = $("serviceState");
  const identityState = $("identityState");

  function setServiceState(label, kind = "neutral") {
    serviceState.textContent = label;
    serviceState.className = `status-pill ${kind}`;
  }

  async function readJson(path) {
    const response = await fetch(path, { headers: { Accept: "application/json" } });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  }

  async function refresh() {
    setServiceState("Checking v2…");
    try {
      const health = await readJson("/api/m1/health");
      setServiceState(health.status === "ok" ? "v2 connected" : "v2 unavailable", health.status === "ok" ? "good" : "warn");
      identityState.textContent = health.identity || "v2 session not identified";
    } catch (error) {
      setServiceState("v2 unavailable", "warn");
      identityState.textContent = "No execution data loaded";
      $("specMessage").textContent = "The M1 service is unavailable; no execution task was created.";
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
  $("refreshButton").addEventListener("click", refresh);
  $("freezeButton").addEventListener("click", () => {
    $("specMessage").textContent = "Spec assessment is not connected to a Teaching API yet; no task was created.";
    $("specState").textContent = "Needs API";
  });
  refresh();
})();
