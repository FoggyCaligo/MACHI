from __future__ import annotations

import re
from typing import Any

from .anchors import fact_node_id, utterance_node_id, user_anchor_id
from .models import GraphEdge, GraphNode
from .service import GraphMemoryService, _TEXT_GRAPH_VERSION


_SEMANTIC_NODE_TYPE = "semantic_memory"
_SEMANTIC_ENTITY_TYPE = "semantic_entity"


class ModelManagedGraphMemoryService(GraphMemoryService):
    """Keep raw conversation automatic while making semantic memory model-managed."""

    def record_user_utterance(self, *, user_id: str, text: str, session_id: str | None) -> str:
        anchor_id = self.ensure_user_anchor(user_id)
        utterance_id = utterance_node_id(user_id, text, session_id)
        existing_utterance = self._repo.get_node(utterance_id)
        is_new_utterance = existing_utterance is None
        if is_new_utterance:
            self._repo.upsert_node(GraphNode(
                node_id=utterance_id,
                labels=[text],
                node_type="utterance",
                payload={
                    "user_id": user_id,
                    "session_id": session_id,
                    "text_graph_version": _TEXT_GRAPH_VERSION,
                },
                provenance="user_utterance",
                trust_score=1.0,
                stability_score=0.8,
            ))
            self._repo.add_edge(GraphEdge(
                source_id=anchor_id,
                target_id=utterance_id,
                relation="spoke",
                payload={"session_id": session_id},
                provenance="user_utterance",
                trust_score=1.0,
            ))
        needs_graph_refresh = (
            is_new_utterance
            or int((existing_utterance.payload if existing_utterance else {}).get("text_graph_version") or 0)
            < _TEXT_GRAPH_VERSION
        )
        if needs_graph_refresh:
            self._graphize_text(
                owner_anchor_id=anchor_id,
                carrier_node_id=utterance_id,
                text=text,
                edge_prefix="user",
                payload={
                    "user_id": user_id,
                    "session_id": session_id,
                    "text_graph_version": _TEXT_GRAPH_VERSION,
                },
            )
            if existing_utterance is not None:
                existing_utterance.payload["text_graph_version"] = _TEXT_GRAPH_VERSION
                self._repo.upsert_node(existing_utterance)
        return utterance_id

    def write_semantic_memory(
        self,
        *,
        user_id: str,
        subject: dict[str, Any],
        relation: str,
        object_: dict[str, Any],
    ) -> dict[str, Any]:
        anchor_id = self.ensure_user_anchor(user_id)
        source_id, source_label = self._resolve_memory_endpoint(user_id=user_id, endpoint=subject)
        target_id, target_label = self._resolve_memory_endpoint(user_id=user_id, endpoint=object_)
        normalized_relation = _normalize_relation(relation)
        assertion_key = f"{source_id}|{normalized_relation}|{target_id}"
        memory_id = fact_node_id(user_id, assertion_key, namespace="semantic_memory")
        memory_label = f"{source_label} --{normalized_relation}--> {target_label}"
        existing = self._repo.get_node(memory_id)
        if existing is None:
            self._repo.upsert_node(GraphNode(
                node_id=memory_id,
                labels=[memory_label],
                node_type=_SEMANTIC_NODE_TYPE,
                payload={
                    "user_id": user_id,
                    "subject_id": source_id,
                    "relation": normalized_relation,
                    "object_id": target_id,
                    "managed_by": "model",
                },
                provenance="model_memory",
                trust_score=0.8,
                stability_score=0.7,
            ))
        else:
            if existing.node_type != _SEMANTIC_NODE_TYPE:
                raise ValueError(f"semantic memory id collision: {memory_id}")
            existing.is_active = True
            existing.labels = [memory_label]
            self._repo.upsert_node(existing)

        self._repo.add_edge(GraphEdge(
            source_id=anchor_id,
            target_id=memory_id,
            relation="semantic_memory",
            payload={"user_id": user_id},
            provenance="model_memory",
            trust_score=0.85,
        ))
        self._repo.add_edge(GraphEdge(
            source_id=memory_id,
            target_id=source_id,
            relation="memory_subject",
            payload={"user_id": user_id},
            provenance="model_memory",
            trust_score=0.85,
        ))
        self._repo.add_edge(GraphEdge(
            source_id=memory_id,
            target_id=target_id,
            relation="memory_object",
            payload={"user_id": user_id, "relation": normalized_relation},
            provenance="model_memory",
            trust_score=0.85,
        ))
        support_count = 0
        for edge in self._repo.edges_for_node(memory_id):
            if edge.source_id == anchor_id and edge.target_id == memory_id and edge.relation == "semantic_memory":
                support_count = edge.support_count
                break
        return {
            "ok": True,
            "memory_node_id": memory_id,
            "subject_node_id": source_id,
            "relation": normalized_relation,
            "object_node_id": target_id,
            "support_count": support_count,
        }

    def revise_semantic_memory(
        self,
        *,
        user_id: str,
        memory_node_id: str,
        subject: dict[str, Any],
        relation: str,
        object_: dict[str, Any],
    ) -> dict[str, Any]:
        previous = self._repo.get_node(memory_node_id)
        if previous is None:
            raise ValueError(f"memory node not found: {memory_node_id}")
        if previous.node_type != _SEMANTIC_NODE_TYPE:
            raise ValueError(f"node is not model-managed semantic memory: {memory_node_id}")
        if str(previous.payload.get("user_id") or "") != user_id:
            raise ValueError("memory node does not belong to the current user")
        if not previous.is_active:
            raise ValueError(f"memory node is already inactive: {memory_node_id}")

        replacement = self.write_semantic_memory(
            user_id=user_id,
            subject=subject,
            relation=relation,
            object_=object_,
        )
        replacement_id = str(replacement["memory_node_id"])
        if replacement_id == memory_node_id:
            return {**replacement, "revised": False, "previous_memory_node_id": memory_node_id}

        previous.is_active = False
        previous.payload["superseded_by"] = replacement_id
        self._repo.upsert_node(previous)
        self._repo.add_edge(GraphEdge(
            source_id=memory_node_id,
            target_id=replacement_id,
            relation="superseded_by",
            payload={"user_id": user_id},
            provenance="model_memory_revision",
            trust_score=1.0,
        ))
        return {**replacement, "revised": True, "previous_memory_node_id": memory_node_id}

    def user_memory_summary(self, user_id: str, **kwargs: Any) -> list[dict]:
        limit = int(kwargs.get("limit", 5))
        base_limit = 0 if limit <= 0 else max(limit * 2, limit)
        base_items = super().user_memory_summary(user_id, **{**kwargs, "limit": base_limit})
        semantic_items = self._semantic_memory_items(
            user_id=user_id,
            query=str(kwargs.get("query") or ""),
            min_signal=float(kwargs.get("min_signal", 0.0)),
            exclude_node_ids=kwargs.get("exclude_node_ids") or set(),
        )
        combined = [*semantic_items, *base_items]
        return combined if limit <= 0 else combined[:limit]

    def _semantic_memory_items(
        self,
        *,
        user_id: str,
        query: str,
        min_signal: float,
        exclude_node_ids: set[str],
    ) -> list[dict]:
        anchor_id = self.ensure_user_anchor(user_id)
        terms = {term.casefold() for term in re.findall(r"\w+", query) if len(term) >= 2}
        ranked: list[tuple[float, dict[str, Any]]] = []
        for node in self._repo.neighbors(anchor_id):
            if node.node_id in exclude_node_ids or node.node_type != _SEMANTIC_NODE_TYPE or not node.is_active:
                continue
            label = node.labels[0] if node.labels else node.node_id
            label_terms = {term.casefold() for term in re.findall(r"\w+", label)}
            relevance = len(terms.intersection(label_terms)) / max(1, len(terms)) if terms else 0.0
            if terms and relevance < max(0.0, min_signal):
                continue
            score = 8.0 + relevance * 4.0 + node.trust_score + node.stability_score
            ranked.append((score, {
                "node_id": node.node_id,
                "node_type": node.node_type,
                "label": label,
                "raw_label": label,
                "subgraph": self._small_subgraph_summary(
                    user_id=user_id,
                    node=node,
                    relation_limit=6,
                    excluded_node_ids=exclude_node_ids,
                ),
                "score": round(score, 4),
                "score_components": {"semantic_memory": 8.0, "relevance": round(relevance, 4)},
            }))
        ranked.sort(key=lambda item: (-item[0], str(item[1]["label"])))
        return [item for _, item in ranked]

    def _resolve_memory_endpoint(self, *, user_id: str, endpoint: dict[str, Any]) -> tuple[str, str]:
        node_id = str(endpoint.get("node_id") or "").strip()
        if node_id:
            node = self._repo.get_node(node_id)
            if node is None or not node.is_active:
                raise ValueError(f"memory endpoint node not found or inactive: {node_id}")
            owner = str(node.payload.get("user_id") or "")
            if owner and owner != user_id:
                raise ValueError("memory endpoint belongs to another user")
            return node.node_id, node.labels[0] if node.labels else node.node_id

        kind = str(endpoint.get("kind") or "").strip().casefold()
        if kind == "user":
            anchor_id = user_anchor_id(user_id)
            self.ensure_user_anchor(user_id)
            return anchor_id, "user"
        label = str(endpoint.get("label") or "").strip()
        if not label:
            raise ValueError("memory endpoint requires node_id, or kind and label")
        canonical = _canonical_label(label)
        entity_id = fact_node_id(user_id, canonical, namespace="semantic_entity")
        existing = self._repo.get_node(entity_id)
        if existing is None:
            self._repo.upsert_node(GraphNode(
                node_id=entity_id,
                labels=[label],
                node_type=_SEMANTIC_ENTITY_TYPE,
                payload={"user_id": user_id, "kind": kind or "concept", "canonical_label": canonical},
                provenance="model_memory",
                trust_score=0.8,
                stability_score=0.8,
            ))
        return entity_id, existing.labels[0] if existing and existing.labels else label


def _canonical_label(label: str) -> str:
    canonical = " ".join(label.strip().casefold().split())
    if not canonical:
        raise ValueError("memory label must not be empty")
    return canonical


def _normalize_relation(relation: str) -> str:
    normalized = re.sub(r"_+", "_", re.sub(r"[\s-]+", "_", relation.strip().casefold())).strip("_")
    if not normalized:
        raise ValueError("memory relation must not be empty")
    return normalized
