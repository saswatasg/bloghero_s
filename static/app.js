const state = {
  schema: [],
  stepIndex: 0,
  values: {},
  selectedGscProperty: null,
};

const $ = (sel) => document.querySelector(sel);

async function api(path, opts) {
  const res = await fetch(path, opts);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error || `Request failed: ${res.status}`);
  }
  return res.json();
}

// ---------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------
async function boot() {
  const status = await api("/api/status");
  state.values = status.config || {};

  if (status.needs_setup) {
    state.schema = await api("/api/setup-schema");
    showWizard();
  } else {
    showDashboard();
  }
}

function showWizard() {
  $("#wizard-screen").classList.remove("hidden");
  $("#dashboard-screen").classList.add("hidden");
  renderWizardNav();
  renderWizardStep();
}

function showDashboard() {
  $("#wizard-screen").classList.add("hidden");
  $("#dashboard-screen").classList.remove("hidden");
  $("#topbar-status").textContent = "Ready";
  connectLogSocket();
  refreshBacklog();
  refreshDrafts();
  refreshRunStatus();
}

// ---------------------------------------------------------------------
// Wizard
// ---------------------------------------------------------------------
function renderWizardNav() {
  const nav = $("#wizard-steps-nav");
  nav.innerHTML = "";
  state.schema.forEach((step, i) => {
    const div = document.createElement("div");
    div.className = "wizard-step-item" + (i === state.stepIndex ? " active" : i < state.stepIndex ? " done" : "");
    div.textContent = `${i + 1}. ${step.title}`;
    nav.appendChild(div);
  });
}

function renderWizardStep() {
  const step = state.schema[state.stepIndex];
  const container = $("#wizard-step-content");
  container.innerHTML = "";

  const h2 = document.createElement("h2");
  h2.textContent = step.title;
  container.appendChild(h2);

  if (step.intro) {
    const p = document.createElement("p");
    p.className = "wizard-intro";
    p.textContent = step.intro;
    container.appendChild(p);
  }

  if (step.link) {
    const a = document.createElement("a");
    a.className = "wizard-link";
    a.href = step.link.url;
    a.target = "_blank";
    a.textContent = step.link.label + " \u2197";
    container.appendChild(a);
  }

  step.fields.forEach((field) => {
    container.appendChild(renderField(field));
  });

  $("#wizard-back").disabled = state.stepIndex === 0;
  $("#wizard-next").textContent = state.stepIndex === state.schema.length - 1 ? "Finish" : "Next";
  renderWizardNav();
}

function renderField(field) {
  const wrap = document.createElement("div");
  wrap.className = "field";

  if (field.type === "file") {
    const label = document.createElement("label");
    label.textContent = field.label;
    wrap.appendChild(label);

    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".json";
    input.id = "field_" + field.key;
    wrap.appendChild(input);

    const help = document.createElement("div");
    help.className = "field-help";
    help.id = "help_" + field.key;
    help.textContent = field.help || "";
    wrap.appendChild(help);
    return wrap;
  }

  if (field.type === "gsc_picker") {
    const label = document.createElement("label");
    label.textContent = field.label;
    wrap.appendChild(label);

    const currentVal = state.values[field.key] || "";
    if (currentVal) {
      const current = document.createElement("div");
      current.className = "field-help";
      current.textContent = "Currently set to: " + currentVal;
      wrap.appendChild(current);
    }

    const btn = document.createElement("button");
    btn.className = "btn btn-ghost btn-small";
    btn.textContent = "Find my properties";
    btn.onclick = async (e) => {
      e.preventDefault();
      btn.textContent = "Connecting...";
      btn.disabled = true;
      try {
        const result = await api("/api/gsc-properties");
        renderGscOptions(result.properties || [], field.key);
      } catch (err) {
        renderGscOptions([], field.key, err.message);
      }
      btn.textContent = "Find my properties";
      btn.disabled = false;
    };
    wrap.appendChild(btn);

    const listDiv = document.createElement("div");
    listDiv.className = "gsc-picker-list";
    listDiv.id = "gsc_list_" + field.key;
    wrap.appendChild(listDiv);

    const help = document.createElement("div");
    help.className = "field-help";
    help.textContent = field.help || "";
    wrap.appendChild(help);
    return wrap;
  }

  // Plain text/secret field
  const label = document.createElement("label");
  label.textContent = field.label + (field.required ? " *" : "");
  wrap.appendChild(label);

  if (field.type === "select") {
    const select = document.createElement("select");
    select.id = "field_" + field.key;
    (field.options || []).forEach((opt) => {
      const o = document.createElement("option");
      o.value = opt.value;
      o.textContent = opt.label;
      select.appendChild(o);
    });
    const existingVal = state.values[field.key] || field.default;
    if (existingVal) select.value = existingVal;
    wrap.appendChild(select);

    if (field.help) {
      const help = document.createElement("div");
      help.className = "field-help";
      help.textContent = field.help;
      wrap.appendChild(help);
    }
    return wrap;
  }

  const input = document.createElement("input");
  input.type = field.secret ? "password" : "text";
  input.id = "field_" + field.key;
  input.placeholder = field.default || "";
  const existingVal = state.values[field.key];
  if (existingVal && !(field.secret && existingVal.includes("saved"))) {
    input.value = existingVal;
  }
  wrap.appendChild(input);

  if (field.help) {
    const help = document.createElement("div");
    help.className = "field-help";
    help.textContent = field.help;
    wrap.appendChild(help);
  }
  return wrap;
}

