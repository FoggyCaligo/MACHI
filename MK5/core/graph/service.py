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
                self._repo.upsert_node(GraphNode(
                    node_id=node_id,
                    labels=labels,
                    node_type="anchor",
                    provenance="system_policy",
                    trust_score=1.0,
                    stability_score=1.0,
                ))

    def ensure_user_anchor(self, user_id: str) -> str:
        anchor_id = user_anchor_id(user_id)
        if self._repo.get_node(anchor_id) is None:
            self._repo.upsert_node(
                GraphNode(
                    node_id=anchor_id,
                    labels=[user_id],
                    node_type="anchor",
                    payload={"user_id": user_id},
                    provenance="system_policy",
                    trust_score=1.0,
                    stability_score=1.0,
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
                    provenance="user_utterance",
                    trust_score=1.0,
                    stability_score=0.8,
                )
            )
            self._repo.add_edge(
                GraphEdge(
                    source_id=anchor_id,
                    target_id=utterance_id,
                    relation="spoke",
                    payload={"session_id": session_id},
                    provenance="user_utterance",
                    trust_score=1.0,
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
                        provenance="user_assertion",
                        trust_score=0.75,
                        stability_score=0.5,
                    )
                )
            self._repo.add_edge(
                GraphEdge(
                    source_id=anchor_id,
                    target_id=node_id,
                    relation="asserted_fact",
                    payload={"session_id": session_id},
                    provenance="user_assertion",
                    trust_score=0.8,
                )
            )
            self._repo.add_edge(
                GraphEdge(
                    source_id=utterance_id,
                    target_id=node_id,
                    relation="derived_fact",
                    payload={"session_id": session_id},
                    provenance="derived_from_utterance",
                    trust_score=0.7,
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
                    provenance="search",
                    trust_score=0.7,
                )
            )
        self._repo.add_edge(
            GraphEdge(
                source_id=SEARCH_ANCHOR_ID,
                target_id=query_node_id,
                relation="issued_search",
                payload={},
                provenance="search",
                trust_score=0.8,
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
                        provenance="search",
                        trust_score=0.65,
                    )
                )
            self._repo.add_edge(
                GraphEdge(
                    source_id=query_node_id,
                    target_id=result_node_id,
                    relation="returned_result",
                    payload={"source": source},
                    provenance="search",
                    trust_score=0.7,
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
                            provenance="search",
                            trust_score=0.6,
                        )
                    )
                self._repo.add_edge(
                    GraphEdge(
                        source_id=result_node_id,
                        target_id=fact_id,
                        relation="supports_fact",
                        payload={"source": source},
                        provenance="search",
                        trust_score=0.65,
                    )
                )
                recorded.append(fact_id)
        return recorded

    def user_memory_summary(self, user_id: str, *, query: str = "", limit: int = 5) -> list[str]:
        anchor_id = self.ensure_user_anchor(user_id)
        terms = {term.lower() for term in re.findall(r"\w+", query) if len(term) >= 2}
        ranked: list[tuple[float, str]] = []
        for node in self._repo.neighbors(anchor_id):
            if not node.labels or not node.is_active:
                continue
            if node.payload.get("suppress_from_summary"):
                continue
            if node.node_type not in {"fact", "utterance"}:
                continue
            label = node.labels[0]
            label_terms = {term.lower() for term in re.findall(r"\w+", label)}
            relevance = len(terms.intersection(label_terms)) / max(1, len(terms)) if terms else 0.0
            type_bonus = 1.0 if node.node_type == "fact" else 0.25
            score = relevance * 4.0 + type_bonus + node.trust_score + node.stability_score
            ranked.append((score, self._format_user_memory_for_model(user_id=user_id, node=node, label=label)))
        ranked.sort(key=lambda item: (-item[0], item[1]))
        return [label for _, label in ranked[:limit]]

    def _format_user_memory_for_model(self, *, user_id: str, node: GraphNode, label: str) -> str:
        if node.node_type == "fact":
            return (
                f'사용자({user_id})에 대한 기억: "{label}" '
                "이 문장의 1인칭 표현은 assistant가 아니라 사용자에게 귀속됩니다."
            )
        return (
            f'사용자({user_id})가 이전에 말한 발화: "{label}" '
            "이 발화의 speaker는 사용자이며 assistant의 자기소개가 아닙니다."
        )

    def search_concept_nodes_for_utterance(
        self,
        *,
        user_id: str,
        utterance_id: str,
        limit: int = 4,
    ) -> list[str]:
        _ = self.ensure_user_anchor(user_id)
        utterance = self._repo.get_node(utterance_id)
        if utterance is None or utterance.node_type != "utterance":
            return []
        if str(utterance.payload.get("user_id") or "") != user_id:
            return []

        candidates: list[tuple[float, str]] = []
        seen: set[str] = set()
        for edge in self._repo.edges_for_node(utterance_id):
            if not edge.is_active or edge.relation != "user_mentions_concept":
                continue
            concept_id = edge.target_id if edge.source_id == utterance_id else edge.source_id
            concept = self._repo.get_node(concept_id)
            if concept is None or concept.node_type != "concept" or not concept.is_active:
                continue
            label = str(concept.payload.get("normalized") or (concept.labels[0] if concept.labels else "")).strip()
            if len(label) < 2 or label in seen:
                continue
            seen.add(label)
            support = sum(
                linked.support_count
                for linked in self._repo.edges_for_node(concept.node_id)
                if linked.is_active and linked.relation.endswith("_references_concept")
            )
            token_index = edge.payload.get("token_index")
            position_bonus = 1.0 / (1.0 + float(token_index)) if isinstance(token_index, int) else 0.0
            score = concept.trust_score + concept.stability_score + support * 0.1 + position_bonus
            candidates.append((score, label))

        candidates.sort(key=lambda item: (-item[0], item[1]))
        return [label for _, label in candidates[:limit]]

    def should_search_without_slots(self, *, user_id: str, utterance_id: str) -> bool:
        search_nodes = self.search_concept_nodes_for_utterance(
            user_id=user_id,
            utterance_id=utterance_id,
        )
        if not search_nodes:
            return False
        for label in search_nodes:
            concept = self._repo.get_node(concept_node_id(label))
            if concept is not None and self._has_search_support(concept.node_id):
                return False
        return True

    def _has_search_support(self, node_id: str) -> bool:
        for edge in self._repo.edges_for_node(node_id):
            if not edge.is_active:
                continue
            if edge.provenance == "search" or edge.relation.startswith("search_"):
                return True
            other_id = edge.target_id if edge.source_id == node_id else edge.source_id
            other = self._repo.get_node(other_id)
            if other is None:
                continue
            if other.provenance == "search" or other.node_type.startswith("search_"):
                return True
        return False

    def record_fact_correction(
        self,
        *,
        user_id: str,
        previous_fact_id: str,
        replacement_text: str,
        session_id: str | None = None,
    ) -> str:
        """Replace a user fact while preserving both provenance and history.

        MK5 intentionally does not guess corrections from cue strings. The planner
        calls this explicit operation after it has identified the previous fact.
        """
        anchor_id = self.ensure_user_anchor(user_id)
        previous = self._repo.get_node(previous_fact_id)
        if previous is None or previous.node_type != "fact":
            raise ValueError("previous_fact_id must identify an existing fact")
        if str(previous.payload.get("user_id") or "") != user_id:
            raise ValueError("cannot correct another user's fact")

        replacement = replacement_text.strip()
        if not replacement:
            raise ValueError("replacement_text must not be empty")
        replacement_id = fact_node_id(user_id, replacement, namespace="fact")
        self._repo.upsert_node(GraphNode(
            node_id=replacement_id,
            labels=[replacement],
            node_type="fact",
            payload={
                "user_id": user_id,
                "session_id": session_id,
                "source": "user_correction",
                "replaces": previous_fact_id,
            },
            provenance="user_correction",
            trust_score=0.95,
            stability_score=0.75,
        ))
        self._repo.add_edge(GraphEdge(
            source_id=anchor_id,
            target_id=replacement_id,
            relation="asserted_fact",
            payload={"session_id": session_id, "correction": True},
            provenance="user_correction",
            trust_score=0.95,
        ))
        self._repo.add_edge(GraphEdge(
            source_id=replacement_id,
            target_id=previous_fact_id,
            relation="replaces",
            payload={"session_id": session_id},
            provenance="user_correction",
            trust_score=1.0,
            conflict_count=1,
        ))
        previous.payload["superseded_by"] = replacement_id
        previous.payload["status"] = "superseded"
        previous.is_active = False
        previous.trust_score = min(previous.trust_score, 0.2)
        self._repo.upsert_node(previous)
        # Keep the original utterance for audit/provenance, but do not feed a
        # sentence known to contain the superseded fact back into the LLM summary.
        for edge in self._repo.edges_for_node(previous_fact_id):
            if edge.relation != "derived_fact" or edge.target_id != previous_fact_id:
                continue
            utterance = self._repo.get_node(edge.source_id)
            if utterance is None or utterance.node_type != "utterance":
                continue
            utterance.payload["suppress_from_summary"] = True
            utterance.payload["superseded_fact_id"] = previous_fact_id
            self._repo.upsert_node(utterance)
        return replacement_id

    def graph_search(self, *, user_id: str, query: str, limit: int = 8) -> list[dict]:
        _ = self.ensure_user_anchor(user_id)
        if not query.strip():
            return []
        results: list[dict] = []
        anchor_id = self.ensure_user_anchor(user_id)
        user_reachable = {node.node_id for node in self._repo.neighbors(anchor_id)} | {anchor_id}
        candidates = self._repo.search_nodes(query, limit=max(limit * 4, limit))
        for node in candidates:
            if len(results) >= limit:
                break
            owner = str(node.payload.get("user_id") or "")
            is_external = node.provenance == "search" or node.node_type.startswith("search_")
            if owner and owner != user_id:
                continue
            if not is_external and node.node_id not in user_reachable and node.node_type != "concept":
                continue
            neighbors = []
            for edge in self._repo.edges_for_node(node.node_id)[:6]:
                if not edge.is_active:
                    continue
                other_id = edge.target_id if edge.source_id == node.node_id else edge.source_id
                other_node = self._repo.get_node(other_id)
                if other_node is None or not other_node.is_active:
                    continue
                other_owner = str(other_node.payload.get("user_id") or "")
                if other_owner and other_owner != user_id:
                    continue
                neighbors.append(
                    {
                        "node_id": other_node.node_id,
                        "labels": list(other_node.labels),
                        "node_type": other_node.node_type,
                        "relation": edge.relation,
                        "direction": "outgoing" if edge.source_id == node.node_id else "incoming",
                        "provenance": edge.provenance,
                        "support_count": edge.support_count,
                        "trust_score": edge.trust_score,
                    }
                )
            results.append(
                {
                    "node_id": node.node_id,
                    "labels": list(node.labels),
                    "node_type": node.node_type,
                    "payload": dict(node.payload),
                    "provenance": node.provenance,
                    "trust_score": node.trust_score,
                    "stability_score": node.stability_score,
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
                    provenance="user_utterance" if edge_prefix == "user" else "search",
                    trust_score=0.75 if edge_prefix == "user" else 0.6,
                )
            )
            self._repo.add_edge(
                GraphEdge(
                    source_id=owner_anchor_id,
                    target_id=node_id,
                    relation=f"{edge_prefix}_references_concept",
                    payload={**payload, "normalized": span.normalized},
                    provenance="user_utterance" if edge_prefix == "user" else "search",
                    trust_score=0.7 if edge_prefix == "user" else 0.6,
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
                        provenance="user_utterance" if edge_prefix == "user" else "search",
                        trust_score=0.65,
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
                    provenance="ingest",
                    trust_score=0.5,
                    stability_score=0.4,
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
