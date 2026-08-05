from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

from agent import run_agent
from config import settings
from memory import init_db, save_message, update_profile_from_user_text

app = FastAPI(title="Gemma 4 26B A4B Trusted Search Agent")

@app.get("/")
def root():
    return {"message": "gemma_local_agent is running"}


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    reply: str
    tool_traces: list[dict]


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "model": settings.ollama_model}


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    user_input = req.message.strip()

    save_message("user", user_input)
    update_profile_from_user_text(user_input)

    reply, tool_traces = run_agent(user_input)

    save_message("assistant", reply)

    return ChatResponse(reply=reply, tool_traces=tool_traces)
