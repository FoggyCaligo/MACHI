const form = document.getElementById("chatForm");
const messagesEl = document.getElementById("messages");
const emptyStateEl = document.getElementById("emptyState");
const inputEl = document.getElementById("messageInput");
const fileInputEl = document.getElementById("fileInput");
const fileBadgeEl = document.getElementById("fileBadge");
const fileNameEl = document.getElementById("fileName");
const clearFileBtn = document.getElementById("clearFileBtn");
const sendBtn = document.getElementById("sendBtn");
const modelSelectEl = document.getElementById("modelSelect");
const newChatBtn = document.getElementById("newChatBtn");

const DEFAULT_REQUEST_TIMEOUT_MS = 360000;
const MODEL_STORAGE_KEY = "mk5_selected_model";
const DEBUG_STORAGE_KEY = "mk5_show_debug";
const SESSION_STORAGE_KEY = "mk5_session_id";

let uiState = {
  requestTimeoutMs: DEFAULT_REQUEST_TIMEOUT_MS,
  loading: false,
};

let modelsState = {
  defaultModel: "",
  models: [],
  ollamaAvailable: false,
  error: null,
};

function generateSessionId() {
  if (window.crypto?.randomUUID) {
    return window.crypto.randomUUID();
  }
  return `mk5-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function getOrCreateSessionId() {
  const saved = sessionStorage.getItem(SESSION_STORAGE_KEY);
  if (saved) return saved;
  const created = generateSessionId();
  sessionStorage.setItem(SESSION_STORAGE_KEY, created);
  return created;
}

function resetSessionId() {
  const created = generateSessionId();
  sessionStorage.setItem(SESSION_STORAGE_KEY, created);
  return created;
}

let currentSessionId = getOrCreateSessionId();

function shouldShowDebugPanels() {
  const params = new URLSearchParams(window.location.search);
  if (params.get("debug") === "1") return true;
  return localStorage.getItem(DEBUG_STORAGE_KEY) === "1";
}

function scrollBottom() {
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function escapeHtml(text) {
  return String(text ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function setEmptyStateVisible(visible) {
  emptyStateEl.classList.toggle("hidden", !visible);
}

function autoResizeTextarea() {
  inputEl.style.height = "auto";
  inputEl.style.height = `${Math.min(inputEl.scrollHeight, 180)}px`;
}

function clearFile() {
  fileInputEl.value = "";
  fileBadgeEl.classList.add("hidden");
  fileNameEl.textContent = "";
}

function getSelectedModel() {
  return modelSelectEl.value || "";
}

function setModelSelection(modelName) {
  const value = modelName || "";
  modelSelectEl.value = value;
  if (value) {
    localStorage.setItem(MODEL_STORAGE_KEY, value);
  } else {
    localStorage.removeItem(MODEL_STORAGE_KEY);
  }
}

function restorePreferredModel() {
  const saved = localStorage.getItem(MODEL_STORAGE_KEY) || "";
  const options = Array.from(modelSelectEl.options).map((opt) => opt.value);
  if (saved && options.includes(saved)) {
    setModelSelection(saved);
    return;
  }
  if (modelsState.defaultModel && options.includes(modelsState.defaultModel)) {
    setModelSelection(modelsState.defaultModel);
    return;
  }
  setModelSelection("");
}

function renderModelOptions() {
  const previousValue = localStorage.getItem(MODEL_STORAGE_KEY) || modelSelectEl.value || "";
  modelSelectEl.innerHTML = "";

  const defaultOption = document.createElement("option");
  defaultOption.value = "";
  defaultOption.textContent = modelsState.defaultModel
    ? `기본 모델 자동 사용 (${modelsState.defaultModel})`
    : "기본 모델 자동 사용";
  modelSelectEl.appendChild(defaultOption);

  modelsState.models.forEach((item) => {
    const option = document.createElement("option");
    option.value = item.name;
    const bits = [item.name];
    if (item.parameter_size) bits.push(item.parameter_size);
    if (item.quantization_level) bits.push(item.quantization_level);
    option.textContent = bits.join(" | ");
    modelSelectEl.appendChild(option);
  });

  modelSelectEl.disabled = modelsState.models.length === 0 && !modelsState.defaultModel;

  if (previousValue && Array.from(modelSelectEl.options).some((opt) => opt.value === previousValue)) {
    setModelSelection(previousValue);
    return;
  }
  restorePreferredModel();
}

async function loadUiConfig() {
  try {
    const res = await fetch("/ui-config");
    const data = await res.json();
    const timeoutMs = Number(data.request_timeout_ms);
    if (Number.isFinite(timeoutMs) && timeoutMs > 0) {
      uiState.requestTimeoutMs = timeoutMs;
    }
  } catch (_err) {
    uiState.requestTimeoutMs = DEFAULT_REQUEST_TIMEOUT_MS;
  }
}

async function loadModels() {
  try {
    const res = await fetch("/models");
    const data = await res.json();
    modelsState = {
      defaultModel: data.default_model || "",
      models: Array.isArray(data.models) ? data.models : [],
      ollamaAvailable: Boolean(data.ollama_available),
      error: data.error || null,
    };
    renderModelOptions();
  } catch (_err) {
    modelSelectEl.innerHTML = '<option value="">모델 연결 실패</option>';
    modelSelectEl.disabled = true;
  }
}

function addRow(role, bodyNode) {
  setEmptyStateVisible(false);
  const row = document.createElement("div");
  row.className = `msg-row ${role}`;

  const avatar = document.createElement("div");
  avatar.className = `avatar ${role}`;
  avatar.textContent = role === "user" ? "YOU" : role === "system" ? "ERR" : "M5";

  row.appendChild(avatar);
  row.appendChild(bodyNode);
  messagesEl.appendChild(row);
  scrollBottom();
  return row;
}

function appendUserBubble(text, fileName) {
  const bubble = document.createElement("div");
  bubble.className = "bubble";

  if (fileName) {
    const pill = document.createElement("div");
    pill.className = "file-pill";
    pill.textContent = `FILE ${fileName}`;
    bubble.appendChild(pill);
  }

  if (text) {
    bubble.appendChild(document.createTextNode(text));
  }

  addRow("user", bubble);
}

function appendAssistantBubble(data) {
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.appendChild(document.createTextNode(data.reply || "(응답 없음)"));

  const meta = document.createElement("div");
  meta.className = "meta";
  const aligned = data?.thinking?.conclusion_view?.aligned_node_count ?? 0;
  const edges = data?.thinking?.conclusion_view?.supporting_edge_count ?? 0;
  const searchTriggered = data?.search?.query_triggered ? "search on" : "search off";
  const modelName = data.used_model || "";

  meta.innerHTML = `
    <span>aligned ${escapeHtml(String(aligned))}</span>
    <span>edges ${escapeHtml(String(edges))}</span>
    <span>${escapeHtml(searchTriggered)}</span>
    ${modelName ? `<span>model ${escapeHtml(modelName)}</span>` : ""}
  `;
  bubble.appendChild(meta);

  addRow("assistant", bubble);
}

function addDebugPanel(title, sections) {
  if (!shouldShowDebugPanels()) return;

  const bubble = document.createElement("div");
  bubble.className = "bubble debug-panel";

  const details = document.createElement("details");
  const summary = document.createElement("summary");
  summary.textContent = title;
  details.appendChild(summary);

  sections.filter(Boolean).forEach((section) => {
    const block = document.createElement("pre");
    block.className = "debug-block";
    block.textContent = section;
    details.appendChild(block);
  });

  bubble.appendChild(details);
  addRow("assistant", bubble);
}

function appendErrorBubble(message) {
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = `[오류] ${message}`;
  addRow("system", bubble);
}

function appendLoader() {
  const bubble = document.createElement("div");
  bubble.className = "loader";
  bubble.innerHTML = "<span></span><span></span><span></span>";
  return addRow("assistant", bubble);
}

function buildDebugSections(data) {
  return [
    data.internal_explanation ? `internal_explanation\n${data.internal_explanation}` : "",
    data.ingest ? `ingest\n${JSON.stringify(data.ingest, null, 2)}` : "",
    data.activation ? `activation\n${JSON.stringify(data.activation, null, 2)}` : "",
    data.thinking ? `thinking\n${JSON.stringify(data.thinking, null, 2)}` : "",
    data.search ? `search\n${JSON.stringify(data.search, null, 2)}` : "",
    data.assistant_ingest ? `assistant_ingest\n${JSON.stringify(data.assistant_ingest, null, 2)}` : "",
    data.verbalization ? `verbalization\n${JSON.stringify(data.verbalization, null, 2)}` : "",
    data.debug ? `debug\n${JSON.stringify(data.debug, null, 2)}` : "",
  ];
}

async function sendMessage() {
  if (uiState.loading) return;

  const message = inputEl.value.trim();
  const file = fileInputEl.files[0];
  if (!message && !file) return;

  appendUserBubble(message, file?.name || "");
  inputEl.value = "";
  autoResizeTextarea();

  const loaderRow = appendLoader();
  uiState.loading = true;
  sendBtn.disabled = true;
  newChatBtn.disabled = true;

  const formData = new FormData();
  formData.append("message", message);
  formData.append("session_id", currentSessionId);
  if (getSelectedModel()) {
    formData.append("model", getSelectedModel());
  }
  if (file) {
    formData.append("file", file);
  }

  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), uiState.requestTimeoutMs);

  try {
    const res = await fetch("/chat", {
      method: "POST",
      body: formData,
      signal: controller.signal,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(data.detail || res.statusText || "요청 실패");
    }

    loaderRow.remove();
    appendAssistantBubble(data);
    if (shouldShowDebugPanels()) {
      addDebugPanel("MK5 debug", buildDebugSections(data));
    }
    clearFile();
  } catch (err) {
    loaderRow.remove();
    const messageText =
      err?.name === "AbortError"
        ? "요청 시간이 초과되었습니다."
        : (err?.message || "알 수 없는 오류가 발생했습니다.");
    appendErrorBubble(messageText);
  } finally {
    window.clearTimeout(timeoutId);
    uiState.loading = false;
    sendBtn.disabled = false;
    newChatBtn.disabled = false;
    inputEl.focus();
  }
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  sendMessage();
});

inputEl.addEventListener("input", autoResizeTextarea);
inputEl.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    sendMessage();
  }
});

fileInputEl.addEventListener("change", () => {
  const file = fileInputEl.files[0];
  if (!file) {
    clearFile();
    return;
  }
  fileBadgeEl.classList.remove("hidden");
  fileNameEl.textContent = file.name;
});

clearFileBtn.addEventListener("click", clearFile);
modelSelectEl.addEventListener("change", () => setModelSelection(getSelectedModel()));
newChatBtn.addEventListener("click", () => {
  currentSessionId = resetSessionId();
  messagesEl.querySelectorAll(".msg-row").forEach((node) => node.remove());
  setEmptyStateVisible(true);
  clearFile();
  inputEl.value = "";
  autoResizeTextarea();
});

Promise.all([loadUiConfig(), loadModels()]).finally(() => {
  autoResizeTextarea();
  inputEl.focus();
});