function renderGscOptions(properties, fieldKey, errorMsg) {
  const listDiv = $("#gsc_list_" + fieldKey);
  listDiv.innerHTML = "";
  if (errorMsg) {
    const p = document.createElement("div");
    p.className = "field-help";
    p.textContent = "Couldn't connect yet: " + errorMsg + " (make sure the service account was added as a User in Search Console).";
    listDiv.appendChild(p);
    return;
  }
  if (properties.length === 0) {
    const p = document.createElement("div");
    p.className = "field-help";
    p.textContent = "No properties visible yet - double check the service account was added as a User.";
    listDiv.appendChild(p);
    return;
  }
  properties.forEach((prop) => {
    const div = document.createElement("div");
    div.className = "gsc-option";
    div.textContent = prop;
    div.onclick = () => {
      document.querySelectorAll(".gsc-option").forEach((el) => el.classList.remove("selected"));
      div.classList.add("selected");
      state.values[fieldKey] = prop;
      state.selectedGscProperty = prop;
    };
    listDiv.appendChild(div);
  });
}

async function collectStepValues(step) {
  const updates = {};
  for (const field of step.fields) {
    if (field.type === "file") {
      const input = $("#field_" + field.key);
      if (input && input.files.length > 0) {
        const formData = new FormData();
        formData.append("file", input.files[0]);
        const result = await api("/api/upload-service-account", { method: "POST", body: formData });
        const help = $("#help_" + field.key);
        if (result.client_email) {
          help.textContent = "Saved. Service account email: " + result.client_email +
            " (paste this into Search Console and your Google Sheet's sharing settings).";
        }
      }
      continue;
    }
    if (field.type === "gsc_picker") {
      if (state.values[field.key]) updates[field.key] = state.values[field.key];
      continue;
    }
    if (field.type === "select") {
      const select = $("#field_" + field.key);
      if (select) updates[field.key] = select.value;
      continue;
    }
    const input = $("#field_" + field.key);
    if (input) {
      const val = input.value.trim();
      updates[field.key] = val || field.default || "";
    }
  }
  return updates;
}

$("#wizard-next").addEventListener("click", async () => {
  const step = state.schema[state.stepIndex];
  $("#wizard-next").disabled = true;
  try {
    const updates = await collectStepValues(step);
    Object.assign(state.values, updates);
    const result = await api("/api/setup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(updates),
    });

    if (state.stepIndex < state.schema.length - 1) {
      state.stepIndex += 1;
      renderWizardStep();
    } else if (!result.needs_setup) {
      showDashboard();
    } else {
      alert("A few required fields are still missing - check the earlier steps.");
    }
  } catch (err) {
    alert("Something went wrong saving this step: " + err.message);
  }
  $("#wizard-next").disabled = false;
});

$("#wizard-back").addEventListener("click", () => {
  if (state.stepIndex > 0) {
    state.stepIndex -= 1;
    renderWizardStep();
  }
});

$("#btn-open-setup").addEventListener("click", async () => {
  state.schema = await api("/api/setup-schema");
  state.stepIndex = 0;
  showWizard();
});

// ---------------------------------------------------------------------
// Dashboard: live log via WebSocket
// ---------------------------------------------------------------------
function connectLogSocket() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws/logs`);
  ws.onmessage = (event) => {
    const pane = $("#log-pane");
    if (pane.textContent === "Waiting for a run...") pane.textContent = "";
    pane.textContent += event.data;
    pane.scrollTop = pane.scrollHeight;
    if (event.data.includes(">>> Done.") || event.data.includes(">>> Run failed")) {
      refreshBacklog();
      refreshDrafts();
      refreshRunStatus();
    }
  };
  ws.onclose = () => setTimeout(connectLogSocket, 2000);
}

async function refreshRunStatus() {
  const s = await api("/api/run-status");
  const running = s.running;
  ["btn-research", "btn-write", "btn-run-all"].forEach((id) => ($(`#${id}`).disabled = running));
  $("#topbar-status").textContent = running ? `Running: ${s.action}...` : "Ready";
}

async function triggerRun(action) {
  $("#log-pane").textContent = "";
  try {
    await api(`/api/run/${action}`, { method: "POST" });
    refreshRunStatus();
  } catch (err) {
    alert(err.message);
  }
}

