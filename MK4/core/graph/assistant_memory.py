from __future__ import annotations

from .anchors import ASSISTANT_ANCHOR_ID, concept_node_id, user_anchor_id, utterance_node_id
from .models import GraphEdge, GraphNode
from .repository import GraphRepository
from .text_graph import tokenize_spans


_ASSISTANT_TEXT_GRAPH_VERSION = 1


class AssistantMemoryRecorder:
    """Persist assistant-visible replies as user-scoped graph memory.

    Assistant replies remain distinguishable from user utterances through provenance
    and edge relations, while using the existing utterance node type so the current
    summary/search ranking code can retrieve them after a process restart.
    """

    def __init__(self, repo: GraphRepository) -> None:
        self._repo = repo

    def record(
        self,
        *,
        user_id: str,
        text: str,
        session_id: str | None,
    ) -> str | None:
        cleaned_text = text.strip()
        if not cleaned_text:
            return None

        anchor_id = user_anchor_id(user_id)
        if self._repo.get_node(anchor_id) is None:
            raise ValueError("user anchor must exist before recording assistant memory")
        if self._repo.get_node(ASSISTANT_ANCHOR_ID) is None:
            raise ValueError("assistant anchor must exist before recording assistant memory")

        node_id = utterance_node_id(f"assistant::{user_id}", cleaned_text, session_id)
        existing = self._repo.get_node(node_id)
        if existing is None:
            self._repo.upsert_node(GraphNode(
                node_id=node_id,
                labels=[cleaned_text],
                node_type="utterance",
                payload={
                    "user_id": user_id,
                    "session_id": session_id,
                    "speaker": "assistant",
                    "source": "assistant_response",
                    "text_graph_version": _ASSISTANT_TEXT_GRAPH_VERSION,
                },
                provenance="assistant_utterance",
                trust_score=0.9,
                stability_score=0.7,
            ))

        edge_payload = {
            "user_id": user_id,
            "session_id": session_id,
            "speaker": "assistant",
        }
        self._repo.add_edge(GraphEdge(
            source_id=ASSISTANT_ANCHOR_ID,
            target_id=node_id,
            relation="spoke",
            payload=edge_payload,
            provenance="assistant_utterance",
            trust_score=1.0,
        ))
        self._repo.add_edge(GraphEdge(
            source_id=anchor_id,
            target_id=node_id,
            relation="received_response",
            payload=edge_payload,
            provenance="assistant_utterance",
            trust_score=1.0,
        ))

        if existing is None:
            self._graphize(
                user_id=user_id,
                node_id=node_id,
                text=cleaned_text,
                session_id=session_id,
            )
        return node_id

    def _graphize(
        self,
        *,
        user_id: str,
        node_id: str,
        text: str,
        session_id: str | None,
    ) -> None:
        sentence_concepts: dict[int, list[str]] = {}
        for span in tokenize_spans(text):
            concept_id = concept_node_id(span.normalized)
            if self._repo.get_node(concept_id) is None:
                self._repo.upsert_node(GraphNode(
                    node_id=concept_id,
                    labels=[span.token, span.normalized],
                    node_type="concept",
                    payload={"normalized": span.normalized},
                    provenance="ingest",
                    trust_score=0.5,
                    stability_score=0.4,
                ))
            payload = {
                "user_id": user_id,
                "session_id": session_id,
                "speaker": "assistant",
                "token": span.token,
                "normalized": span.normalized,
                "sentence_index": span.sentence_index,
                "token_index": span.token_index,
            }
            self._repo.add_edge(GraphEdge(
                source_id=node_id,
                target_id=concept_id,
                relation="assistant_mentions_concept",
                payload=payload,
                provenance="assistant_utterance",
                trust_score=0.75,
            ))
            sentence_concepts.setdefault(span.sentence_index, []).append(concept_id)

        for concept_ids in sentence_concepts.values():
            for left, right in zip(concept_ids, concept_ids[1:]):
                if left == right:
                    continue
                self._repo.add_edge(GraphEdge(
                    source_id=left,
                    target_id=right,
                    relation="assistant_adjacent_concept",
                    payload={
                        "user_id": user_id,
                        "session_id": session_id,
                        "speaker": "assistant",
                    },
                    provenance="assistant_utterance",
                    trust_score=0.65,
                ))
