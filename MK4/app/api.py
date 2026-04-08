from fastapi import FastAPI
from pydantic import BaseModel

from app.orchestrator import Orchestrator
from memory.db import initialize_database

app = FastAPI(title="MK4 Personalization Agent")
orchestrator = Orchestrator()


class ChatRequest(BaseModel):
    message: str


@app.on_event("startup")
def startup() -> None:
    initialize_database()


@app.get("/")
def root():
    return {"message": "mk4 is running"}


@app.post("/chat")
def chat(req: ChatRequest):
    return orchestrator.handle_chat(req.message)


@app.get("/recall")
def recall(query: str):
    return orchestrator.handle_recall(query)
