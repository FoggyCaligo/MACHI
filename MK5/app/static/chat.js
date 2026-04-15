const form = document.getElementById("chatForm");
const messagesEl = document.getElementById("messages");
const inputEl = document.getElementById("messageInput");
const fileInputEl = document.getElementById("fileInput");
const fileNameEl = document.getElementById("fileName");
const clearFileBtn = document.getElementById("clearFileBtn");
const sendBtn = document.getElementById("sendBtn");
const projectSelectEl = document.getElementById("projectSelect");
const refreshProjectsBtn = document.getElementById("refreshProjectsBtn");
const clearProjectBtn = document.getElementById("clearProjectBtn");
const projectNameInputEl = document.getElementById("projectNameInput");
const projectBadgeEl = document.getElementById("projectBadge");
const modelSelectEl = document.getElementById("modelSelect");
const refreshModelsBtn = document.getElementById("refreshModelsBtn");
const clearModelBtn = document.getElementById("clearModelBtn");
const modelBadgeEl = document.getElementById("modelBadge");

const DEFAULT_REQUEST_TIMEOUT_MS = 300000;
const PROJECT_STORAGE_KEY = "mk5_selected_project_id";
const MODEL_STORAGE_KEY = "mk5_selected_model";
const DEBUG_STORAGE_KEY = "mk5_show_debug";

let uiState = {
  requestTimeoutMs: DEFAULT_REQUEST_TIMEOUT_MS,
};

let projectsState = {
  projects: [],
  error: null,
};

let modelsState = {
  defaultModel: "",
  models: [],
  ollamaAvailable: false,
  error: null,
};

function addMessage(role, text) {
  const div = document.createElement("div");
  div.className = `message ${role}`;
  div.textContent = text;
  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return div;
}

function shouldShowDebugPanels() {
  const params = new URLSearchParams(window.location.search);
  if (params.get("debug") === "1") return true;
  return localStorage.getItem(DEBUG_STORAGE_KEY) === "1";
}

