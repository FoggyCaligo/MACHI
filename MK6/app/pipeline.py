"""MK6 메인 파이프라인.

언어입력 → LangToGraph → TempThoughtGraph → Think 루프
  → ConclusionView → GraphToLang → 언어출력
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from ..core.entities.node import Node
from ..core.storage.db import open_db
from ..core.storage.world_graph import get_node as db_get_node, insert_node
from ..core.translation.lang_to_graph import translate as lang_to_graph
from ..core.thinking.thought_engine import ThoughtEngine, ConclusionView
from ..tools.ollama_client import get_embedding, generate
from ..tools.search_client import search as _search
from .. import config


# ── GraphToLang ───────────────────────────────────────────────────────────────

async def graph_to_lang(conclusion: ConclusionView) -> str:
    """ConclusionView를 자연어로 변환한다.

    사용자 입력과 인지 그래프 구조를 함께 LLM에 전달한다.
    레이블 없는 추상 노드는 이웃 노드의 레이블과 엣지 관계로 간접 표현한다.
    """
    # ── 구조 직렬화 ───────────────────────────────────────────────────────────
    def _trust_label(t: float) -> str:
        if t >= 0.7:
            return "확실"
        if t >= 0.3:
            return "보통"
        return "불확실"

    node_lines: list[str] = []
    for node in conclusion.nodes:
        if node.address_hash == conclusion.goal_hash:
            continue
        if node.labels:
            label_str = node.labels[0]
        else:
            # 추상 노드: 이웃 노드 레이블로 간접 표현
            neighbor_hashes = {
                e.target_hash if e.source_hash == node.address_hash else e.source_hash
                for e in conclusion.edges
                if e.source_hash == node.address_hash or e.target_hash == node.address_hash
            }
            neighbor_labels = []
            for h in neighbor_hashes:
                neighbor = next((n for n in conclusion.nodes if n.address_hash == h), None)
                if neighbor and neighbor.labels:
                    neighbor_labels.append(neighbor.labels[0])
            if not neighbor_labels:
                continue
            label_str = f"[{', '.join(neighbor_labels)}의 공통 개념]"
        node_lines.append(f"  - {label_str} (신뢰도: {_trust_label(node.trust_score)})")

    edge_lines: list[str] = []
    node_map = {n.address_hash: n for n in conclusion.nodes}
    for edge in conclusion.edges:
        if edge.is_temporary:
            continue
        src = node_map.get(edge.source_hash)
        tgt = node_map.get(edge.target_hash)
        src_str = src.labels[0] if src and src.labels else edge.source_hash[:8]
        tgt_str = tgt.labels[0] if tgt and tgt.labels else edge.target_hash[:8]
        edge_lines.append(f"  - {src_str} --[{edge.connect_type}]--> {tgt_str}")

    nodes_text = "\n".join(node_lines) or "  (없음)"
    edges_text = "\n".join(edge_lines) or "  (없음)"

    user_msg = conclusion.user_input or ""

    prompt = (
        "아래는 다음 사용자 입력에 대해 인지 그래프 위에서 사고 과정을 거친 결론입니다.\n"
        "이 결론을 기준으로 사용자 입력에 자연스러운 한국어로 응답해 주세요.\n"
        "신뢰도가 '불확실'인 개념은 단정하지 말고 조심스럽게 표현하세요.\n"
        "구조 자체를 설명하거나 나열하지 마세요.\n\n"
        f"[사용자 입력]\n{user_msg}\n\n"
        f"[결론 — 인식된 개념]\n{nodes_text}\n\n"
        f"[결론 — 개념 간 관계]\n{edges_text}\n\n"
        "응답:"
    )
    return await generate(prompt, model=conclusion.model)


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
        # 1. 언어 → 그래프 번역
        translated = await lang_to_graph(user_input, self._conn, get_embedding)

        # 2. Think 루프
        engine = ThoughtEngine(
            conn=self._conn,
            embed_fn=get_embedding,
            search_fn=_search,
            lang_to_graph_fn=lang_to_graph,
            goal_node=self._goal_node,
        )
        conclusion = await engine.think(translated, model=model, user_input=user_input)

        # 3. 그래프 → 언어
        response_text = await graph_to_lang(conclusion)

        return PipelineResult(
            response_text=response_text,
            conclusion=conclusion,
        )

    def close(self) -> None:
        self._conn.close()

    async def __aenter__(self) -> "Pipeline":
        return self

    async def __aexit__(self, *_: object) -> None:
        self.close()
