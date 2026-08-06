from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .language_graph import LanguageGraph

ROOT = Path(__file__).resolve().parent
_graph: LanguageGraph | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _graph
    _graph = LanguageGraph(ROOT / "data" / "mk_language.db")
    yield
    _graph.close()
    _graph = None


app = FastAPI(title="MACHI MK", version="0.1.0", lifespan=lifespan)


class InputRequest(BaseModel):
    text: str


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/process")
def process(req: InputRequest) -> dict:
    if _graph is None:
        raise HTTPException(503, "language graph is not ready")
    try:
        result = _graph.process(req.text)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {
        "input_id": result.input_id,
        "text": result.text,
        "alphs": result.alphs,
        "segments": result.segments,
        "evidence": [item.__dict__ for item in result.evidence],
    }