function addDebugPanel(title, sections) {
  if (!shouldShowDebugPanels()) return;

  const wrapper = document.createElement("div");
  wrapper.className = "message system debug-panel";

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

  wrapper.appendChild(details);
  messagesEl.appendChild(wrapper);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function getRequestTimeoutMs() {
  const value = Number(uiState.requestTimeoutMs);
  return Number.isFinite(value) && value > 0 ? value : DEFAULT_REQUEST_TIMEOUT_MS;
}

function getProjectById(projectId) {
  return projectsState.projects.find((item) => item.id === projectId) || null;
}

function getProjectDisplayName(projectId) {
  if (!projectId) return "";
  const project = getProjectById(projectId);
  return project?.name || "";
}

function setSelectedProject(projectId) {
  const value = projectId || "";
  const hasOption = Array.from(projectSelectEl.options).some((opt) => opt.value === value);
  projectSelectEl.value = hasOption ? value : "";

  const badgeText = value ? getProjectDisplayName(value) || "알 수 없는 프로젝트" : "없음";
  projectBadgeEl.textContent = badgeText;

  if (value) {
    localStorage.setItem(PROJECT_STORAGE_KEY, value);
  } else {
    localStorage.removeItem(PROJECT_STORAGE_KEY);
  }
}

function restorePreferredProject() {
  const saved = localStorage.getItem(PROJECT_STORAGE_KEY) || "";
  if (saved && Array.from(projectSelectEl.options).some((opt) => opt.value === saved)) {
    setSelectedProject(saved);
    return;
  }
  setSelectedProject("");
}

function renderProjectOptions(preferredProjectId = "") {
  const previousValue =
    preferredProjectId ||
    localStorage.getItem(PROJECT_STORAGE_KEY) ||
    projectSelectEl.value ||
    "";

  projectSelectEl.innerHTML = "";

  const defaultOption = document.createElement("option");
  defaultOption.value = "";
  defaultOption.textContent = "프로젝트 선택 안 함";
  projectSelectEl.appendChild(defaultOption);

  projectsState.projects.forEach((item) => {
    const option = document.createElement("option");
    option.value = item.id;

    const suffix = item.status && item.status !== "indexed" ? ` [${item.status}]` : "";
    option.textContent = `${item.name}${suffix}`;
    projectSelectEl.appendChild(option);
  });

  projectSelectEl.disabled = projectsState.projects.length === 0;

  if (previousValue && Array.from(projectSelectEl.options).some((opt) => opt.value === previousValue)) {
    setSelectedProject(previousValue);
    return;
  }

  restorePreferredProject();
}

async function loadProjects({ silent = false, preferredProjectId = "" } = {}) {
  refreshProjectsBtn.disabled = true;

  try {
    const res = await fetch("/projects");
    const data = await res.json();

    projectsState = {
      projects: Array.isArray(data.projects) ? data.projects : [],
      error: null,
    };

    renderProjectOptions(preferredProjectId);

    if (!silent && shouldShowDebugPanels()) {
      addMessage("system", `프로젝트 목록 갱신 완료\n- project_count: ${projectsState.projects.length}`);
    }
  } catch (err) {
    projectsState = {
      projects: [],
      error: err.message,
    };
    renderProjectOptions("");
    addMessage("system", `프로젝트 목록 로드 실패: ${err.message}`);
  } finally {
    refreshProjectsBtn.disabled = false;
  }
}

function setModelSelection(modelName) {
  const value = modelName || "";
  modelSelectEl.value = value;
  modelBadgeEl.textContent = value || modelsState.defaultModel || "기본 모델";

  if (value) {
    localStorage.setItem(MODEL_STORAGE_KEY, value);
  } else {
    localStorage.removeItem(MODEL_STORAGE_KEY);
  }
}

function restorePreferredModel() {
  const saved = localStorage.getItem(MODEL_STORAGE_KEY) || "";
  if (saved && Array.from(modelSelectEl.options).some((opt) => opt.value === saved)) {
    setModelSelection(saved);
    return;
  }

  if (
    modelsState.defaultModel &&
    Array.from(modelSelectEl.options).some((opt) => opt.value === modelsState.defaultModel)
  ) {
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

async function loadModels({ silent = false } = {}) {
  refreshModelsBtn.disabled = true;

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

    if (!silent && shouldShowDebugPanels()) {
      const lines = [
        "모델 목록 갱신 완료",
        `- ollama_available: ${modelsState.ollamaAvailable ? "예" : "아니오"}`,
        `- default_model: ${modelsState.defaultModel || "없음"}`,
        `- local_models: ${modelsState.models.length}`,
      ];
      addMessage("system", lines.join("\n"));
    }

    if (modelsState.error && shouldShowDebugPanels()) {
      addMessage("system", `모델 목록 경고: ${modelsState.error}`);
    }
  } catch (err) {
    modelsState = {
      defaultModel: "",
      models: [],
      ollamaAvailable: false,
      error: err.message,
    };
    renderModelOptions();
    addMessage("system", `모델 목록 로드 실패: ${err.message}`);
  } finally {
    refreshModelsBtn.disabled = false;
  }
}

async function loadUiConfig({ silent = false } = {}) {
  try {
    const res = await fetch("/ui-config");
    const data = await res.json();
    uiState.requestTimeoutMs = Number(data.request_timeout_ms) || DEFAULT_REQUEST_TIMEOUT_MS;
  } catch (err) {
    uiState.requestTimeoutMs = DEFAULT_REQUEST_TIMEOUT_MS;
    if (!silent) {
      addMessage("system", `UI 설정 로드 실패: ${err.message}`);
    }
  }
}

function getSelectedModel() {
  return (modelSelectEl.value || "").trim();
}

function getSelectedProjectId() {
  return (projectSelectEl.value || "").trim();
}

function isZipFile(file) {
  return Boolean(file && file.name && file.name.toLowerCase().endsWith(".zip"));
}

fileInputEl.addEventListener("change", () => {
  const file = fileInputEl.files && fileInputEl.files[0];
  fileNameEl.textContent = file ? file.name : "선택된 파일 없음";
});

clearFileBtn.addEventListener("click", () => {
  fileInputEl.value = "";
  fileNameEl.textContent = "선택된 파일 없음";
});

clearProjectBtn.addEventListener("click", () => {
  setSelectedProject("");
});

refreshProjectsBtn.addEventListener("click", () => {
  loadProjects();
});

refreshModelsBtn.addEventListener("click", () => {
  loadModels();
});

clearModelBtn.addEventListener("click", () => {
  setModelSelection("");
});

projectSelectEl.addEventListener("change", () => {
  const projectId = getSelectedProjectId();
  setSelectedProject(projectId);
});

modelSelectEl.addEventListener("change", () => {
  const selected = getSelectedModel();
  setModelSelection(selected);
});

inputEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    form.requestSubmit();
  }
});

