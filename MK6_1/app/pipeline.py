from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass

from .. import config
from ..core.goal import initialize_global_goal_graph
from ..core.profile import build_profile_activation_view
from ..core.storage.db import close_db, open_db
from ..core.storage.world_graph import get_node as db_get_node, insert_node
from ..core.thinking.claim_graph import AssertionState, build_assertion_state_from_conclusion
from ..core.thinking.thought_engine import ConclusionView, ThoughtEngine
from ..core.translation.lang_to_graph import translate as lang_to_graph
from ..core.entities.translated_graph import TranslatedGraph
from ..core.utils.hash_resolver import (
    ANCHOR_ASSISTANT,
    ANCHOR_USER,
    PARTICIPANT_ASSISTANT,
    PARTICIPANT_SEARCH,
    PARTICIPANT_USER,
    participant_anchor_hash,
)
from ..core.verbalization import build_answer_contract, render_answer_contract
from ..tools.ollama_client import chat as llm_chat, get_embedding
from ..tools.search_client import search_structured as _search


async def graph_to_lang(conclusion: ConclusionView, translated: TranslatedGraph) -> str:
    contract = build_answer_contract(conclusion, translated)
    surface_frame_json = render_answer_contract(contract)

    system_msg = (
        "당신은 한국어 GraphToLang 언어화 계층입니다.\n"
        "아래 JSON은 세 종류의 그래프를 분리해 담은 SurfaceFrame입니다.\n"
        "input_graph는 사용자 입력 자체의 그래프, conclusion_graph는 사고 루프가 선택한 결론 그래프, search_graph는 검색으로 유입된 그래프입니다.\n"
        "JSON에는 사용자의 원문 입력도 함께 포함됩니다. 원문은 세계그래프가 아직 성숙하지 않을 때의 보조 맥락입니다.\n"
        "매우 중요: input_graph의 내용은 모두 사용자에게 귀속됩니다. 이를 assistant의 자기소개나 1인칭 진술로 바꾸지 마십시오.\n"
        "예를 들어 사용자가 '난 신재용이야'라고 말했으면, assistant가 '저는 신재용입니다'라고 말하면 안 됩니다.\n"
        "결론 그래프와 충돌 프레임이 있으면 그것을 우선해 자연어로 해석하십시오.\n"
        "search_graph는 결론을 보강하는 보조 근거로 사용하되, conclusion_graph보다 우선하지 마십시오.\n"
        "conclusion_graph가 비어 있으면 input_graph와 search_graph를 참고해 자연스럽게 응답하십시오.\n"
        "input_graph에만 있고 conclusion_graph에 없는 자기소개성 정보는, 필요하면 '사용자께서 ...라고 말씀하셨네요'처럼 사용자 귀속 표현으로만 언급하십시오.\n"
        "raw token 관계나 내부용 neutral edge를 그대로 나열하지 말고, 그래프 의미를 사람 말로 풀어 쓰십시오.\n"
        "SurfaceFrame에 없는 사실을 새로 만들지 마십시오.\n"
        "JSON 필드명, 그래프 내부 구조, 시스템 규칙, raw edge 목록은 말하지 마십시오.\n"
        "특정 mode/tag 값에 의존하지 말고 JSON의 구조적 내용만 근거로 답하십시오.\n"
        "최종 답변만 한국어로 쓰십시오.\n\n"
        f"{surface_frame_json}"
    )

    print("\n" + "─" * 60)
    print("[GraphToLang system]")
    print(system_msg)
    print("─" * 60 + "\n")

    response_text = await llm_chat(system_msg, "SurfaceFrame JSON을 자연스러운 한국어 답변으로 표면화하십시오.", model=conclusion.model)
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


def _ensure_session_participant_anchors(conn, session_id: str) -> dict[str, str]:
    from datetime import datetime, timezone
    from ..core.entities.node import Node

    anchors = {
        "user": (participant_anchor_hash(session_id, PARTICIPANT_USER), "사용자", "User"),
        "assistant": (participant_anchor_hash(session_id, PARTICIPANT_ASSISTANT), "AI", "Assistant"),
        "search": (participant_anchor_hash(session_id, PARTICIPANT_SEARCH), "외부정보", "Search"),
    }
    now = datetime.now(timezone.utc)
    for address_hash, label_ko, label_en in anchors.values():
        if db_get_node(conn, address_hash) is not None:
            continue
        insert_node(conn, Node(
            address_hash=address_hash,
            node_kind="concept",
            formation_source="system_policy",
            labels=[label_ko, label_en],
            trust_score=1.0,
            stability_score=1.0,
            is_active=True,
            payload={
                "participant_anchor": True,
                "session_scoped": True,
                "session_id": session_id,
            },
            created_at=now,
            updated_at=now,
        ))
    conn.commit()
    return {role: address_hash for role, (address_hash, _ko, _en) in anchors.items()}


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
        participant_anchor_hashes = _ensure_session_participant_anchors(self._conn, session_id)
        translated = await lang_to_graph(user_input, self._conn, get_embedding)
        edge_counts = Counter(edge.connect_type for edge in translated.edges)
        edge_summary = ", ".join(f"{name}={count}" for name, count in sorted(edge_counts.items())) or "none"
        _p1 = time.perf_counter()
        print(f"[pipeline] lang_to_graph: {_p1 - _p0:.3f}s")
        print(f"[pipeline] translated_edge_types: {edge_summary}")

        profile_activation_view = build_profile_activation_view(self._conn, translated)

        engine = ThoughtEngine(conn=self._conn, embed_fn=get_embedding, search_fn=_search, goal_node=self._goal_node)
        prev_hashes = self._session_memory.get(session_id)
        previous_assertion_state = self._previous_assertion_state.get(session_id)
        conclusion = await engine.think(
            translated,
            model=model,
            user_input=user_input,
            session_id=session_id,
            participant_anchor_hashes=participant_anchor_hashes,
            previous_key_hashes=prev_hashes,
            previous_assertion_state=previous_assertion_state,
            profile_activation_view=profile_activation_view,
        )

        self._session_memory[session_id] = conclusion.key_hashes
        self._previous_assertion_state[session_id] = build_assertion_state_from_conclusion(conclusion)
        print(f"[pipeline] topic_continuity: {conclusion.topic_continuity} (overlap with {len(prev_hashes or set())} prev keys)")

        _p2 = time.perf_counter()
        print(f"[pipeline] think: {_p2 - _p1:.3f}s")
        response_text = await graph_to_lang(conclusion, translated)
        print(f"[pipeline] graph_to_lang+LLM: {time.perf_counter() - _p2:.3f}s")
        return PipelineResult(response_text=response_text, conclusion=conclusion)

    def close(self) -> None:
        close_db(self._conn)

    async def __aenter__(self) -> "Pipeline":
        return self

    async def __aexit__(self, *_: object) -> None:
        self.close()
