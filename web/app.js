const state = {
  sessionId: null,
  session: null,
  sessions: [],
  meta: null,
  sending: false,
};

const el = Object.fromEntries([
  "sidebar", "new-session", "session-list", "session-count", "runtime-model", "tool-count",
  "max-steps", "menu-button", "session-title", "session-id", "copy-session", "trace-toggle",
  "messages", "welcome", "composer", "message-input", "send-button", "tool-chips", "inspector",
  "close-trace", "run-status", "step-count", "refresh-trace", "timeline", "memory-summary",
  "todo-list", "todo-badge", "backdrop", "toast",
  "left-resizer", "right-resizer",
].map((id) => [id, document.getElementById(id)]));

const PANEL_LIMITS = {
  sidebar: { min: 210, max: 420, storage: "agent-sidebar-width" },
  inspector: { min: 280, max: 520, storage: "agent-inspector-width" },
  centerMin: 480,
};

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  let payload;
  try { payload = await response.json(); } catch { payload = {}; }
  if (!response.ok) throw new Error(payload.error || `请求失败 (${response.status})`);
  return payload;
}

async function bootstrap() {
  restorePanelWidths();
  try {
    state.meta = await api("/api/meta");
    renderMeta();
    await loadSessions();
    if (state.sessions.length) await selectSession(state.sessions[0].id);
    else await createSession();
  } catch (error) {
    showToast(error.message);
    setRunStatus("Offline", "error");
  }
}

function renderMeta() {
  el["runtime-model"].textContent = `${state.meta.provider} · ${state.meta.model}`;
  el["tool-count"].textContent = `${state.meta.tools.length} tools`;
  el["max-steps"].textContent = `${state.meta.max_steps} steps`;
  el["step-count"].textContent = `0 / ${state.meta.max_steps}`;
  el["tool-chips"].replaceChildren(...state.meta.tools.map((tool) => {
    const chip = document.createElement("span");
    chip.className = "tool-chip";
    chip.textContent = tool.name;
    chip.title = tool.description;
    return chip;
  }));
}

async function loadSessions() {
  const payload = await api("/api/sessions");
  state.sessions = payload.sessions;
  renderSessions();
}

function renderSessions() {
  el["session-count"].textContent = state.sessions.length;
  el["session-list"].replaceChildren(...state.sessions.map((session) => {
    const button = document.createElement("button");
    button.className = `session-item${session.id === state.sessionId ? " active" : ""}`;
    button.type = "button";
    const title = document.createElement("strong");
    title.textContent = session.title;
    const meta = document.createElement("small");
    meta.textContent = `${formatRelative(session.updated_at)} · ${session.message_count} 条消息`;
    button.append(title, meta);
    button.addEventListener("click", () => selectSession(session.id));
    return button;
  }));
}

async function createSession() {
  if (state.sending) return;
  try {
    const session = await api("/api/sessions", { method: "POST", body: "{}" });
    await loadSessions();
    await selectSession(session.id);
    showToast("已创建新 Session");
  } catch (error) { showToast(error.message); }
}

async function selectSession(sessionId) {
  if (state.sending) return showToast("请等待当前请求完成");
  try {
    const [session, tracePayload] = await Promise.all([
      api(`/api/sessions/${sessionId}`),
      api(`/api/sessions/${sessionId}/traces`),
    ]);
    state.sessionId = sessionId;
    state.session = session;
    renderSession();
    renderTraces(tracePayload.traces);
    renderSessions();
    closeOverlays();
  } catch (error) { showToast(error.message); }
}

function renderSession() {
  const session = state.session;
  el["session-title"].textContent = session.title;
  el["session-id"].textContent = session.id;
  el["session-id"].title = session.id;
  const visible = session.messages.filter((message) => message.role !== "tool");
  if (!visible.length) {
    el.messages.innerHTML = welcomeMarkup();
    bindPromptCards();
  } else {
    el.messages.replaceChildren(...visible.map(messageElement));
    scrollMessages();
  }
  renderMemory(session);
}

