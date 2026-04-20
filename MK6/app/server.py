"""MK6 FastAPI 서버.

엔드포인트:
  GET  /           UI (index.html)
  POST /chat       사용자 입력 → 언어 응답
  GET  /health     서버 상태 확인
  GET  /graph/node/{address_hash}         노드 조회
  GET  /graph/neighbors/{address_hash}    이웃 노드 조회
"""
from __future__ import annotations

import logging
import os
import signal
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .pipeline import Pipeline
from ..core.storage.world_graph import get_node, get_edges_for_node, get_words_for_node
from ..tools.ollama_client import list_models
from .. import config

logger = logging.getLogger(__name__)


# ── 앱 생명주기 ───────────────────────────────────────────────────────────────

_pipeline: Pipeline | None = None


def _shutdown_handler(signum: int, frame: object) -> None:
    """SIGINT / SIGTERM 수신 시 DB를 안전하게 닫는다.

    uvicorn이 lifespan 종료를 완료하기 전에 프로세스가 종료되는 경우
    (예: 이중 Ctrl+C, kill 명령어)를 대비해 WAL 체크포인트를 보장한다.
    """
    if _pipeline is not None:
        try:
            _pipeline.close()
        except Exception:
            pass
    # 기본 동작으로 복구하고 시그널을 재전달 → 프로세스 정상 종료
    signal.signal(signum, signal.SIG_DFL)
    signal.raise_signal(signum)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    global _pipeline
    _pipeline = Pipeline()
    # 시그널 핸들러 등록 — lifespan 종료 외 경로로 프로세스가 죽을 때 대비
    signal.signal(signal.SIGINT, _shutdown_handler)
    signal.signal(signal.SIGTERM, _shutdown_handler)
    yield
    if _pipeline is not None:
        _pipeline.close()
        _pipeline = None


app = FastAPI(title="MK6", version="0.1.0", lifespan=lifespan)

# 정적 파일 마운트 (app/static/)
_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


def _get_pipeline() -> Pipeline:
    if _pipeline is None:
        raise RuntimeError("Pipeline not initialized")
    return _pipeline


# ── 요청/응답 스키마 ──────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    model: str | None = None   # None이면 config.OLLAMA_MODEL_NAME 사용


class ChatResponse(BaseModel):
    response: str
    loop_count: int
    had_empty_slots: bool
    node_count: int
    edge_count: int
    model_used: str | None = None


class NodeResponse(BaseModel):
    address_hash: str
    labels: list[str]
    node_kind: str
    is_abstract: bool
    trust_score: float
    stability_score: float
    formation_source: str
    is_active: bool
    words: list[str]


class NeighborResponse(BaseModel):
    address_hash: str
    labels: list[str]
    connect_type: str
    direction: str   # "outgoing" | "incoming"


# ── 라우터 ────────────────────────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
async def ui() -> FileResponse:
    return FileResponse(os.path.join(_STATIC_DIR, "index.html"))


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "model": config.OLLAMA_MODEL_NAME}


@app.get("/models")
async def get_models() -> dict:
    """Ollama에 설치된 모델 목록을 반환한다."""
    models = await list_models()
    return {
        "models": models,
        "current": config.OLLAMA_MODEL_NAME or None,
    }


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    try:
        pipeline = _get_pipeline()
        result = await pipeline.run(req.message, model=req.model)
        c = result.conclusion
        return ChatResponse(
            response=result.response_text,
            loop_count=c.loop_count,
            had_empty_slots=c.had_empty_slots,
            node_count=len(c.nodes),
            edge_count=len(c.edges),
            model_used=c.model or config.OLLAMA_MODEL_NAME or None,
        )
    except Exception as exc:
        logger.exception("POST /chat 처리 중 오류: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/graph/node/{address_hash}", response_model=NodeResponse)
async def get_graph_node(address_hash: str) -> NodeResponse:
    pipeline = _get_pipeline()
    node = get_node(pipeline._conn, address_hash)
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")
    words = get_words_for_node(pipeline._conn, address_hash)
    return NodeResponse(
        address_hash=node.address_hash,
        labels=node.labels,
        node_kind=node.node_kind,
        is_abstract=node.is_abstract,
        trust_score=node.trust_score,
        stability_score=node.stability_score,
        formation_source=node.formation_source,
        is_active=node.is_active,
        words=[w.surface_form for w in words],
    )


@app.get("/graph/neighbors/{address_hash}", response_model=list[NeighborResponse])
async def get_neighbors(address_hash: str) -> list[NeighborResponse]:
    pipeline = _get_pipeline()
    node = get_node(pipeline._conn, address_hash)
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")

    edges = get_edges_for_node(pipeline._conn, address_hash, active_only=True)
    result: list[NeighborResponse] = []
    for edge in edges:
        if edge.source_hash == address_hash:
            neighbor_hash = edge.target_hash
            direction = "outgoing"
        else:
            neighbor_hash = edge.source_hash
            direction = "incoming"

        neighbor = get_node(pipeline._conn, neighbor_hash)
        if neighbor is None:
            continue

        result.append(NeighborResponse(
            address_hash=neighbor.address_hash,
            labels=neighbor.labels,
            connect_type=edge.connect_type,
            direction=direction,
        ))
    return result
