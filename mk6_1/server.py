from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

from .ollama_client import list_models
from .pipeline import Pipeline

app = FastAPI(title="Machi MK6_1")
pipeline = Pipeline()


class ChatRequest(BaseModel):
    message: str
    model: str | None = None
    session_id: str = "default"


@app.post("/api/chat")
async def chat(request: ChatRequest):
    result = await pipeline.run(request.message, model=request.model, session_id=request.session_id)
    return {"response": result.response_text, "surface_frame": result.surface_frame}


@app.get("/api/models")
async def models():
    return {"models": await list_models()}


@app.on_event("shutdown")
async def shutdown():
    pipeline.close()