function normalizeReply(data) {
  if (!data) return "(빈 응답)";
  if (typeof data.reply === "string") return data.reply;
  if (data.reply && typeof data.reply.reply === "string") return data.reply.reply;
  return JSON.stringify(data, null, 2);
}

function summarizeModel(data) {
  if (!data || !data.used_model) return null;
  return ["응답 모델", `- used_model: ${data.used_model}`].join("\n");
}

function summarizeInternalExplanation(data) {
  if (!data || !data.internal_explanation) return null;
  return ["내부 설명용 요약", data.internal_explanation].join("\n\n");
}

function summarizeDerivedAction(actionLayer) {
  if (!actionLayer) return null;
  return [
    "derived action",
    `- response_mode: ${actionLayer.response_mode || "-"}`,
    `- answer_goal: ${actionLayer.answer_goal || "-"}`,
    `- tone_hint: ${actionLayer.tone_hint || "-"}`,
    `- suggested_actions: ${(actionLayer.suggested_actions || []).join(" | ") || "없음"}`,
    `- do_not_claim: ${(actionLayer.do_not_claim || []).join(" | ") || "없음"}`,
  ].join("\n");
}

function summarizeIngest(ingest) {
  if (!ingest) return null;
  return [
    "graph ingest 결과",
    `- message_id: ${ingest.message_id ?? "-"}`,
    `- root_event_id: ${ingest.root_event_id ?? "-"}`,
    `- block_count: ${ingest.block_count ?? 0}`,
    `- created_node_ids: ${(ingest.created_node_ids || []).join(", ") || "없음"}`,
    `- reused_node_ids: ${(ingest.reused_node_ids || []).join(", ") || "없음"}`,
    `- created_edge_ids: ${(ingest.created_edge_ids || []).join(", ") || "없음"}`,
    `- supported_edge_ids: ${(ingest.supported_edge_ids || []).join(", ") || "없음"}`,
    `- created_pointer_ids: ${(ingest.created_pointer_ids || []).join(", ") || "없음"}`,
  ].join("\n");
}

function summarizeActivation(activation) {
  if (!activation) return null;
  const seedBlocks = Array.isArray(activation.seed_blocks) ? activation.seed_blocks : [];
  const seedLines = seedBlocks.slice(0, 5).map(
    (item, index) => `${index + 1}. [${item.block_kind}] ${item.text}`,
  );

  return [
    "activation debug",
    `- seed_block_count: ${seedBlocks.length}`,
    `- seed_node_ids: ${(activation.seed_node_ids || []).join(", ") || "없음"}`,
    `- local_node_ids: ${(activation.local_node_ids || []).join(", ") || "없음"}`,
    `- local_edge_ids: ${(activation.local_edge_ids || []).join(", ") || "없음"}`,
    `- pointer_ids: ${(activation.pointer_ids || []).join(", ") || "없음"}`,
    ...seedLines,
  ].join("\n");
}

function summarizeThinkingDebug(thinking) {
  if (!thinking) return null;
  const lines = [
    "thinking debug",
    `- signal_count: ${thinking.signal_count ?? 0}`,
    `- trust_update_count: ${thinking.trust_update_count ?? 0}`,
    `- revision_action_count: ${thinking.revision_action_count ?? 0}`,
  ];

  const conclusion = thinking.core_conclusion;
  if (conclusion) {
    lines.push(`- activated_concepts: ${(conclusion.activated_concepts || []).join(", ") || "없음"}`);
    lines.push(`- key_relations: ${(conclusion.key_relations || []).join(", ") || "없음"}`);
    lines.push(`- inferred_intent: ${conclusion.inferred_intent || "-"}`);
  }

  const signals = Array.isArray(thinking.signals) ? thinking.signals : [];
  signals.slice(0, 5).forEach((item, index) => {
    lines.push(
      `${index + 1}. edge#${item.edge_id} [${item.edge_type}] ${item.reason} | severity=${item.severity}`,
    );
  });

  return lines.join("\n");
}

