"""MK6 메인 파이프라인.

언어입력 → LangToGraph → TempThoughtGraph → Think 루프
  → ConclusionView → GraphToLang → 언어출력
"""
from __future__ import annotations

import math
import sqlite3
import time
from dataclasses import dataclass

from ..core.entities.node import Node
from ..core.storage.db import open_db, close_db
from ..core.storage.world_graph import get_node as db_get_node, insert_node
from ..core.translation.lang_to_graph import translate as lang_to_graph
from ..core.thinking.thought_engine import ThoughtEngine, ConclusionView
from ..tools.ollama_client import get_embedding, generate, chat as llm_chat
from ..tools.search_client import search as _search
from .. import config


# ── GraphToLang ───────────────────────────────────────────────────────────────

async def graph_to_lang(conclusion: ConclusionView) -> str:
    """ConclusionView를 자연어로 변환한다.

    사용자 입력과 인지 그래프 구조를 함께 LLM에 전달한다.
    레이블 없는 추상 노드는 이웃 노드의 레이블과 엣지 관계로 간접 표현한다.
    """
    # ── 구조 직렬화 ───────────────────────────────────────────────────────────
    # ── 노드 분류: known_hashes → 핵심 키워드, 신규 ingest → 참고 개념 ────────
    key_labels: list[str] = []
    ref_labels: list[str] = []
    node_map = {n.address_hash: n for n in conclusion.nodes}

    for node in conclusion.nodes:
        if node.address_hash == conclusion.goal_hash:
            continue
        # abstract 노드는 GraphToLang 출력에서 제외.
        # 분화 결과로 생성된 구조 노드이며, LLM 컨텍스트에 노이즈만 추가한다.
        if node.is_abstract:
            continue
        if not node.labels:
            continue

        label_str = node.labels[0]

        # 핵심 키워드: near 그룹 — centroid에 가까운 토큰 (문장 대표 개념).
        # 참고 개념:  far 그룹  — centroid에서 먼 토큰 (도메인 특이 개념·고유명사).
        # 두 기준 모두 언어 구조 기반이며 그래프 상태(DB 존재 여부)와 무관하다.
        if node.address_hash in conclusion.key_hashes:
            key_labels.append(label_str)
        elif node.address_hash in conclusion.ref_hashes:
            ref_labels.append(label_str)

    # ── 엣지: 비임시 엣지 → 근거 연결 ───────────────────────────────────────
    # abstract 노드가 엔드포인트인 엣지는 제외 (분화 구조 엣지 → LLM 컨텍스트 노이즈)
    # 정렬: non-neutral 먼저 > edge_weight 내림차순 > search 외 provenance 먼저
    # 상한: 정렬 후 상위 GRAPH_TO_LANG_EDGE_RATIO(30%)만 포함
    _edge_candidates: list[tuple] = []   # (sort_key, src_str, tgt_str, connect_type, weight)
    for edge in conclusion.edges:
        if edge.is_temporary:
            continue
        src = node_map.get(edge.source_hash)
        tgt = node_map.get(edge.target_hash)
        if src is None or tgt is None:
            continue
        if src.is_abstract or tgt.is_abstract:
            continue
        src_str = src.labels[0] if src.labels else edge.source_hash[:8]
        tgt_str = tgt.labels[0] if tgt.labels else edge.target_hash[:8]
        sort_key = (
            0 if edge.connect_type != "neutral" else 1,   # non-neutral 우선
            -edge.edge_weight,                             # 높은 weight 우선
            0 if edge.provenance_source != "search" else 1,  # search 외 provenance 우선
        )
        _edge_candidates.append((sort_key, src_str, tgt_str, edge.connect_type, edge.edge_weight))

    _edge_candidates.sort(key=lambda x: x[0])

    # 상위 30% 절삭 — 노드 수 n에서 생성되는 pairwise 엣지는 O(n²)이므로
    # 정렬 후 상위 비율만 LLM에 전달한다.
    _n_edges = max(1, math.ceil(len(_edge_candidates) * config.GRAPH_TO_LANG_EDGE_RATIO))
    _edge_candidates = _edge_candidates[:_n_edges]

    edge_lines: list[str] = []
    for _, src_str, tgt_str, connect_type, weight in _edge_candidates:
        weight_str = f"{weight:.2f}".rstrip("0").rstrip(".")
        edge_lines.append(f"  - {src_str} →[{connect_type}, {weight_str}]→ {tgt_str}")

    # ── 검색 컨텍스트: 이번 세션에서 search_summary가 설정된 노드만 수집 ──────
    # conclusion.search_node_hashes: _ingest_slot이 이번 요청 중 search_summary를
    # 실제로 설정한 노드 해시 집합. 이전 세션에서 로드된 이웃 노드의 summary가
    # 새어나오는 것을 방지한다.
    _SEARCH_CTX_MAX = 600   # 시스템 메시지에 포함할 검색 요약 최대 길이
    seen_summaries: set[str] = set()
    search_ctx_parts: list[str] = []
    for node in conclusion.nodes:
        if node.address_hash not in conclusion.search_node_hashes:
            continue
        summary = node.payload.get("search_summary", "")
        if not summary:
            continue
        snippet = summary[:_SEARCH_CTX_MAX]
        if snippet not in seen_summaries:
            seen_summaries.add(snippet)
            search_ctx_parts.append(snippet)
            if len(search_ctx_parts) >= 2:   # 최대 2개 (중복 제거 후)
                break

    key_text    = ", ".join(key_labels) if key_labels else "(없음)"
    ref_text    = ", ".join(ref_labels) if ref_labels else "(없음)"
    edge_text   = "\n".join(edge_lines) if edge_lines else "  (없음)"
    search_text = ("\n---\n".join(search_ctx_parts)) if search_ctx_parts else "(없음)"

    user_msg = conclusion.user_input or ""

    system_msg = (
        "당신은 인지 그래프 기반 AI 어시스턴트입니다.\n"
        "아래는 사용자 입력에 대해 인지 그래프 위에서 사고 과정을 거쳐 도달한 당신의 현재 인식 상태입니다.\n"
        "이 인식 상태를 바탕으로 사용자에게 자연스러운 한국어로 응답하십시오.\n"
        "핵심 키워드를 중심으로 응답을 구성하고, 참고 개념은 필요한 경우에만 활용하십시오.\n"
        "검색 컨텍스트가 있으면 이를 근거로 구체적인 정보를 답변에 포함하십시오. 단, 검색결과를 언급하지 않아도 되면 빼도 됩니다.\n"
        "근거 연결이 있으면 그 관계를 자연스럽게 반영하십시오.\n"
        "인식 상태 구조 자체를 설명하거나 나열하지 마십시오.\n"
        "확실하지 않거나 모르는 게 있으면 얼버무리지 않고, 모른다고 솔직하게 답하십시오.\n\n"
        f"[핵심 키워드]\n{key_text}\n\n"
        f"[참고 개념]\n{ref_text}\n\n"
        f"[근거 연결]\n{edge_text}\n\n"
        f"[검색 컨텍스트]\n{search_text}"
    )

    print("\n" + "─" * 60)
    print("[GraphToLang system]")
    print(system_msg)
    print("─" * 30)
    print("[GraphToLang user]")
    print(user_msg)
    print("─" * 60 + "\n")

    return await llm_chat(system_msg, user_msg, model=conclusion.model)


