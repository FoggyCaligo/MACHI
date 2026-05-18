"""MK6 메인 파이프라인.

언어입력 → LangToGraph → TempThoughtGraph → Think 루프
  → ConclusionView → GraphToLang → 언어출력
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass

from .. import config
from ..core.goal import initialize_global_goal_graph
from ..core.storage.db import close_db, open_db
from ..core.storage.world_graph import get_node as db_get_node, insert_node
from ..core.thinking.thought_engine import ConclusionView, ThoughtEngine
from ..core.translation.lang_to_graph import translate as lang_to_graph
from ..core.utils.hash_resolver import ANCHOR_ASSISTANT, ANCHOR_USER
from ..tools.ollama_client import chat as llm_chat, get_embedding
from ..tools.search_client import search as _search


# ── GraphToLang ───────────────────────────────────────────────────────────────

async def graph_to_lang(conclusion: ConclusionView) -> str:
    """ConclusionView를 자연어로 변환한다.

    사용자 입력과 인지 그래프 구조를 함께 LLM에 전달한다.
    레이블 없는 추상 노드는 이웃 노드의 레이블과 엣지 관계로 간접 표현한다.
    """
    key_labels: list[str] = []
    ref_labels: list[str] = []
    node_map = {n.address_hash: n for n in conclusion.nodes}
    edge_by_id = {e.edge_id: e for e in conclusion.edges}
    identity_names = {ANCHOR_USER: "사용자", ANCHOR_ASSISTANT: "AI"}

    def _node_label(address_hash: str) -> str:
        node = node_map.get(address_hash)
        if address_hash in identity_names:
            return identity_names[address_hash]
        if node and node.labels:
            return node.labels[0]
        return address_hash[:8]

    for node in conclusion.nodes:
        if node.address_hash == conclusion.goal_hash:
            continue
        if node.is_abstract:
            continue
        if not node.labels:
            continue

        label_str = identity_names.get(node.address_hash) or node.labels[0]
        if node.address_hash in conclusion.key_hashes:
            key_labels.append(label_str)
        elif node.address_hash in conclusion.ref_hashes:
            ref_labels.append(label_str)

    edge_map: dict[tuple[str, str, str, str], tuple[int, str, str, str, float]] = {}
    for edge in conclusion.edges:
        src = node_map.get(edge.source_hash)
        tgt = node_map.get(edge.target_hash)
        if src is None or tgt is None:
            continue
        if src.is_abstract or tgt.is_abstract:
            continue

        is_identity_view = edge.is_temporary and edge.edge_family == "relation" and edge.source_hash in identity_names
        if edge.is_temporary and not is_identity_view:
            continue

        src_str = identity_names.get(src.address_hash) or (src.labels[0] if src.labels else edge.source_hash[:8])
        tgt_str = identity_names.get(tgt.address_hash) or (tgt.labels[0] if tgt.labels else edge.target_hash[:8])
        key = (edge.source_hash, edge.target_hash, edge.edge_family, edge.connect_type)

        priority = 0 if is_identity_view else 1 if edge.connect_type != "neutral" else 2
        candidate = (priority, src_str, tgt_str, edge.connect_type, edge.edge_weight)
        previous = edge_map.get(key)
        if previous is None or candidate[0] < previous[0] or candidate[4] > previous[4]:
            edge_map[key] = candidate

    _edge_candidates = sorted(
        edge_map.values(),
        key=lambda x: (x[0], -x[4]),
    )

    _n_edges = max(1, math.ceil(len(_edge_candidates) * config.GRAPH_TO_LANG_EDGE_RATIO))
    _edge_candidates = _edge_candidates[:_n_edges]

    edge_lines: list[str] = []
    for _, src_str, tgt_str, connect_type, weight in _edge_candidates:
        weight_str = f"{weight:.2f}".rstrip("0").rstrip(".")
        edge_lines.append(f"  - {src_str} →[{connect_type}, {weight_str}]→ {tgt_str}")

    conclusion_graph_lines: list[str] = []
    selected_graph_node_hashes: set[str] = set()
    for idx, graph in enumerate(conclusion.selected_graphs[:3], start=1):
        selected_graph_node_hashes |= graph.node_hashes
        core = ", ".join(_node_label(h) for h in sorted(graph.core_hashes)) or "(없음)"
        bridge = ", ".join(_node_label(h) for h in sorted(graph.bridge_hashes)) or "(없음)"
        exceptions = ", ".join(_node_label(h) for h in sorted(graph.exception_hashes)) or "(없음)"
        edges = []
        for edge_id in sorted(graph.edge_ids):
            edge = edge_by_id.get(edge_id)
            if edge is None or edge.is_temporary:
                continue
            edges.append(f"{_node_label(edge.source_hash)} →[{edge.connect_type}]→ {_node_label(edge.target_hash)}")
            if len(edges) >= 4:
                break
        edge_summary = "; ".join(edges) if edges else "(없음)"
        conclusion_graph_lines.append(
            f"  {idx}. core={core} / bridge={bridge} / exception={exceptions} / "
            f"score={graph.score:.3f} / uncertainty={graph.uncertainty:.2f}\n"
            f"     edges: {edge_summary}"
        )

    _SEARCH_CTX_MAX = 800
    seen_summaries: set[str] = set()
    search_ctx_parts: list[str] = []

    # 검색 요약은 더 이상 key_hash라는 이유만으로 주입하지 않는다.
    # selected ConclusionGraph에 실제로 포함된 searched node만 사용한다.
    # selected graph가 없으면 검색 결과가 답변을 오염시키지 않도록 비운다.
    allowed_search_hashes = selected_graph_node_hashes.intersection(conclusion.search_node_hashes)
    for h in allowed_search_hashes:
        node = node_map.get(h)
        if node is None:
            continue
        summary = node.payload.get("search_summary", "")
        if not summary:
            continue

        snippet = summary[:_SEARCH_CTX_MAX]
        if snippet not in seen_summaries:
            seen_summaries.add(snippet)
            search_ctx_parts.append(f"[검색 결과] {snippet}")
            if len(search_ctx_parts) >= 3:
                break

    key_text = ", ".join(key_labels) if key_labels else "(없음)"
    ref_text = ", ".join(ref_labels) if ref_labels else "(없음)"
    edge_text = "\n".join(edge_lines) if edge_lines else "  (없음)"
    conclusion_graph_text = "\n".join(conclusion_graph_lines) if conclusion_graph_lines else "  (없음)"
    search_text = "\n---\n".join(search_ctx_parts) if search_ctx_parts else "(없음)"
    user_msg = conclusion.user_input or ""

    continuity_hints = {
        "new_topic": "새로운 주제의 시작입니다.",
        "continued_topic": "이전 대화와 밀접하게 이어지는 주제입니다.",
        "related_topic": "이전 대화와 느슨하게 연관된 주제입니다.",
        "shifted_topic": "이전 대화와는 다른 새로운 주제로 전환되었습니다.",
    }
    continuity_hint = continuity_hints.get(conclusion.topic_continuity, "")

    system_msg = (
        "당신은 인지 그래프 기반 AI 어시스턴트입니다.\n"
        f"{continuity_hint}\n"
        "아래는 사용자 입력에 대해 인지 그래프 위에서 사고 과정을 거쳐 도달한 당신의 현재 인식 상태입니다.\n"
        "이 인식 상태를 바탕으로 사용자에게 자연스러운 한국어로 응답하십시오.\n"
        "핵심 키워드를 중심으로 응답을 구성하고, 참고 개념은 필요한 경우에만 활용하십시오.\n"
        "결론 그래프가 제공되면, 단일 키워드가 아니라 해당 국소 그래프의 관계 구조를 우선 반영하십시오.\n"
        "제공된 지식 및 검색 결과를 근거로 구체적이고 정확한 정보를 답변에 포함하십시오. 단, 검색결과를 언급하지 않아도 되면 빼도 됩니다.\n"
        "근거 연결이 있으면 그 관계를 자연스럽게 반영하십시오.\n"
        "인식 상태 구조 자체를 설명하거나 나열하지 마십시오.\n"
        "확실하지 않거나 모르는 게 있으면 얼버무리지 않고, 모른다고 솔직하게 답하십시오.\n\n"
        f"[핵심 키워드]\n{key_text}\n\n"
        f"[참고 개념]\n{ref_text}\n\n"
        f"[결론 그래프]\n{conclusion_graph_text}\n\n"
        f"[근거 연결]\n{edge_text}\n\n"
        f"[지식 및 검색 결과]\n{search_text}"
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

    anchors = [
        (ANCHOR_USER, "사용자", "User"),
        (ANCHOR_ASSISTANT, "AI", "Assistant"),
    ]

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

    async def run(
        self,
        user_input: str,
        model: str | None = None,
        session_id: str = "default",
    ) -> PipelineResult:
        _p0 = time.perf_counter()

        translated = await lang_to_graph(user_input, self._conn, get_embedding)
        _p1 = time.perf_counter()
        print(f"[pipeline] lang_to_graph: {_p1 - _p0:.3f}s")

        engine = ThoughtEngine(
            conn=self._conn,
            embed_fn=get_embedding,
            search_fn=_search,
            goal_node=self._goal_node,
        )
        prev_hashes = self._session_memory.get(session_id)
        conclusion = await engine.think(
            translated,
            model=model,
            user_input=user_input,
            previous_key_hashes=prev_hashes,
        )

        self._session_memory[session_id] = conclusion.key_hashes
        print(f"[pipeline] topic_continuity: {conclusion.topic_continuity} (overlap with {len(prev_hashes or set())} prev keys)")

        _p2 = time.perf_counter()
        print(f"[pipeline] think: {_p2 - _p1:.3f}s")

        response_text = await graph_to_lang(conclusion)
        print(f"[pipeline] graph_to_lang+LLM: {time.perf_counter() - _p2:.3f}s")

        return PipelineResult(
            response_text=response_text,
            conclusion=conclusion,
        )

    def close(self) -> None:
        close_db(self._conn)

    async def __aenter__(self) -> "Pipeline":
        return self

    async def __aexit__(self, *_: object) -> None:
        self.close()
