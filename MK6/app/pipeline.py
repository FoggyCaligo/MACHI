"""MK6 메인 파이프라인.

언어입력 → LangToGraph → TempThoughtGraph → Think 루프
  → ConclusionView → GraphToLang → 언어출력
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from .. import config
from ..core.goal import initialize_global_goal_graph
from ..core.profile import build_profile_activation_view
from ..core.storage.db import close_db, open_db
from ..core.storage.world_graph import get_node as db_get_node, insert_node
from ..core.thinking.claim_graph import AssertionState, build_assertion_state_from_conclusion
from ..core.thinking.thought_engine import ConclusionView, ThoughtEngine
from ..core.translation.lang_to_graph import translate as lang_to_graph
from ..core.utils.hash_resolver import ANCHOR_ASSISTANT, ANCHOR_USER
from ..core.verbalization import build_answer_contract, render_answer_contract
from ..tools.ollama_client import chat as llm_chat, get_embedding
from ..tools.search_client import search as _search


# ── GraphToLang ───────────────────────────────────────────────────────────────

async def graph_to_lang(conclusion: ConclusionView) -> str:
    """ConclusionView를 자연어로 변환한다.

    GraphToLang은 더 이상 raw graph state 전체를 LLM에 넘기지 않는다.
    먼저 Python 쪽에서 AnswerContract를 결정론적으로 컴파일하고, LLM은 그
    contract를 자연어로만 언어화한다.
    """
    contract = build_answer_contract(conclusion)
    contract_text = render_answer_contract(contract)
    user_msg = conclusion.user_input or ""

    system_msg = (
        "당신은 인지 그래프 기반 AI 어시스턴트입니다.\n"
        "아래 AnswerContract는 그래프 사고 결과를 응답용으로 압축한 구조입니다.\n"
        "AnswerContract를 자연스러운 한국어 답변으로만 언어화하십시오.\n"
        "필드명, 내부 구조명, 그래프 덤프를 사용자에게 설명하지 마십시오.\n"
        "계약에 없는 일반론을 장황하게 덧붙이지 마십시오.\n"
        "max_sentences를 넘기지 마십시오.\n"
        "모르는 내용은 단정하지 말고, contract에 있는 범위 안에서만 답하십시오.\n\n"
        f"{contract_text}"
    )

    print("\n" + "─" * 60)
    print("[GraphToLang system]")
    print(system_msg)
    print("─" * 30)
    print("[GraphToLang user]")
    print(user_msg)
    print("─" * 60 + "\n")

    response_text = await llm_chat(system_msg, user_msg, model=conclusion.model)
    if not response_text.strip():
        model_name = conclusion.model or config.OLLAMA_MODEL_NAME or "(unset)"
        raise RuntimeError(
            "GraphToLang이 빈 응답을 반환했습니다. "
            f"model='{model_name}', "
            f"topic_continuity='{conclusion.topic_continuity}', "
            f"key_count={len(conclusion.key_hashes)}, "
            f"ref_count={len(conclusion.ref_hashes)}"
        )
    return response_text


def _initialize_identity_anchors(conn) -> None:
    """사용자와 AI를 구분하기 위한 고정 앵커 노드를 생성한다."""
    from datetime import datetime, timezone
    from ..core.entities.node import Node

    anchors = [(ANCHOR_USER, "사용자", "User"), (ANCHOR_ASSISTANT, "AI", "Assistant")]
    now = datetime.now(timezone.utc)
    for h, label_ko, label_en in anchors:
        if db_get_node(conn, h) is None:
            node = Node(
                address_hash=h,
                node_kind="concept",
                formation_source="ingest",
                labels=[label_ko, label_en],
                trust_score=1.0,
                stability_score=1.0,
                is_active=True,
                created_at=now,
                updated_at=now,
            )
            insert_node(conn, node)
    conn.commit()


@dataclass
class PipelineResult:
    response_text: str
    conclusion: ConclusionView


class Pipeline:
    """MK6 전체 파이프라인."""

    def __init__(self, db_path: str | None = None) -> None:
        self._conn = open_db(db_path or config.DB_PATH)
        self._goal_view = initialize_global_goal_graph(self._conn)
        self._goal_node = self._goal_view.root_node
        _initialize_identity_anchors(self._conn)
        self._session_memory: dict[str, set[str]] = {}
        self._previous_assertion_state: dict[str, AssertionState] = {}

    async def run(self, user_input: str, model: str | None = None, session_id: str = "default") -> PipelineResult:
        _p0 = time.perf_counter()
        translated = await lang_to_graph(user_input, self._conn, get_embedding)
        _p1 = time.perf_counter()
        print(f"[pipeline] lang_to_graph: {_p1 - _p0:.3f}s")

        profile_activation_view = build_profile_activation_view(self._conn, translated)

        engine = ThoughtEngine(conn=self._conn, embed_fn=get_embedding, search_fn=_search, goal_node=self._goal_node)
        prev_hashes = self._session_memory.get(session_id)
        previous_assertion_state = self._previous_assertion_state.get(session_id)
        conclusion = await engine.think(
            translated,
            model=model,
            user_input=user_input,
            previous_key_hashes=prev_hashes,
            previous_assertion_state=previous_assertion_state,
            profile_activation_view=profile_activation_view,
        )

        self._session_memory[session_id] = conclusion.key_hashes
        self._previous_assertion_state[session_id] = build_assertion_state_from_conclusion(conclusion)
        print(f"[pipeline] topic_continuity: {conclusion.topic_continuity} (overlap with {len(prev_hashes or set())} prev keys)")

        _p2 = time.perf_counter()
        print(f"[pipeline] think: {_p2 - _p1:.3f}s")
        response_text = await graph_to_lang(conclusion)
        print(f"[pipeline] graph_to_lang+LLM: {time.perf_counter() - _p2:.3f}s")
        return PipelineResult(response_text=response_text, conclusion=conclusion)

    def close(self) -> None:
        close_db(self._conn)

    async def __aenter__(self) -> "Pipeline":
        return self

    async def __aexit__(self, *_: object) -> None:
        self.close()