function summarizeCoreConclusion(conclusion) {
  if (!conclusion) return null;
  return [
    "core conclusion",
    `- user_input_summary: ${conclusion.user_input_summary || "-"}`,
    `- inferred_intent: ${conclusion.inferred_intent || "-"}`,
    `- explanation_summary: ${conclusion.explanation_summary || "-"}`,
  ].join("\n");
}

function summarizeSearch(search) {
  if (!search) return null;
  const decision = search.need_decision || {};
  const slotPlan = search.slot_plan || null;
  const plan = search.plan || null;
  const results = Array.isArray(search.results) ? search.results : [];
  const ingest = Array.isArray(search.ingest) ? search.ingest : [];

  const lines = [
    "search debug",
    `- planning_attempted: ${search.planning_attempted ? "true" : "false"}`,
    `- query_triggered: ${search.query_triggered ? "true" : "false"}`,
    `- need_search: ${decision.need_search ? "true" : "false"}`,
    `- decision_reason: ${decision.reason || "-"}`,
    `- gap_summary: ${decision.gap_summary || "-"}`,
    `- target_terms: ${(decision.target_terms || []).join(" | ") || "없음"}`,
  ];

  if (plan) {
    lines.push(`- planned_queries: ${(plan.queries || []).join(" | ") || "없음"}`);
    lines.push(`- plan_reason: ${plan.reason || "-"}`);
    lines.push(`- focus_terms: ${(plan.focus_terms || []).join(" | ") || "없음"}`);
    const groundingQueries = (plan.grounding_queries || []).join(" | ");
    const comparisonQueries = (plan.comparison_queries || []).join(" | ");
    const requestedSlots = (decision.requested_slots || []).map((slot) => slot.label || `${slot.entity || "-"}:${slot.aspect || ""}`).join(" | ");
    const coveredSlots = (decision.covered_slots || []).map((slot) => slot.label || `${slot.entity || "-"}:${slot.aspect || ""}`).join(" | ");
    const missingSlots = (decision.missing_slots || []).map((slot) => slot.label || `${slot.entity || "-"}:${slot.aspect || ""}`).join(" | ");
    const issuedSlotQueries = (plan.issued_slot_queries || [])
      .map((item) => {
        const entity = item?.entity || "-";
        const aspects = Array.isArray(item?.aspects) ? item.aspects.filter(Boolean).join(", ") : "";
        const slotLabel = aspects ? `${entity}:${aspects}` : entity;
        return `${slotLabel} -> ${item?.query || "-"}`;
      })
      .join(" | ");
    lines.push(`- grounding_queries: ${groundingQueries || "없음"}`);
    lines.push(`- comparison_queries: ${comparisonQueries || "없음"}`);
    lines.push(`- requested_slots: ${requestedSlots || "없음"}`);
    lines.push(`- covered_slots: ${coveredSlots || "없음"}`);
    lines.push(`- missing_slots: ${missingSlots || "없음"}`);
    lines.push(`- issued_slot_queries: ${issuedSlotQueries || "없음"}`);
  } else {
    lines.push(`- planned_queries: 없음`);
  }

  if (slotPlan) {
    lines.push(`- slot_entities: ${(slotPlan.entities || []).join(" | ") || "-"}`);
    lines.push(`- slot_aspects: ${(slotPlan.aspects || []).join(" | ") || "-"}`);
    lines.push(`- slot_reason: ${slotPlan.reason || "-"}`);
  }

  lines.push(`- result_count: ${results.length}`);
  lines.push(`- error: ${search.error || "없음"}`);

  results.slice(0, 5).forEach((item, index) => {
    lines.push(
      `${index + 1}. [${item.provider || "-"} | trust=${item.trust_hint ?? "-"} | provenance=${item.source_provenance || "-"}] ${item.title || "(제목 없음)"}`
    );
  });

  if (Array.isArray(search.provider_errors) && search.provider_errors.length > 0) {
    search.provider_errors.slice(0, 5).forEach((item, index) => {
      lines.push(
        `provider_error ${index + 1}. [${item.provider || "-"}] query=${item.query || "-"} | ${item.error || "-"}`
      );
    });
  }

  if (Array.isArray(search.grounded_terms) && search.grounded_terms.length > 0) {
    lines.push(`- grounded_terms: ${search.grounded_terms.join(" | ")}`);
  }
  if (Array.isArray(search.missing_terms) && search.missing_terms.length > 0) {
    lines.push(`- missing_terms: ${search.missing_terms.join(" | ")}`);
  }

  ingest.slice(0, 5).forEach((item, index) => {
    lines.push(
      `ingest ${index + 1}. message_id=${item.message_id ?? "-"}, created_nodes=${(item.created_node_ids || []).join(", ") || "없음"}`
    );
  });

  return lines.join("\n");
}