function welcomeMarkup() {
  return `<div class="welcome" id="welcome">
    <span class="welcome-kicker">MINIMAL AGENT · REAL LOOP</span>
    <h2>今天想让 Agent<br><em>完成什么？</em></h2>
    <p>它会自主判断直接回答或调用工具。每一步决策都可以在 Trace 中查看。</p>
    <div class="prompt-grid">
      <button class="prompt-card" data-prompt="帮我计算 (125 + 75) * 3"><span class="prompt-icon">∑</span><strong>安全计算</strong><small>计算 (125 + 75) × 3</small></button>
      <button class="prompt-card" data-prompt="查询北京天气，并添加一个带伞的待办"><span class="prompt-icon">☂</span><strong>连续工具</strong><small>查天气并记录待办</small></button>
      <button class="prompt-card" data-prompt="搜索 Context 压缩相关资料，然后总结要点"><span class="prompt-icon">⌕</span><strong>知识搜索</strong><small>搜索并整理资料</small></button>
    </div></div>`;
}

function bindPromptCards() {
  document.querySelectorAll(".prompt-card").forEach((button) => {
    button.addEventListener("click", () => {
      el["message-input"].value = button.dataset.prompt;
      resizeTextarea();
      el["message-input"].focus();
    });
  });
}

function messageElement(message) {
  const article = document.createElement("article");
  const isUser = message.role === "user";
  article.className = `message ${isUser ? "user" : "agent"}`;
  const avatar = document.createElement("div");
  avatar.className = "avatar";
  avatar.textContent = isUser ? "YOU" : "AI";
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  const meta = document.createElement("div");
  meta.className = "bubble-meta";
  meta.textContent = `${isUser ? "YOU" : "AGENT"} · ${formatTime(message.created_at)}`;
  const content = document.createElement("div");
  content.className = "bubble-content";
  content.textContent = message.content;
  bubble.append(meta, content);
  article.append(avatar, bubble);
  return article;
}

function typingElement() {
  const article = document.createElement("article");
  article.className = "message agent";
  article.id = "typing-message";
  article.innerHTML = `<div class="avatar">AI</div><div class="bubble"><div class="bubble-meta">AGENT · THINKING</div><div class="bubble-content typing"><i></i><i></i><i></i></div></div>`;
  return article;
}

async function sendMessage(value) {
  const message = value.trim();
  if (!message || state.sending || !state.sessionId) return;
  state.sending = true;
  el["send-button"].disabled = true;
  el["message-input"].value = "";
  resizeTextarea();
  document.getElementById("welcome")?.remove();
  const optimistic = messageElement({ role: "user", content: message, created_at: new Date().toISOString() });
  el.messages.append(optimistic, typingElement());
  scrollMessages();
  setRunStatus("Running", "running");
  try {
    const payload = await api(`/api/sessions/${state.sessionId}/messages`, {
      method: "POST",
      body: JSON.stringify({ message }),
    });
    state.session = payload.session;
    renderSession();
    renderTraces(payload.traces);
    el["step-count"].textContent = `${payload.result.steps} / ${state.meta.max_steps}`;
    setRunStatus(payload.result.error ? "Completed · warning" : "Completed", payload.result.error ? "error" : "done");
    await loadSessions();
  } catch (error) {
    document.getElementById("typing-message")?.remove();
    showToast(error.message);
    setRunStatus("Failed", "error");
  } finally {
    state.sending = false;
    el["send-button"].disabled = false;
    el["message-input"].focus();
  }
}

function renderTraces(traces) {
  if (!traces?.length) {
    el.timeline.innerHTML = `<div class="empty-trace"><span>⌁</span><p>发送消息后，这里会显示<br>模型决策和工具执行过程。</p></div>`;
    return;
  }
  const groups = groupTraces(traces).reverse();
  el.timeline.replaceChildren(...groups.map((group, index) => traceGroupElement(
    group,
    groups.length - index,
    index === 0,
  )));
}

function groupTraces(traces) {
  const groups = [];
  const byRunId = new Map();
  let legacyGroup = null;
  traces.forEach((trace) => {
    if (trace.run_id) {
      let group = byRunId.get(trace.run_id);
      if (!group) {
        group = { runId: trace.run_id, events: [] };
        byRunId.set(trace.run_id, group);
        groups.push(group);
      }
      group.events.push(trace);
      return;
    }
    if (trace.event === "run_started" || !legacyGroup) {
      legacyGroup = { runId: `legacy-${groups.length}`, events: [] };
      groups.push(legacyGroup);
    }
    legacyGroup.events.push(trace);
  });
  return groups;
}