# ── 목표 노드 ─────────────────────────────────────────────────────────────────

def _get_or_create_goal_node(conn: sqlite3.Connection) -> Node:
    """세계그래프에서 목표 노드를 로드하거나 최초 생성한다."""
    import hashlib
    from datetime import datetime, timezone

    goal_hash = hashlib.sha256(b"goal::machi_ai_intent").hexdigest()[:32]
    node = db_get_node(conn, goal_hash)
    if node is not None:
        return node

    now = datetime.now(timezone.utc)
    goal_node = Node(
        address_hash=goal_hash,
        node_kind="goal",
        formation_source="ingest",
        labels=["목표", "AI_intent"],
        is_abstract=False,
        trust_score=1.0,
        stability_score=1.0,
        is_active=True,
        embedding=None,
        payload={},
        created_at=now,
        updated_at=now,
    )
    insert_node(conn, goal_node)
    conn.commit()
    return goal_node


# ── 파이프라인 ────────────────────────────────────────────────────────────────

@dataclass
class PipelineResult:
    response_text: str
    conclusion: ConclusionView


class Pipeline:
    """MK6 전체 파이프라인.

    사용 예:
        pipeline = Pipeline()
        result = await pipeline.run("사과는 과일이야")
        print(result.response_text)
    """

    def __init__(self, db_path: str | None = None) -> None:
        self._conn = open_db(db_path or config.DB_PATH)
        self._goal_node = _get_or_create_goal_node(self._conn)

    async def run(self, user_input: str, model: str | None = None) -> PipelineResult:
        """사용자 입력을 처리하고 언어 출력을 반환한다.

        Args:
            user_input: 사용자 메시지 (파일 내용 포함 가능)
            model:      사용할 생성 모델 (None이면 config.OLLAMA_MODEL_NAME)
        """
        _p0 = time.perf_counter()

        # 1. 언어 → 그래프 번역
        translated = await lang_to_graph(user_input, self._conn, get_embedding)
        _p1 = time.perf_counter()
        print(f"[pipeline] lang_to_graph: {_p1 - _p0:.3f}s")

        # 2. Think 루프
        engine = ThoughtEngine(
            conn=self._conn,
            embed_fn=get_embedding,
            search_fn=_search,
            goal_node=self._goal_node,
        )
        conclusion = await engine.think(translated, model=model, user_input=user_input)
        _p2 = time.perf_counter()
        print(f"[pipeline] think: {_p2 - _p1:.3f}s")

        # 3. 그래프 → 언어
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