function summarizeVerbalization(verbalization) {
  if (!verbalization) return null;
  return [
    "verbalization",
    `- used_llm: ${verbalization.used_llm ? "true" : "false"}`,
    `- llm_error: ${verbalization.llm_error || "없음"}`,
  ].join("\n");
}

function showResponseDebug(data) {
  const debug = data && data.debug ? data.debug : null;
  if (!debug) return;

  const sections = [
    summarizeModel(data),
    summarizeInternalExplanation(data),
    summarizeDerivedAction(debug.derived_action),
    summarizeIngest(debug.ingest),
    summarizeActivation(debug.activation),
    summarizeThinkingDebug(debug.thinking),
    summarizeCoreConclusion(debug.thinking && debug.thinking.core_conclusion),
    summarizeSearch(debug.search),
    summarizeVerbalization(debug.verbalization),
  ].filter(Boolean);

  if (sections.length > 0) {
    addDebugPanel("debug / 내부 설명", sections);
  }
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();

  const message = inputEl.value.trim();
  const file = fileInputEl.files && fileInputEl.files[0];
  const projectId = getSelectedProjectId();
  const projectName = projectNameInputEl.value.trim();
  const selectedModel = getSelectedModel();
  const zipUpload = isZipFile(file);

  if (!message && !file) return;

  if (!message && file && !zipUpload) {
    addMessage("system", "텍스트 파일을 참고 자료로 붙일 때는 함께 보낼 메시지가 필요합니다.");
    return;
  }

  if (message) {
    addMessage("user", message);
  } else if (zipUpload) {
    addMessage("user", "[ZIP 업로드]");
  }

  inputEl.value = "";
  sendBtn.disabled = true;
  sendBtn.textContent = "전송 중...";

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), getRequestTimeoutMs());

  try {
    const formData = new FormData();
    formData.append("message", message);
    if (file) formData.append("file", file);
    if (projectId) formData.append("project_id", projectId);
    if (zipUpload && projectName) formData.append("project_name", projectName);
    if (selectedModel) formData.append("model", selectedModel);

    const res = await fetch("/chat", {
      method: "POST",
      body: formData,
      signal: controller.signal,
    });

    const data = await res.json();

    if (!res.ok) {
      throw new Error(data.detail || "요청 실패");
    }

    addMessage("assistant", normalizeReply(data));

    if (data.project_id) {
      await loadProjects({ silent: true, preferredProjectId: data.project_id });
      setSelectedProject(data.project_id);
    } else {
      setSelectedProject(projectId);
    }

    if (data.used_model) {
      setModelSelection(data.used_model === modelsState.defaultModel && !selectedModel ? "" : data.used_model);
    }

    showResponseDebug(data);

    fileInputEl.value = "";
    fileNameEl.textContent = "선택된 파일 없음";
    if (zipUpload) {
      projectNameInputEl.value = "";
    }
  } catch (err) {
    if (err.name === "AbortError") {
      addMessage(
        "system",
        `오류: ${getRequestTimeoutMs() / 1000}초 안에 응답이 오지 않았습니다. 터미널의 [API] / [ORCHESTRATOR] / [OLLAMA] 로그를 확인하세요.`,
      );
    } else {
      addMessage("system", `오류: ${err.message}`);
    }
  } finally {
    clearTimeout(timeoutId);
    sendBtn.disabled = false;
    sendBtn.textContent = "전송";
    inputEl.focus();
  }
});

addMessage(
  "assistant",
  "안녕하세요. MK5 채팅 UI입니다. 현재는 그래프 기반 응답 흐름이 연결되어 있고, debug 정보는 기본적으로 숨겨져 있습니다. 필요하면 URL 뒤에 ?debug=1 을 붙여 확인할 수 있습니다.",
);

Promise.allSettled([
  loadUiConfig({ silent: true }),
  loadProjects({ silent: true }),
  loadModels({ silent: true }),
]);
