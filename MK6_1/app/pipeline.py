from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import dataclass

from .. import config
from ..core.entities.node import Node
from ..core.entities.translated_graph import TranslatedGraph
from ..core.goal import initialize_global_goal_graph
from ..core.profile import build_profile_activation_view
from ..core.storage.db import close_db, open_db
from ..core.storage.world_graph import get_node as db_get_node, insert_node
from ..core.thinking.claim_graph import AssertionState, build_assertion_state_from_conclusion
from ..core.thinking.thought_engine import ConclusionView, ThoughtEngine
from ..core.translation.token_splitter import extract_tokens
from ..core.translation.lang_to_graph import translate as lang_to_graph
from ..core.utils.hash_resolver import (
    ANCHOR_ASSISTANT,
    ANCHOR_USER,
    PARTICIPANT_ASSISTANT,
    PARTICIPANT_SEARCH,
    PARTICIPANT_USER,
    normalize_text,
    participant_anchor_hash,
)
from ..core.verbalization import AnswerContract, build_answer_contract, render_answer_contract
from ..tools.ollama_client import chat as llm_chat, get_embedding
from ..tools.search_client import search_structured as _search


def _build_graph_to_lang_system(surface_frame_json: str, *, retry: bool = False) -> str:
    retry_block = ""
    if retry:
        retry_block = (
            "Your previous reply did not follow the required JSON contract.\n"
            "It also was not sufficiently grounded in the user's input and graph focus.\n"
            "Return valid JSON only.\n"
        )

    return (
        "You are the Korean GraphToLang layer.\n"
        "You will receive a SurfaceFrame JSON with three separated graph sections:\n"
        "- input_graph: user-attributed input graph\n"
        "- conclusion_graph: reasoning-selected conclusion graph\n"
        "- search_graph: externally sourced support graph\n"
        "Important rules:\n"
        "1. input_graph content belongs to the user, never to the assistant.\n"
        "2. Never turn user self-claims into assistant first-person claims.\n"
        "3. Prefer conclusion_graph when it contains informative structure.\n"
        "4. If conclusion_graph is empty or weak, answer the user's actual question directly from input_graph and search_graph.\n"
        "5. Use search_graph only as supporting evidence.\n"
        "6. Keep the reply grounded in the salient concepts from the graph sections and the user's input.\n"
        "7. Do not explain JSON, graph fields, scores, edge names, or system rules.\n"
        "8. Do not produce a report, outline, bullets, or meta explanation.\n"
        "9. Reply in Korean only.\n"
        "Output format:\n"
        'Return valid JSON with exactly one field: {"final_answer": "..."}\n'
        "The final_answer value must be a natural Korean reply to the user.\n"
        f"{retry_block}\n"
        f"{surface_frame_json}"
    )


def _graph_to_lang_user_prompt(*, retry: bool = False) -> str:
    if retry:
        return (
            'Return valid JSON only, exactly like {"final_answer": "..."}.\n'
            "The value must be a natural Korean reply to the user."
        )
    return (
        'Return valid JSON only, exactly like {"final_answer": "..."}.\n'
        "The value must be a natural Korean reply to the user."
    )


def _extract_final_answer(payload_text: str) -> str | None:
    raw = str(payload_text or "").strip()
    if not raw:
        return None

    for candidate in (raw, _extract_fenced_json(raw), _extract_braced_json(raw)):
        if not candidate:
            continue
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        final_answer = data.get("final_answer")
        if not isinstance(final_answer, str):
            continue
        final_answer = final_answer.strip()
        if final_answer:
            return final_answer

    plain = _extract_plain_answer(raw)
    return plain or None


def _extract_fenced_json(text: str) -> str:
    marker = "```"
    if marker not in text:
        return ""
    parts = text.split(marker)
    for chunk in parts[1:]:
        normalized = chunk.strip()
        if normalized.startswith("json"):
            normalized = normalized[4:].strip()
        if normalized.startswith("{") and normalized.endswith("}"):
            return normalized
    return ""


