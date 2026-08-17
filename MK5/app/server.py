from __future__ import annotations

import os
import re
import shutil
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .pipeline import Pipeline
from .schemas import ChatRequest, ChatResponse
from .. import config
from ..tools.ollama_client import list_models


pipeline: Pipeline | None = None
_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
_UPLOAD_DIR = config.WORKSPACE_ROOT / ".mk5_uploads"


@asynccontextmanager
async def lifespan(app: FastAPI):
    global pipeline
    pipeline = Pipeline()
    yield
    if pipeline is not None:
        pipeline.close()
        pipeline = None


app = FastAPI(title="Machi MK5", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


def _get_pipeline() -> Pipeline:
    if pipeline is None:
        raise RuntimeError("Pipeline not initialized")
    return pipeline


@app.get("/", include_in_schema=False)
async def ui() -> FileResponse:
    return FileResponse(os.path.join(_STATIC_DIR, "index.html"))


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/models")
async def get_models() -> dict:
    return {
        "models": await list_models(),
        "current": config.OLLAMA_MODEL_NAME or None,
        "current_image": config.OLLAMA_IMAGE_MODEL_NAME or None,
    }


@app.get("/tools")
async def get_tools() -> dict:
    return {
        "tools": [
            "graph_search",
            "record_memory_correction",
            "latest_search",
            "web_research",
            "code_index",
            "code_search",
            "file_search",
            "file_create",
            "file_read",
            "document_read",
            "image_analyze",
            "file_update",
            "file_delete",
            "terminal_command",
            "tool_manual",
        ]
    }


@app.post("/upload")
async def upload_file(request: Request):
    try:
        form = await request.form()
    except (RuntimeError, AssertionError) as exc:
        return JSONResponse(
            status_code=500,
            content={
                "ok": False,
                "error": "missing_dependency",
                "message": (
                    "File upload requires python-multipart. Install MK5 requirements "
                    "or run: pip install python-multipart"
                ),
                "detail": str(exc),
            },
        )
    file = form.get("file")
    if file is None or not hasattr(file, "filename") or not hasattr(file, "file"):
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": "missing_file", "message": "Upload field 'file' is required."},
        )
    original_name = Path(file.filename or "attachment").name
    safe_name = _safe_upload_name(original_name)
    _UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    target = _unique_upload_path(_UPLOAD_DIR / safe_name)
    with target.open("wb") as handle:
        shutil.copyfileobj(file.file, handle)
    relative_path = target.resolve().relative_to(config.WORKSPACE_ROOT)
    return {
        "ok": True,
        "filename": original_name,
        "path": relative_path.as_posix(),
        "bytes": target.stat().st_size,
    }


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    try:
        result = await _get_pipeline().run(
            user_id=req.user_id,
            message=req.message,
            model=req.model,
            image_model=req.image_model,
            session_id=req.session_id,
        )
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={
                "detail": f"{type(exc).__name__}: {exc}",
                "text": f"[오류] {type(exc).__name__}: {exc}",
                "used_tools": [],
                "memory_writes": [],
                "tool_events": [],
            },
        )
    return ChatResponse(
        text=result.text,
        used_tools=result.used_tools,
        memory_writes=result.memory_writes,
        tool_events=result.tool_events,
    )


def _safe_upload_name(filename: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", filename).strip(" .")
    return cleaned or "attachment"


def _unique_upload_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    for index in range(1, 10000):
        candidate = path.with_name(f"{stem}_{index}{suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError("Could not allocate upload filename")


def run() -> None:
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8010, reload=False)

