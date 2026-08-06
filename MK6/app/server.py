from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..CONCEPT_GRAPH import analyze_text


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    yield


app = FastAPI(title="MK6", version="0.1.0", lifespan=lifespan)

_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


class ChatRequest(BaseModel):
    user_id: str = Field(default="default_user", min_length=1)
    message: str
    model: str | None = None
    session_id: str = "default"


class ChatResponse(BaseModel):
    response: str
    loop_count: int
    had_empty_slots: bool
    node_count: int
    edge_count: int
    model_used: str | None = None


@app.get("/", include_in_schema=False)
async def ui() -> FileResponse:
    return FileResponse(os.path.join(_STATIC_DIR, "index.html"))


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "app": "MK6"}


@app.get("/models")
async def get_models() -> dict[str, object]:
    return {"models": ["lang-graph"], "current": "lang-graph"}


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    try:
        result = analyze_text(req.message)
        response_lines = [
            f"segments: {result.segments}",
            f"concepts: {[concept['address'] for concept in result.concepts]}",
        ]
        edge_count = max(len(result.segments) - 1, 0)
        return ChatResponse(
            response="\n".join(response_lines),
            loop_count=1,
            had_empty_slots=False,
            node_count=len(result.concepts),
            edge_count=edge_count,
            model_used="lang-graph",
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
