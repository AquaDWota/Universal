(function () {
  const titles = { chat: "Chat", connectors: "Connectors", overview: "Overview" };

  const sidebar = document.getElementById("sidebar");
  const backdrop = document.getElementById("backdrop");
  const menuBtn = document.getElementById("menu-btn");
  const collapseBtn = document.getElementById("sidebar-collapse");
  const pageTitle = document.getElementById("page-title");
  const pillInference = document.getElementById("pill-inference");

  const chatThread = document.getElementById("chat-thread");
  const chatInput = document.getElementById("chat-input");
  const chatSend = document.getElementById("chat-send");
  const btnClear = document.getElementById("btn-clear-chat");

  const connectorsGrid = document.getElementById("connectors-grid");
  const connectorsEmpty = document.getElementById("connectors-empty");
  const statusTiles = document.getElementById("status-tiles");

  function showView(name) {
    document.querySelectorAll(".nav-item").forEach((n) => {
      n.classList.toggle("active", n.dataset.view === name);
    });
    ["chat", "connectors", "overview"].forEach((v) => {
      const el = document.getElementById("view-" + v);
      if (!el) return;
      el.hidden = v !== name;
      el.classList.toggle("active", v === name);
    });
    pageTitle.textContent = titles[name] || name;
    closeMobileSidebar();
    if (name === "overview") refreshStatus();
    if (name === "connectors") refreshConnectors();
  }

  function openMobileSidebar() {
    sidebar.classList.add("open");
    backdrop.hidden = false;
  }

  function closeMobileSidebar() {
    sidebar.classList.remove("open");
    backdrop.hidden = true;
  }

  document.querySelectorAll(".nav-item").forEach((btn) => {
    btn.addEventListener("click", () => showView(btn.dataset.view));
  });

  menuBtn.addEventListener("click", () => {
    if (sidebar.classList.contains("open")) closeMobileSidebar();
    else openMobileSidebar();
  });

  backdrop.addEventListener("click", closeMobileSidebar);

  collapseBtn.addEventListener("click", () => {
    sidebar.classList.toggle("collapsed");
    collapseBtn.textContent = sidebar.classList.contains("collapsed") ? "⟩" : "⟨";
  });

  function appendMessage(role, text, pending) {
    const wrap = document.createElement("article");
    wrap.className = "msg " + role + (pending ? " pending" : "");
    const meta = document.createElement("div");
    meta.className = "msg-meta";
    meta.textContent = role === "user" ? "You" : "Assistant";
    const body = document.createElement("div");
    body.textContent = text;
    wrap.appendChild(meta);
    wrap.appendChild(body);
    chatThread.appendChild(wrap);
    chatThread.scrollTop = chatThread.scrollHeight;
    return wrap;
  }

  async function sendChat() {
    const msg = chatInput.value.trim();
    if (!msg) return;
    chatInput.value = "";
    appendMessage("user", msg);
    const bubble = appendMessage("assistant", "Thinking…", true);
    chatSend.disabled = true;
    try {
      const r = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: msg }),
      });
      const j = await r.json();
      bubble.classList.remove("pending");
      const body = bubble.querySelector("div:last-child");
      if (!r.ok) {
        body.textContent =
          "Error: " + (typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail || j));
        return;
      }
      body.textContent = j.reply || "(empty reply)";
    } catch (e) {
      bubble.classList.remove("pending");
      bubble.querySelector("div:last-child").textContent = "Error: " + e;
    } finally {
      chatSend.disabled = false;
      chatInput.focus();
    }
  }

  chatSend.addEventListener("click", sendChat);
  chatInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendChat();
    }
  });

  btnClear.addEventListener("click", () => {
    chatThread.innerHTML = "";
  });

  async function refreshStatus() {
    statusTiles.innerHTML = "";
    try {
      const r = await fetch("/api/status");
      const s = await r.json();
      const rows = [
        ["Inference mode", s.inference],
        ["Local model", s.local_model],
        ["Cloud model", s.cloud_model],
        ["Privacy local_mode", String(s.privacy_local_mode)],
        ["Vector index", s.vector_store_active ? "Active" : "Off"],
        ["Connectors", String(s.connector_count)],
      ];
      rows.forEach(([label, val]) => {
        const t = document.createElement("div");
        t.className = "tile";
        t.innerHTML =
          '<div class="label"></div><div class="value"></div>';
        t.querySelector(".label").textContent = label;
        t.querySelector(".value").textContent = val == null ? "—" : String(val);
        statusTiles.appendChild(t);
      });
    } catch (e) {
      statusTiles.innerHTML =
        '<p class="muted">Could not load status: ' +
        String(e) +
        "</p>";
    }
  }

  async function refreshConnectors() {
    connectorsGrid.innerHTML = "";
    try {
      const r = await fetch("/api/connectors");
      const data = await r.json();
      const list = data.connectors || [];
      connectorsEmpty.classList.toggle("hidden", list.length > 0);
      list.forEach((c) => {
        const card = document.createElement("div");
        card.className = "card";
        const enabledBadge = c.enabled
          ? ""
          : '<span class="badge off">disabled</span>';
        let caps = "<ul>";
        (c.capabilities || []).forEach((cap) => {
          const cf = cap.requires_confirmation
            ? ' <span class="badge confirm">confirm</span>'
            : "";
          caps +=
            "<li><strong>" +
            escapeHtml(cap.action_id) +
            "</strong> — " +
            escapeHtml(cap.description || "") +
            cf +
            "</li>";
        });
        caps += "</ul>";
        card.innerHTML =
          '<div class="cat">' +
          escapeHtml(c.category) +
          enabledBadge +
          "</div>" +
          "<h3>" +
          escapeHtml(c.name) +
          "</h3>" +
          '<p class="desc">' +
          escapeHtml(c.description || "") +
          "</p>" +
          caps;
        connectorsGrid.appendChild(card);
      });
    } catch (e) {
      connectorsGrid.innerHTML =
        '<p class="muted">Could not load connectors: ' +
        String(e) +
        "</p>";
    }
  }

  function escapeHtml(s) {
    const d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
  }

  async function boot() {
    try {
      const r = await fetch("/api/status");
      const s = await r.json();
      pillInference.textContent = s.inference || "—";
      pillInference.classList.toggle("cloud", s.inference === "cloud");
      pillInference.title =
        "Inference: " +
        s.inference +
        " · local=" +
        s.local_model +
        " · cloud=" +
        s.cloud_model;
    } catch (_) {
      pillInference.textContent = "?";
    }
    chatInput.focus();
  }

  boot();
})();