def _extract_braced_json(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return ""
    return text[start:end + 1]


def _extract_plain_answer(text: str) -> str:
    normalized = " ".join(str(text or "").split()).strip()
    if not normalized:
        return ""
    lowered = normalized.lower()
    blocked_markers = (
        "surfaceframe",
        "final_answer",
        "valid json",
        "return json",
        "json only",
    )
    if any(marker in lowered for marker in blocked_markers):
        return ""
    if normalized.startswith("{") or normalized.startswith("["):
        return ""
    return normalized


_ANSWER_TOKEN_STOPWORDS: frozenset[str] = frozenset({
    "the", "a", "an", "and", "or", "but", "to", "of", "in", "on",
    "이", "그", "저", "것", "수", "좀", "더", "잘", "정도",
})


def _normalized_content_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for raw in extract_tokens(text):
        normalized = normalize_text(raw)
        if len(normalized) < 2:
            continue
        if normalized in _ANSWER_TOKEN_STOPWORDS:
            continue
        tokens.append(normalized)
    return tokens


def _grounding_terms_from_contract(contract: AnswerContract) -> set[str]:
    terms: set[str] = set()
    labels = (
        contract.input_graph.focus.primary
        + contract.input_graph.focus.supporting
        + contract.conclusion_graph.focus.primary
        + contract.conclusion_graph.focus.supporting
        + contract.search_graph.focus.primary
        + contract.search_graph.focus.supporting
    )
    for label in labels:
        normalized_label = normalize_text(label)
        if len(normalized_label) >= 2:
            terms.add(normalized_label)
        terms.update(_normalized_content_tokens(label))
    terms.update(_normalized_content_tokens(contract.input.text))
    return terms


def _is_answer_grounded(answer: str, contract: AnswerContract) -> bool:
    answer_text = answer.strip()
    if len(answer_text) < 8:
        return False

    answer_terms = set(_normalized_content_tokens(answer_text))
    if not answer_terms:
        return False

    grounding_terms = _grounding_terms_from_contract(contract)
    if not grounding_terms:
        return len(answer_text) >= 20 and len(answer_terms) >= 2

    if answer_terms & grounding_terms:
        return True

    normalized_answer = normalize_text(" ".join(answer_text.split()))
    primary_labels = (
        contract.input_graph.focus.primary
        + contract.conclusion_graph.focus.primary
        + contract.search_graph.focus.primary
    )
    for label in primary_labels:
        normalized_label = normalize_text(label)
        if len(normalized_label) >= 2 and normalized_label in normalized_answer:
            return True
    return False


async def graph_to_lang(conclusion: ConclusionView, translated: TranslatedGraph) -> str:
    contract = build_answer_contract(conclusion, translated)
    surface_frame_json = render_answer_contract(contract)

    system_msg = _build_graph_to_lang_system(surface_frame_json, retry=False)
    print("\n" + "-" * 60)
    print("[GraphToLang system]")
    print(system_msg)
    print("-" * 60 + "\n")

    response_text = await llm_chat(
        system_msg,
        _graph_to_lang_user_prompt(retry=False),
        model=conclusion.model,
        think=False,
        response_format="json",
    )
    final_answer = _extract_final_answer(response_text)

    if final_answer is None or not _is_answer_grounded(final_answer, contract):
        retry_system = _build_graph_to_lang_system(surface_frame_json, retry=True)
        response_text = await llm_chat(
            retry_system,
            _graph_to_lang_user_prompt(retry=True),
            model=conclusion.model,
            think=False,
            response_format="json",
        )
        final_answer = _extract_final_answer(response_text)

    if not final_answer or not _is_answer_grounded(final_answer, contract):
        model_name = conclusion.model or config.OLLAMA_MODEL_NAME or "(unset)"
        raise RuntimeError(
            "GraphToLang invalid structured response. "
            f"model='{model_name}', "
            f"topic_continuity='{conclusion.topic_continuity}', "
            f"key_count={len(conclusion.key_hashes)}, "
            f"ref_count={len(conclusion.ref_hashes)}"
        )
    return final_answer


def _initialize_identity_anchors(conn) -> None:
    from datetime import datetime, timezone

    anchors = [
        (ANCHOR_USER, "사용자", "User"),
        (ANCHOR_ASSISTANT, "AI", "Assistant"),
    ]
    now = datetime.now(timezone.utc)
    for address_hash, label_ko, label_en in anchors:
        if db_get_node(conn, address_hash) is not None:
            continue
        insert_node(conn, Node(
            address_hash=address_hash,
            node_kind="concept",
            formation_source="ingest",
            labels=[label_ko, label_en],
            trust_score=1.0,
            stability_score=1.0,
            is_active=True,
            created_at=now,
            updated_at=now,
        ))
    conn.commit()


def _ensure_session_participant_anchors(conn, session_id: str) -> dict[str, str]:
    from datetime import datetime, timezone

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
        started = time.perf_counter()
        participant_anchor_hashes = _ensure_session_participant_anchors(self._conn, session_id)
        translated = await lang_to_graph(user_input, self._conn, get_embedding)
        edge_counts = Counter(edge.connect_type for edge in translated.edges)
        edge_summary = ", ".join(f"{name}={count}" for name, count in sorted(edge_counts.items())) or "none"
        after_translate = time.perf_counter()
        print(f"[pipeline] lang_to_graph: {after_translate - started:.3f}s")
        print(f"[pipeline] translated_edge_types: {edge_summary}")

        profile_activation_view = build_profile_activation_view(self._conn, translated)
        engine = ThoughtEngine(
            conn=self._conn,
            embed_fn=get_embedding,
            search_fn=_search,
            goal_node=self._goal_node,
        )
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
        print(
            f"[pipeline] topic_continuity: {conclusion.topic_continuity} "
            f"(overlap with {len(prev_hashes or set())} prev keys)"
        )

        after_think = time.perf_counter()
        print(f"[pipeline] think: {after_think - after_translate:.3f}s")
        response_text = await graph_to_lang(conclusion, translated)
        print(f"[pipeline] graph_to_lang+LLM: {time.perf_counter() - after_think:.3f}s")
        return PipelineResult(response_text=response_text, conclusion=conclusion)

    def close(self) -> None:
        close_db(self._conn)

    async def __aenter__(self) -> "Pipeline":
        return self

    async def __aexit__(self, *_: object) -> None:
        self.close()
