from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from config import EMBEDDING_MODEL_NAME, EMBEDDING_TIMEOUT_SECONDS, SCOPE_GATE_SIMILARITY_THRESHOLD
from core.entities.thought_view import ThoughtView
from tools.ollama_client import OllamaClient, OllamaClientError


class SearchScopeGateError(RuntimeError):
    pass


@dataclass(slots=True)
class SearchScopeGateDecision:
    needs_external_search: bool
    scope: str
    reason: str
    confidence: str = ''
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_metadata(self) -> dict[str, Any]:
        return {
            'needs_external_search': self.needs_external_search,
            'scope': self.scope,
            'reason': self.reason,
            'confidence': self.confidence,
            **self.metadata,
        }


@dataclass(slots=True)
class SearchScopeGate:
    """임베딩+코사인 유사도 기반 검색 범위 판정.

    사용자 쿼리와 활성 그래프 노드 텍스트의 코사인 유사도 최댓값을 기준으로
    외부 검색 필요 여부를 판단한다. LLM 호출 없음.
    """

    client: OllamaClient | None = None
    embedding_model: str = EMBEDDING_MODEL_NAME
    similarity_threshold: float = SCOPE_GATE_SIMILARITY_THRESHOLD
    max_nodes: int = 30

    def __post_init__(self) -> None:
        if self.client is None:
            self.client = OllamaClient(timeout_seconds=EMBEDDING_TIMEOUT_SECONDS)

    def decide(
        self,
        *,
        message: str,
        thought_view: ThoughtView,
    ) -> SearchScopeGateDecision:
        if not self.embedding_model:
            raise SearchScopeGateError('EMBEDDING_MODEL_NAME is not configured')

        node_texts = self._collect_node_texts(thought_view)
        if not node_texts:
            return SearchScopeGateDecision(
                needs_external_search=True,
                scope='world_grounding',
                reason='활성 노드가 없어 그래프에서 답변을 구성할 수 없다.',
                confidence='high',
                metadata={'max_similarity': 0.0, 'node_count': 0, 'threshold': self.similarity_threshold},
            )

        try:
            result = self.client.embed(
                model_name=self.embedding_model,
                input_texts=[message] + node_texts[: self.max_nodes],
            )
        except OllamaClientError as exc:
            raise SearchScopeGateError(str(exc)) from exc

        if len(result.embeddings) < 2:
            raise SearchScopeGateError('embedding returned insufficient vectors')

        query_vec = result.embeddings[0]
        node_vecs = result.embeddings[1:]

        max_sim = max(self._cosine(query_vec, nv) for nv in node_vecs)
        needs_external = max_sim < self.similarity_threshold
        scope = 'world_grounding' if needs_external else 'local_graph_only'
        reason = (
            f'쿼리-그래프 최대 코사인 유사도 {max_sim:.3f} < 임계치 {self.similarity_threshold} → 외부 근거 필요.'
            if needs_external
            else f'쿼리-그래프 최대 코사인 유사도 {max_sim:.3f} ≥ 임계치 {self.similarity_threshold} → 그래프 내 답변 가능.'
        )

        return SearchScopeGateDecision(
            needs_external_search=needs_external,
            scope=scope,
            reason=reason,
            confidence='high',
            metadata={
                'max_similarity': round(max_sim, 4),
                'node_count': len(node_vecs),
                'threshold': self.similarity_threshold,
            },
        )

    def _collect_node_texts(self, thought_view: ThoughtView) -> list[str]:
        texts: list[str] = []
        for node in thought_view.nodes:
            if not node.is_active:
                continue
            text = (
                getattr(node, 'normalized_value', '') or getattr(node, 'raw_value', '') or ''
            ).strip()
            if text and text not in texts:
                texts.append(text)
        return texts

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        mag_a = math.sqrt(sum(x * x for x in a))
        mag_b = math.sqrt(sum(x * x for x in b))
        if mag_a == 0.0 or mag_b == 0.0:
            return 0.0
        return dot / (mag_a * mag_b)
