from __future__ import annotations

import re

from .anchors import (
    ASSISTANT_ANCHOR_ID,
    SEARCH_ANCHOR_ID,
    concept_node_id,
    fact_node_id,
    search_query_node_id,
    search_result_node_id,
    user_anchor_id,
    utterance_node_id,
)
from .models import GraphEdge, GraphNode
from .repository import GraphRepository
from .text_graph import TokenSpan, tokenize_spans


class GraphMemoryService:
    def __init__(self, repo: GraphRepository) -> None:
        self._repo = repo
        self._ensure_shared_anchors()

    def _ensure_shared_anchors(self) -> None:
        for node_id, labels in (
            (ASSISTANT_ANCHOR_ID, ["AI", "assistant"]),
            (SEARCH_ANCHOR_ID, ["external", "search"]),
        ):
            if self._repo.get_node(node_id) is None:
                self._repo.upsert_node(GraphNode(node_id=node_id, labels=labels, node_type="anchor"))

    def ensure_user_anchor(self, user_id: str) -> str:
        anchor_id = user_anchor_id(user_id)
        if self._repo.get_node(anchor_id) is None:
            self._repo.upsert_node(
                GraphNode(
                    node_id=anchor_id,
                    labels=[user_id],
                    node_type="anchor",
                    payload={"user_id": user_id},
                )
            )
        return anchor_id

    def record_user_utterance(self, *, user_id: str, text: str, session_id: str | None) -> str:
        anchor_id = self.ensure_user_anchor(user_id)
        utterance_id = utterance_node_id(user_id, text, session_id)
        is_new_utterance = self._repo.get_node(utterance_id) is None
        if is_new_utterance:
            self._repo.upsert_node(
                GraphNode(
                    node_id=utterance_id,
                    labels=[text],
                    node_type="utterance",
                    payload={"user_id": user_id, "session_id": session_id},
                )
            )
            self._repo.add_edge(
                GraphEdge(
                    source_id=anchor_id,
                    target_id=utterance_id,
                    relation="spoke",
                    payload={"session_id": session_id},
                )
            )
            self._graphize_text(
                owner_anchor_id=anchor_id,
                carrier_node_id=utterance_id,
                text=text,
                edge_prefix="user",
                payload={"user_id": user_id, "session_id": session_id},
            )
        self.record_user_facts(
            user_id=user_id,
            text=text,
            session_id=session_id,
            utterance_id=utterance_id,
        )
        return utterance_id

    def record_user_facts(
        self,
        *,
        user_id: str,
        text: str,
        session_id: str | None,
        utterance_id: str,
    ) -> list[str]:
        anchor_id = self.ensure_user_anchor(user_id)
        fact_ids: list[str] = []
        for fact_text in self._extract_fact_candidates(text):
            node_id = fact_node_id(user_id, fact_text, namespace="fact")
            if self._repo.get_node(node_id) is None:
                self._repo.upsert_node(
                    GraphNode(
                        node_id=node_id,
                        labels=[fact_text],
                        node_type="fact",
                        payload={
                            "user_id": user_id,
                            "session_id": session_id,
                            "source": "user_utterance",
                        },
                    )
                )
            self._repo.add_edge(
                GraphEdge(
                    source_id=anchor_id,
                    target_id=node_id,
                    relation="asserted_fact",
                    payload={"session_id": session_id},
                )
            )
            self._repo.add_edge(
                GraphEdge(
                    source_id=utterance_id,
                    target_id=node_id,
                    relation="derived_fact",
                    payload={"session_id": session_id},
                )
            )
            fact_ids.append(node_id)
        return fact_ids

    def record_search_results(self, *, query: str, results: list[dict]) -> list[str]:
        query_text = query.strip()
        if not query_text or not results:
            return []

        query_node_id = search_query_node_id(query_text)
        if self._repo.get_node(query_node_id) is None:
            self._repo.upsert_node(
                GraphNode(
                    node_id=query_node_id,
                    labels=[query_text],
                    node_type="search_query",
                    payload={"query": query_text},
                )
            )
        self._repo.add_edge(
            GraphEdge(
                source_id=SEARCH_ANCHOR_ID,
                target_id=query_node_id,
                relation="issued_search",
                payload={},
            )
        )

        recorded: list[str] = []
        for item in results:
            title = str(item.get("title") or "").strip()
            url = str(item.get("url") or "").strip()
            snippet = str(item.get("snippet") or "").strip()
            source = str(item.get("source") or "").strip() or "unknown"
            if not title and not url:
                continue

            result_node_id = search_result_node_id(query_text, title, url)
            if self._repo.get_node(result_node_id) is None:
                self._repo.upsert_node(
                    GraphNode(
                        node_id=result_node_id,
                        labels=[title or url],
                        node_type="search_result",
                        payload={
                            "query": query_text,
                            "title": title,
                            "url": url,
                            "snippet": snippet,
                            "source": source,
                        },
                    )
                )
            self._repo.add_edge(
                GraphEdge(
                    source_id=query_node_id,
                    target_id=result_node_id,
                    relation="returned_result",
                    payload={"source": source},
                )
            )
            recorded.append(result_node_id)
            self._graphize_text(
                owner_anchor_id=SEARCH_ANCHOR_ID,
                carrier_node_id=result_node_id,
                text="\n".join(part for part in [title, snippet] if part),
                edge_prefix="search",
                payload={
                    "query": query_text,
                    "title": title,
                    "url": url,
                    "source": source,
                },
            )

            for fact_text in self._extract_fact_candidates(snippet):
                fact_id = fact_node_id(url or title or query_text, fact_text, namespace="search_fact")
                if self._repo.get_node(fact_id) is None:
                    self._repo.upsert_node(
                        GraphNode(
                            node_id=fact_id,
                            labels=[fact_text],
                            node_type="search_fact",
                            payload={
                                "query": query_text,
                                "title": title,
                                "url": url,
                                "source": source,
                            },
                        )
                    )
                self._repo.add_edge(
                    GraphEdge(
                        source_id=result_node_id,
                        target_id=fact_id,
                        relation="supports_fact",
                        payload={"source": source},
                    )
                )
                recorded.append(fact_id)
        return recorded

    def user_memory_summary(self, user_id: str, *, limit: int = 5) -> list[str]:
        anchor_id = self.ensure_user_anchor(user_id)
        fact_labels: list[str] = []
        utterance_labels: list[str] = []
        for node in self._repo.neighbors(anchor_id):
            if not node.labels:
                continue
            if node.node_type == "fact":
                fact_labels.append(node.labels[0])
            elif node.node_type == "utterance":
                utterance_labels.append(node.labels[0])
        return (fact_labels + utterance_labels)[:limit]

    def graph_search(self, *, user_id: str, query: str, limit: int = 8) -> list[dict]:
        _ = self.ensure_user_anchor(user_id)
        if not query.strip():
            return []
        results: list[dict] = []
        for node in self._repo.search_nodes(query, limit=limit):
            neighbors = []
            for edge in self._repo.edges_for_node(node.node_id)[:6]:
                other_id = edge.target_id if edge.source_id == node.node_id else edge.source_id
                other_node = self._repo.get_node(other_id)
                if other_node is None:
                    continue
                neighbors.append(
                    {
                        "node_id": other_node.node_id,
                        "labels": list(other_node.labels),
                        "node_type": other_node.node_type,
                        "relation": edge.relation,
                        "direction": "outgoing" if edge.source_id == node.node_id else "incoming",
                    }
                )
            results.append(
                {
                    "node_id": node.node_id,
                    "labels": list(node.labels),
                    "node_type": node.node_type,
                    "payload": dict(node.payload),
                    "neighbors": neighbors,
                }
            )
        return results

    def _extract_fact_candidates(self, text: str) -> list[str]:
        normalized = re.sub(r"\s+", " ", text.strip())
        if not normalized:
            return []

        parts = re.split(r"[\n\r]+|(?<=[.!?。！？])\s+", normalized)
        facts: list[str] = []
        seen: set[str] = set()
        for part in parts:
            candidate = part.strip(" \t\"'[]()")
            if len(candidate) < 6:
                continue
            if candidate.endswith("?"):
                continue
            lowered = candidate.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            facts.append(candidate)
        return facts

    def _graphize_text(
        self,
        *,
        owner_anchor_id: str,
        carrier_node_id: str,
        text: str,
        edge_prefix: str,
        payload: dict,
    ) -> list[str]:
        spans = tokenize_spans(text)
        if not spans:
            return []

        concept_ids: list[str] = []
        sentence_concepts: dict[int, list[str]] = {}
        for span in spans:
            node_id = self._ensure_concept_node(span)
            self._repo.add_edge(
                GraphEdge(
                    source_id=carrier_node_id,
                    target_id=node_id,
                    relation=f"{edge_prefix}_mentions_concept",
                    payload={
                        **payload,
                        "token": span.token,
                        "normalized": span.normalized,
                        "sentence_index": span.sentence_index,
                        "token_index": span.token_index,
                    },
                )
            )
            self._repo.add_edge(
                GraphEdge(
                    source_id=owner_anchor_id,
                    target_id=node_id,
                    relation=f"{edge_prefix}_references_concept",
                    payload={**payload, "normalized": span.normalized},
                )
            )
            concept_ids.append(node_id)
            sentence_concepts.setdefault(span.sentence_index, []).append(node_id)

        for concept_list in sentence_concepts.values():
            for left, right in zip(concept_list, concept_list[1:]):
                if left == right:
                    continue
                self._repo.add_edge(
                    GraphEdge(
                        source_id=left,
                        target_id=right,
                        relation=f"{edge_prefix}_adjacent_concept",
                        payload=payload,
                    )
                )
        return concept_ids

    def _ensure_concept_node(self, span: TokenSpan) -> str:
        node_id = concept_node_id(span.normalized)
        if self._repo.get_node(node_id) is None:
            self._repo.upsert_node(
                GraphNode(
                    node_id=node_id,
                    labels=[span.token, span.normalized],
                    node_type="concept",
                    payload={"normalized": span.normalized},
                )
            )
        return node_id

    def _ensure_normalized_concept(self, normalized: str) -> str:
        node_id = concept_node_id(normalized)
        if self._repo.get_node(node_id) is None:
            self._repo.upsert_node(
                GraphNode(
                    node_id=node_id,
                    labels=[normalized],
                    node_type="concept",
                    payload={"normalized": normalized},
                )
            )
        return node_id
