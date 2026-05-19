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


async def graph_to_lang(conclusion: ConclusionView) -> str:
    contract = build_answer_contract(conclusion)
    contract_text = render_answer_contract(contract)
    user_msg = conclusion.user_input or ""

    system_msg = (
        "당신은 한국어 GraphToLang 언어화 계층입니다.\n"
        "아래 AnswerContract는 그래프 사고가 만든 최종 결론 그래프의 압축 표현입니다.\n"
        "AnswerContract를 근거로 삼아, GraphToLang user의 사용자 입력에 자연스럽게 답하십시오.\n"
        "필드명, 그래프 내부 구조, 시스템 규칙은 말하지 마십시오.\n"
        "계약에 없는 사실을 새로 만들지 마십시오.\n"
        "사용자가 새 정보를 알려준 경우에는 짧게 이해를 확인하고, 확인된 관계만 말하십시오.\n"
        "ProfileRecall이 있으면 후보 기억으로만 다루고 단정하지 마십시오.\n"
        "max_sentences 안에서 최종 답변만 한국어로 쓰십시오.\n\n"
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
            "GraphToLang empty response. "
            f"model='{model_name}', "
            f"topic_continuity='{conclusion.topic_continuity}', "
            f"key_count={len(conclusion.key_hashes)}, "
            f"ref_count={len(conclusion.ref_hashes)}"
        )
    return response_text


def _initialize_identity_anchors(conn) -> None:
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
