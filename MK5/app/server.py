from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .pipeline import Pipeline
from .schemas import ChatRequest, ChatResponse
from .. import config
from ..tools.ollama_client import list_models


pipeline: Pipeline | None = None
_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


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
    }


@app.get("/tools")
async def get_tools() -> dict:
    return {
        "tools": [
            "graph_search",
            "internet_search",
            "latest_search",
            "market_snapshot",
            "file_create",
            "file_read",
            "file_update",
            "file_delete",
            "terminal_command",
        ]
    }


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    try:
        result = await _get_pipeline().run(
            user_id=req.user_id,
            message=req.message,
            model=req.model,
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


def run() -> None:
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8010, reload=False)

