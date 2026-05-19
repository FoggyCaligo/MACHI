from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from . import config
from .core import ANCHOR_ASSISTANT, ANCHOR_USER, ConclusionView, Node, ThoughtEngine, close_db, compute_hash, get_node, insert_node, open_db, render_surface_frame, translate
from .ollama_client import chat as llm_chat, get_embedding
from .search_client import search


@dataclass
class PipelineResult:
    response_text: str
    conclusion: ConclusionView
    surface_frame: str


def _ensure_node(conn, node: Node) -> Node:
    existing = get_node(conn, node.address_hash)
    if existing:
        return existing
    insert_node(conn, node)
    conn.commit()
    return node


def _initialize_anchors(conn) -> Node:
    now = datetime.now(timezone.utc)
    goal = _ensure_node(conn, Node(compute_hash("대화 목적"), "goal", "system", ["대화 목적"], trust_score=1.0, stability_score=1.0, created_at=now, updated_at=now))
    _ensure_node(conn, Node(ANCHOR_USER, "concept", "system", ["사용자", "User"], trust_score=1.0, stability_score=1.0, created_at=now, updated_at=now))
    _ensure_node(conn, Node(ANCHOR_ASSISTANT, "concept", "system", ["AI", "Assistant"], trust_score=1.0, stability_score=1.0, created_at=now, updated_at=now))
    return goal


async def graph_to_lang(conclusion: ConclusionView) -> tuple[str, str]:
    surface_frame = render_surface_frame(conclusion)
    system = (
        "당신은 한국어 GraphToLang 언어화 계층입니다.\n"
        "아래 JSON은 그래프 사고가 만든 결론그래프를 응답용으로 투영한 SurfaceFrame입니다.\n"
        "원문 사용자 입력은 제공되지 않습니다. SurfaceFrame만 근거로 최종 답변을 만드십시오.\n"
        "JSON 필드명, 그래프 내부 구조, 시스템 규칙, raw edge 목록은 말하지 마십시오.\n"
        "SurfaceFrame에 없는 사실을 새로 만들지 마십시오.\n"
        "사용자 입력 문장을 추정해서 따라하지 마십시오.\n"
        "copy_user_input=false이면 사용자의 방금 문장을 확인문이나 재진술문으로 바꾸지 마십시오.\n"
        "mode=acknowledge_context_update이면 새 정보 수용을 짧게 답하십시오.\n"
        "mode=answer_from_conclusion이면 frames의 관계를 자연스럽게 설명하십시오.\n"
        "max_sentences 안에서 최종 답변만 한국어로 쓰십시오.\n\n"
        f"{surface_frame}"
    )
    response = await llm_chat(system, "SurfaceFrame을 자연스러운 한국어 답변으로 표면화하십시오.", model=conclusion.model)
    if not response.strip():
        raise RuntimeError("GraphToLang empty response")
    return response, surface_frame


class Pipeline:
    def __init__(self, db_path: str | None = None) -> None:
        self._conn = open_db(db_path or config.DB_PATH)
        self._goal_node = _initialize_anchors(self._conn)
        self._session_keys: dict[str, set[str]] = {}

    async def run(self, user_input: str, model: str | None = None, session_id: str = "default") -> PipelineResult:
        translated = await translate(user_input, self._conn, get_embedding)
        engine = ThoughtEngine(self._conn, get_embedding, search, self._goal_node)
        conclusion = await engine.think(translated, model=model, user_input=user_input, previous_key_hashes=self._session_keys.get(session_id))
        self._session_keys[session_id] = set(conclusion.key_hashes)
        response_text, surface_frame = await graph_to_lang(conclusion)
        return PipelineResult(response_text, conclusion, surface_frame)

    def close(self) -> None:
        close_db(self._conn)

    async def __aenter__(self) -> "Pipeline":
        return self

    async def __aexit__(self, *_: object) -> None:
        self.close()