function traceGroupElement(group, number, newest) {
  const wrapper = document.createElement("section");
  wrapper.className = `trace-run${newest ? " current" : ""}`;
  const started = group.events.find((trace) => trace.event === "run_started");
  const header = document.createElement("header");
  header.className = "trace-run-head";
  const label = document.createElement("span");
  label.textContent = `消息 ${number}`;
  const title = document.createElement("strong");
  title.textContent = started?.input_preview || "历史消息";
  title.title = started?.input_preview || "历史消息";
  const time = document.createElement("time");
  time.textContent = formatTime(started?.at || group.events[0]?.at);
  header.append(label, title, time);
  const events = document.createElement("div");
  events.className = "trace-run-events";
  events.replaceChildren(...group.events.slice().reverse().map(traceEventElement));
  wrapper.append(header, events);
  return wrapper;
}

function traceEventElement(trace) {
    const item = document.createElement("div");
    const kind = trace.event.includes("tool") ? "tool" : trace.event.includes("finished") ? "finish" : "";
    item.className = `trace-event ${kind}`;
    const head = document.createElement("div");
    head.className = "trace-head";
    const title = document.createElement("strong");
    title.textContent = traceLabel(trace);
    const time = document.createElement("time");
    time.textContent = formatTime(trace.at);
    head.append(title, time);
    const details = document.createElement("p");
    details.textContent = traceDetails(trace);
    item.append(head, details);
    return item;
}

function traceLabel(trace) {
  const labels = {
    run_started: "Run started", decision: "Model decision", tool_finished: "Tool completed",
    run_finished: "Final answer", parse_repair: "Format repair", context_compacted: "Context compacted",
    run_failed: "Run failed", max_steps_reached: "Max steps reached",
  };
  return labels[trace.event] || trace.event.replaceAll("_", " ");
}

function traceDetails(trace) {
  if (trace.event === "decision") return trace.tool ? `${trace.type} → ${trace.tool} · ${trace.reasoning_summary || "—"}` : `${trace.type} · ${trace.reasoning_summary || "—"}`;
  if (trace.event === "tool_finished") return `${trace.tool} · ${trace.ok ? "success" : trace.error || "failed"}`;
  if (trace.event === "run_started") return `收到 ${trace.input_chars || 0} 字符输入`;
  if (trace.event === "run_finished") return `在第 ${trace.step} 步生成最终回答`;
  if (trace.error) return trace.error;
  return trace.step ? `Step ${trace.step}` : "Runtime event";
}

function renderMemory(session) {
  el["memory-summary"].textContent = session.summary || "尚未生成历史摘要";
  const active = session.todos.filter((todo) => !todo.done).length;
  el["todo-badge"].textContent = `${active} TODO`;
  if (!session.todos.length) {
    el["todo-list"].innerHTML = "";
    return;
  }
  el["todo-list"].replaceChildren(...session.todos.map((todo) => {
    const item = document.createElement("div");
    item.className = `todo-item${todo.done ? " done" : ""}`;
    const check = document.createElement("span");
    check.className = "todo-check";
    check.textContent = todo.done ? "✓" : "";
    const text = document.createElement("span");
    text.textContent = `#${todo.id} ${todo.text}`;
    item.append(check, text);
    return item;
  }));
}

function setRunStatus(text, type) {
  el["run-status"].textContent = "";
  const dot = document.createElement("i");
  dot.className = "status-dot";
  if (type === "running") dot.style.background = "#ef6d50";
  if (type === "error") dot.style.background = "#d85439";
  el["run-status"].append(dot, document.createTextNode(text));
}

async function refreshTrace() {
  if (!state.sessionId) return;
  try {
    const payload = await api(`/api/sessions/${state.sessionId}/traces`);
    renderTraces(payload.traces);
  } catch (error) { showToast(error.message); }
}

function formatTime(value) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }).format(new Date(value));
}

function formatRelative(value) {
  const delta = Date.now() - new Date(value).getTime();
  if (delta < 60_000) return "刚刚";
  if (delta < 3_600_000) return `${Math.floor(delta / 60_000)} 分钟前`;
  if (delta < 86_400_000) return `${Math.floor(delta / 3_600_000)} 小时前`;
  return `${Math.floor(delta / 86_400_000)} 天前`;
}

function resizeTextarea() {
  const textarea = el["message-input"];
  textarea.style.height = "auto";
  textarea.style.height = `${Math.min(textarea.scrollHeight, 140)}px`;
}

function scrollMessages() { requestAnimationFrame(() => { el.messages.scrollTop = el.messages.scrollHeight; }); }
function showToast(message) {
  el.toast.textContent = message;
  el.toast.classList.add("show");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => el.toast.classList.remove("show"), 2200);
}
function closeOverlays() {
  el.sidebar.classList.remove("open");
  el.inspector.classList.remove("open");
  el.backdrop.classList.remove("show");
}

