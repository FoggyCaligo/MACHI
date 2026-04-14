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

    if (!silent) {
      addMessage("system", `프로젝트 목록 갱신 완료\n- project_count: ${projectsState.projects.length}`);
    }
  } catch (err) {
    projectsState = {
      projects: [],
      error: err.message,
    };
    renderProjectOptions("");
    if (!silent) {
      addMessage("system", `프로젝트 목록 로드 실패: ${err.message}`);
    }
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

    if (!silent) {
      const lines = [
        "모델 목록 갱신 완료",
        `- ollama_available: ${modelsState.ollamaAvailable ? "예" : "아니오"}`,
        `- default_model: ${modelsState.defaultModel || "없음"}`,
        `- local_models: ${modelsState.models.length}`,
      ];
      addMessage("system", lines.join("\n"));
    }

    if (modelsState.error) {
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
  addMessage("system", "프로젝트 선택을 해제했습니다.");
});

refreshProjectsBtn.addEventListener("click", () => {
  loadProjects();
});

refreshModelsBtn.addEventListener("click", () => {
  loadModels();
});

clearModelBtn.addEventListener("click", () => {
  setModelSelection("");
  addMessage("system", `기본 모델 사용으로 되돌렸습니다. (${modelsState.defaultModel || "서버 기본값"})`);
});

projectSelectEl.addEventListener("change", () => {
  const projectId = getSelectedProjectId();
  setSelectedProject(projectId);
  addMessage("system", `선택 프로젝트: ${getProjectDisplayName(projectId) || "없음"}`);
});

modelSelectEl.addEventListener("change", () => {
  const selected = getSelectedModel();
  setModelSelection(selected);
  addMessage("system", `선택 모델: ${selected || modelsState.defaultModel || "서버 기본값"}`);
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

function summarizeExtract(extractInfo) {
  if (!extractInfo) return null;
  const stored = extractInfo.stored ? "예" : "아니오";
  return [
    "profile evidence 추출",
    `- stored: ${stored}`,
    `- document_count: ${extractInfo.document_count ?? 0}`,
    `- candidate_count: ${extractInfo.candidate_count ?? 0}`,
  ].join("\n");
}

function summarizeSync(syncInfo) {
  if (!syncInfo) return null;
  return [
    "memory sync 결과",
    `- processed: ${syncInfo.processed ?? 0}`,
    `- inserted_profiles: ${syncInfo.inserted_profiles ?? 0}`,
    `- added_corrections: ${syncInfo.added_corrections ?? 0}`,
    `- skipped: ${syncInfo.skipped ?? 0}`,
  ].join("\n");
}

function summarizeChunkUsage(chunks) {
  if (!Array.isArray(chunks) || chunks.length === 0) return null;
  const lines = chunks.slice(0, 5).map((chunk, index) => {
    const score = typeof chunk.score === "number" ? chunk.score.toFixed(1) : String(chunk.score ?? "-");
    return `${index + 1}. ${chunk.file_path} (${chunk.start_line}-${chunk.end_line}, score=${score})`;
  });
  return [`사용 chunk: ${chunks.length}건`, ...lines].join("\n");
}

function summarizeEvidenceUsage(evidences) {
  if (!Array.isArray(evidences) || evidences.length === 0) return null;
  const lines = evidences.slice(0, 5).map((item, index) => {
    return `${index + 1}. ${item.topic} | ${item.source_file_path} | confidence=${item.confidence}`;
  });
  return [`사용 profile evidence: ${evidences.length}건`, ...lines].join("\n");
}

function summarizeArtifactIngest(data) {
  if (!data || data.mode !== "artifact") return null;
  if (typeof data.stored_file_count !== "number") return null;
  return [
    "artifact ingest 결과",
    `- stored_file_count: ${data.stored_file_count ?? 0}`,
    `- stored_chunk_count: ${data.stored_chunk_count ?? 0}`,
    `- skipped_file_count: ${data.skipped_file_count ?? 0}`,
  ].join("\n");
}

function showResponseMeta(data) {
  const blocks = [
    summarizeModel(data),
    summarizeArtifactIngest(data),
    summarizeExtract(data.profile_evidence_extract),
    summarizeSync(data.profile_memory_sync),
    summarizeChunkUsage(data.used_chunks),
    summarizeEvidenceUsage(data.used_profile_evidence),
  ].filter(Boolean);

  blocks.forEach((block) => addMessage("system", block));
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

  if (file) {
    if (zipUpload) {
      addMessage("system", `ZIP 업로드: ${file.name} (artifact/project로 처리)`);
      if (projectName) {
        addMessage("system", `프로젝트 이름: ${projectName}`);
      }
    } else {
      addMessage("system", `첨부 파일: ${file.name} (현재 질문 참고 자료)`);
    }
  }

  if (projectId) {
    addMessage("system", `project: ${getProjectDisplayName(projectId) || "알 수 없는 프로젝트"}`);
  }

  addMessage("system", `model: ${selectedModel || modelsState.defaultModel || "서버 기본값"}`);

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
      addMessage(
        "system",
        `프로젝트 저장됨: ${data.project_name || getProjectDisplayName(data.project_id) || "이름 없음"}`
      );
    } else {
      setSelectedProject(projectId);
    }

    if (data.used_model) {
      setModelSelection(data.used_model === modelsState.defaultModel && !selectedModel ? "" : data.used_model);
    }

    showResponseMeta(data);

    fileInputEl.value = "";
    fileNameEl.textContent = "선택된 파일 없음";
    if (zipUpload) {
      projectNameInputEl.value = "";
    }
  } catch (err) {
    if (err.name === "AbortError") {
      addMessage(
        "system",
        `오류: ${getRequestTimeoutMs() / 1000}초 안에 응답이 오지 않았습니다. 터미널의 [API] / [ORCHESTRATOR] / [OLLAMA] 로그를 확인하세요.`
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
  "안녕하세요. MK5 채팅 UI입니다. 현재는 그래프 ingest → 국부 활성화 → 구조 점검 흐름을 우선 연결해 두었고, project/profile 구분 없이 모든 입력을 chat 흐름으로 처리합니다."
);

Promise.allSettled([
  loadUiConfig({ silent: true }),
  loadProjects({ silent: true }),
  loadModels({ silent: true }),
]);