$("#btn-research").addEventListener("click", () => triggerRun("research"));
$("#btn-write").addEventListener("click", () => triggerRun("write"));
$("#btn-run-all").addEventListener("click", () => triggerRun("run-all"));

// ---------------------------------------------------------------------
// Backlog table
// ---------------------------------------------------------------------
async function refreshBacklog() {
  const rows = await api("/api/backlog");
  const tbody = document.querySelector("#backlog-table tbody");
  tbody.innerHTML = "";
  rows.forEach((r) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${r.id}</td>
      <td>${r.type}</td>
      <td>${r.topic_or_page}</td>
      <td>${r.category}</td>
      <td><span class="badge badge-${(r.priority || "").toLowerCase()}">${r.priority}</span></td>
      <td><span class="badge badge-status-${r.status}">${r.status}</span></td>
    `;
    tbody.appendChild(tr);
  });
}

// ---------------------------------------------------------------------
// Drafts
// ---------------------------------------------------------------------
async function refreshDrafts() {
  const drafts = await api("/api/drafts");
  const list = $("#drafts-list");
  list.innerHTML = "";
  if (drafts.length === 0) {
    list.innerHTML = '<p class="muted">No drafts yet - run Write once topics are queued.</p>';
    return;
  }
  drafts.forEach((d) => {
    const card = document.createElement("div");
    card.className = "draft-card";
    card.innerHTML = `
      <div class="draft-title">${d.is_revival ? "\u267B\uFE0F " : ""}${d.title}</div>
      <div class="draft-meta">${d.meta_description || ""}
        ${d.fact_check_flags > 0 ? `<span class="flag-count"> \u2022 ${d.fact_check_flags} fact-check flag(s)</span>` : ""}
      </div>
    `;
    card.onclick = async () => {
      const full = await api(`/api/drafts/${encodeURIComponent(d.filename)}`);
      $("#modal-title").textContent = d.title;
      $("#modal-body").textContent = full.content;
      $("#draft-modal").classList.remove("hidden");
    };
    list.appendChild(card);
  });
}

$("#modal-close").addEventListener("click", () => $("#draft-modal").classList.add("hidden"));
$("#draft-modal").addEventListener("click", (e) => {
  if (e.target.id === "draft-modal") $("#draft-modal").classList.add("hidden");
});

// ---------------------------------------------------------------------
// Credentials export/import - "run BlogHero on any PC"
// ---------------------------------------------------------------------
const importInput = $("#import-credentials-input");
if (importInput) {
  importInput.addEventListener("change", async () => {
    if (!importInput.files.length) return;
    const status = $("#import-credentials-status");
    status.textContent = "Importing...";
    const formData = new FormData();
    formData.append("file", importInput.files[0]);
    try {
      const result = await api("/api/import-credentials", { method: "POST", body: formData });
      status.textContent = "Imported. Loading...";
      if (!result.needs_setup) {
        showDashboard();
      } else {
        status.textContent = "Imported, but a few required fields are still missing - check the wizard below.";
        state.schema = await api("/api/setup-schema");
        const st = await api("/api/status");
        state.values = st.config || {};
        state.stepIndex = 0;
        renderWizardStep();
      }
    } catch (err) {
      status.textContent = "Import failed: " + err.message;
    }
    importInput.value = "";
  });
}

const exportBtn = $("#btn-export-creds");
if (exportBtn) {
  exportBtn.addEventListener("click", () => {
    window.location.href = "/api/export-credentials";
  });
}

// ---------------------------------------------------------------------
// Add topic manually
// ---------------------------------------------------------------------
const addTopicBtn = $("#btn-add-topic");
if (addTopicBtn) {
  addTopicBtn.addEventListener("click", () => {
    $("#add-topic-input").value = "";
    $("#add-topic-error").textContent = "";
    $("#add-topic-modal").classList.remove("hidden");
    $("#add-topic-input").focus();
  });
}
$("#add-topic-close").addEventListener("click", () => $("#add-topic-modal").classList.add("hidden"));
$("#add-topic-modal").addEventListener("click", (e) => {
  if (e.target.id === "add-topic-modal") $("#add-topic-modal").classList.add("hidden");
});
$("#add-topic-submit").addEventListener("click", async () => {
  const topic = $("#add-topic-input").value.trim();
  const errBox = $("#add-topic-error");
  errBox.textContent = "";
  if (!topic) {
    errBox.textContent = "Enter a topic first.";
    return;
  }
  try {
    await api("/api/backlog", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        topic,
        category: $("#add-topic-category").value,
        priority: $("#add-topic-priority").value,
      }),
    });
    $("#add-topic-modal").classList.add("hidden");
    refreshBacklog();
  } catch (err) {
    errBox.textContent = err.message;
  }
});

boot();