function clampPanelWidth(panel, requested) {
  const limits = PANEL_LIMITS[panel];
  const other = panel === "sidebar"
    ? currentPanelWidth("inspector")
    : currentPanelWidth("sidebar");
  const available = window.innerWidth - other - PANEL_LIMITS.centerMin;
  return Math.max(limits.min, Math.min(limits.max, available, requested));
}

function currentPanelWidth(panel) {
  const target = panel === "sidebar" ? el.sidebar : el.inspector;
  return Math.round(target.getBoundingClientRect().width);
}

function setPanelWidth(panel, width, persist = true) {
  if (window.innerWidth <= 1080) return;
  const value = clampPanelWidth(panel, Math.round(width));
  const property = panel === "sidebar" ? "--sidebar-width" : "--inspector-width";
  document.documentElement.style.setProperty(property, `${value}px`);
  const handle = panel === "sidebar" ? el["left-resizer"] : el["right-resizer"];
  handle.setAttribute("aria-valuemin", PANEL_LIMITS[panel].min);
  handle.setAttribute("aria-valuemax", PANEL_LIMITS[panel].max);
  handle.setAttribute("aria-valuenow", value);
  if (persist) localStorage.setItem(PANEL_LIMITS[panel].storage, String(value));
}

function restorePanelWidths() {
  if (window.innerWidth <= 1080) return;
  const sidebar = Number(localStorage.getItem(PANEL_LIMITS.sidebar.storage)) || 258;
  const inspector = Number(localStorage.getItem(PANEL_LIMITS.inspector.storage)) || 340;
  setPanelWidth("sidebar", sidebar, false);
  setPanelWidth("inspector", inspector, false);
}

function bindPanelResizer(handle, panel) {
  handle.addEventListener("pointerdown", (event) => {
    if (window.innerWidth <= 1080) return;
    event.preventDefault();
    handle.setPointerCapture(event.pointerId);
    handle.classList.add("dragging");
    document.body.classList.add("resizing-panels");
  });
  handle.addEventListener("pointermove", (event) => {
    if (!handle.hasPointerCapture(event.pointerId)) return;
    const requested = panel === "sidebar" ? event.clientX : window.innerWidth - event.clientX;
    setPanelWidth(panel, requested);
  });
  const finish = (event) => {
    if (handle.hasPointerCapture(event.pointerId)) handle.releasePointerCapture(event.pointerId);
    handle.classList.remove("dragging");
    document.body.classList.remove("resizing-panels");
  };
  handle.addEventListener("pointerup", finish);
  handle.addEventListener("pointercancel", finish);
  handle.addEventListener("keydown", (event) => {
    if (!['ArrowLeft', 'ArrowRight'].includes(event.key) || window.innerWidth <= 1080) return;
    event.preventDefault();
    const direction = event.key === "ArrowRight" ? 1 : -1;
    const signed = panel === "sidebar" ? direction : -direction;
    setPanelWidth(panel, currentPanelWidth(panel) + signed * (event.shiftKey ? 40 : 12));
  });
}
function openOverlay(target) {
  closeOverlays();
  target.classList.add("open");
  el.backdrop.classList.add("show");
}

el["new-session"].addEventListener("click", createSession);
el.composer.addEventListener("submit", (event) => { event.preventDefault(); sendMessage(el["message-input"].value); });
el["message-input"].addEventListener("input", resizeTextarea);
el["message-input"].addEventListener("keydown", (event) => {
  if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
    event.preventDefault();
    sendMessage(event.currentTarget.value);
  }
});
el["refresh-trace"].addEventListener("click", refreshTrace);
el["copy-session"].addEventListener("click", async () => {
  if (!state.sessionId) return;
  try { await navigator.clipboard.writeText(state.sessionId); showToast("Session ID 已复制"); }
  catch { showToast("复制失败，请手动选择 Session ID"); }
});
el["trace-toggle"].addEventListener("click", () => openOverlay(el.inspector));
el["menu-button"].addEventListener("click", () => openOverlay(el.sidebar));
el["close-trace"].addEventListener("click", closeOverlays);
el.backdrop.addEventListener("click", closeOverlays);
document.addEventListener("keydown", (event) => { if (event.key === "Escape") closeOverlays(); });
bindPanelResizer(el["left-resizer"], "sidebar");
bindPanelResizer(el["right-resizer"], "inspector");
window.addEventListener("resize", () => {
  if (window.innerWidth > 1080) restorePanelWidths();
});
bindPromptCards();
bootstrap();
