from contextlib import asynccontextmanager
from pathlib import Path
import time
from typing import Annotated

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.orchestrator import Orchestrator
from app.request_orchestrator import RequestOrchestrator
from config import CHAT_UPDATE_EXTRACT_MODEL, OLLAMA_DEFAULT_MODEL, OLLAMA_LIST_TIMEOUT, UI_REQUEST_TIMEOUT_MS
from memory.db import initialize_database
from project_analysis.api.routes import router as project_router
from project_analysis.stores.db import init_project_tables
from tools.ollama_client import OllamaClient

UPLOAD_DIR = Path("data/uploads")
EXTRACT_DIR = Path("data/extracted")
STATIC_DIR = Path(__file__).resolve().parent / "static"

def _log(message: str) -> None:
    print(f"[API] {message}", flush=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize_database()
    init_project_tables()
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    EXTRACT_DIR.mkdir(parents=True, exist_ok=True)
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    _log("startup complete")
    yield


app = FastAPI(title="MK4 Personalization Agent", lifespan=lifespan)
orchestrator = Orchestrator()
request_orchestrator = RequestOrchestrator(
    upload_dir=UPLOAD_DIR,
    extract_dir=EXTRACT_DIR,
    orchestrator=orchestrator,
)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

app.include_router(project_router)


@app.get("/")
def root():
    return {"message": "mk4 is running", "ui": "/ui"}


@app.get("/ui")
def ui():
    html_path = STATIC_DIR / "chat.html"
    if not html_path.exists():
        raise HTTPException(status_code=404, detail="UI 파일이 없습니다.")
    return FileResponse(html_path)


@app.get("/models")
def list_models():
    try:
        models = OllamaClient.list_local_models(timeout=OLLAMA_LIST_TIMEOUT)
        return {
            "default_model": OLLAMA_DEFAULT_MODEL,
            "chat_extract_model": CHAT_UPDATE_EXTRACT_MODEL,
            "ollama_available": True,
            "models": models,
            "error": None,
        }
    except Exception as exc:
        _log(f"/models warning | error={exc}")
        return {
            "default_model": OLLAMA_DEFAULT_MODEL,
            "chat_extract_model": CHAT_UPDATE_EXTRACT_MODEL,
            "ollama_available": False,
            "models": [],
            "error": str(exc),
        }


@app.get("/ui-config")
def ui_config():
    return {
        "request_timeout_ms": UI_REQUEST_TIMEOUT_MS,
    }


def _normalize_optional(value: str | None) -> str | None:
    value = (value or "").strip()
    if value.lower() in {"", "string", "null", "none", "undefined"}:
        return None
    return value


def _resolve_model_name(model: str | None) -> str:
    return (model or OLLAMA_DEFAULT_MODEL).strip()


def _http_error_from_exception(exc: Exception) -> HTTPException:
    detail = str(exc)
    if detail.startswith("OLLAMA_TIMEOUT:"):
        friendly = detail.split(":", 1)[1].strip() or "로컬 Ollama 응답 시간이 초과되었습니다."
        return HTTPException(status_code=504, detail=friendly)
    return HTTPException(status_code=500, detail=detail)


@app.post("/chat")
async def chat(
    message: Annotated[str | None, Form()] = None,
    project_id: Annotated[str | None, Form()] = None,
    project_name: Annotated[str | None, Form()] = None,
    model: Annotated[str | None, Form()] = None,
    file: Annotated[UploadFile | None, File()] = None,
):
    started_at = time.perf_counter()

    message = (message or "").strip()
    project_id = _normalize_optional(project_id)
    project_name = _normalize_optional(project_name)
    model = _normalize_optional(model)
    effective_model = _resolve_model_name(model)

    filename = (file.filename or "") if file is not None else ""
    is_zip_upload = bool(file is not None and filename.lower().endswith(".zip"))

    _log(
        f"/chat start | message_len={len(message)} | "
        f"project_id={project_id} | "
        f"model={effective_model} | "
        f"file={filename or '-'} | is_zip={is_zip_upload}"
    )

    try:
        result = request_orchestrator.handle_chat_request(
            message=message,
            project_id=project_id,
            project_name=project_name,
            model=model,
            effective_model=effective_model,
            file=file,
        )

        elapsed = time.perf_counter() - started_at
        _log(
            f"/chat complete | mode={result.get('mode')} | "
            f"project_id={result.get('project_id')} | elapsed={elapsed:.2f}s"
        )
        return result

    except HTTPException:
        raise
    except Exception as exc:
        elapsed = time.perf_counter() - started_at
        _log(f"/chat error | elapsed={elapsed:.2f}s | error={exc}")
        raise _http_error_from_exception(exc) from exc
    
@app.get("/recall")
def recall(query: str):
    started_at = time.perf_counter()
    try:
        result = orchestrator.handle_recall(query)
        elapsed = time.perf_counter() - started_at
        _log(f"/recall complete | query_len={len(query)} | elapsed={elapsed:.2f}s")
        return result
    except Exception as exc:
        elapsed = time.perf_counter() - started_at
        _log(f"/recall error | elapsed={elapsed:.2f}s | error={exc}")
        raise _http_error_from_exception(exc) from exc
