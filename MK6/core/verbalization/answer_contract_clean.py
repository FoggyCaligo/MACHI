from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..goal import GOAL_ROOT_HASH, GLOBAL_GOAL_AXIS_SEEDS
from ..profile import is_user_profile_node, profile_context_labels
from ..utils.hash_resolver import ANCHOR_ASSISTANT, ANCHOR_USER
from .answer_contract import (
    EVIDENCE_EDGE_RATIO,
    _render_conclusion_graph_lines,
    _render_conflict_graph_lines,
    _select_evidence_lines,
    _select_search_context,
)

if TYPE_CHECKING:
    from ..thinking.thought_engine import ConclusionView


@dataclass(frozen=True, slots=True)
class AnswerContract:
    continuity: str
    max_sentences: int
    key_labels: list[str] = field(default_factory=list)
    ref_labels: list[str] = field(default_factory=list)
    profile_labels: list[str] = field(default_factory=list)
    profile_recall_confidence: float | None = None
    conclusion_lines: list[str] = field(default_factory=list)
    conflict_lines: list[str] = field(default_factory=list)
    evidence_lines: list[str] = field(default_factory=list)
    search_context_parts: list[str] = field(default_factory=list)


def build_answer_contract(conclusion: "ConclusionView") -> AnswerContract:
    node_map = {node.address_hash: node for node in conclusion.nodes}
    edge_by_id = {edge.edge_id: edge for edge in conclusion.edges}
    identity_names = {ANCHOR_USER: "사용자", ANCHOR_ASSISTANT: "AI"}
    internal_goal_hashes = {GOAL_ROOT_HASH, *(seed.node_hash for seed in GLOBAL_GOAL_AXIS_SEEDS)}
    if conclusion.goal_hash:
        internal_goal_hashes.add(conclusion.goal_hash)

    def is_internal_profile_hash(address_hash: str) -> bool:
        node = node_map.get(address_hash)
        return bool(node and is_user_profile_node(node))

    def is_verbalizable_hash(address_hash: str) -> bool:
        return address_hash not in internal_goal_hashes and not is_internal_profile_hash(address_hash)

    def node_label(address_hash: str) -> str:
        if address_hash in identity_names:
            return identity_names[address_hash]
        node = node_map.get(address_hash)
        if node and node.labels:
            return node.labels[0]
        return address_hash[:8]

    def display_degree(address_hash: str) -> int:
        degree = 0
        for edge in conclusion.edges:
            if address_hash in {edge.source_hash, edge.target_hash}:
                degree += 1
        return degree

    def ranked_labels(hashes: set[str], *, limit: int) -> list[str]:
        labels: list[str] = []
        ranked = sorted((h for h in hashes if is_verbalizable_hash(h)), key=lambda h: (-display_degree(h), node_label(h), h))
        for h in ranked:
            node = node_map.get(h)
            if node and (node.is_abstract or not node.labels):
                continue
            label = node_label(h)
            if label not in labels:
                labels.append(label)
            if len(labels) >= limit:
                break
        return labels

    profile_labels: list[str] = []
    profile_conf: float | None = None
    if conclusion.profile_activation_view and conclusion.profile_activation_view.is_active:
        profile_labels = profile_context_labels(conclusion.profile_activation_view, node_map, limit=4)
        if profile_labels:
            profile_conf = conclusion.profile_activation_view.confidence

    answer_graphs = [graph for graph in conclusion.selected_graphs if not graph.has_conflict_structure]
    conflict_graphs = [graph for graph in conclusion.selected_graphs if graph.has_conflict_structure]
    conclusion_lines = _render_conclusion_graph_lines(answer_graphs, edge_by_id=edge_by_id, node_label=node_label, is_verbalizable_hash=is_verbalizable_hash, limit=2)
    conflict_lines = _render_conflict_graph_lines(conflict_graphs, node_label=node_label, is_verbalizable_hash=is_verbalizable_hash, limit=2)
    selected_node_hashes = {h for graph in conclusion.selected_graphs for h in graph.node_hashes if is_verbalizable_hash(h)}
    selected_edge_ids = {edge_id for graph in conclusion.selected_graphs for edge_id in graph.edge_ids}

    return AnswerContract(
        continuity=conclusion.topic_continuity,
        max_sentences=5 if conflict_lines else 4,
        key_labels=ranked_labels(set(conclusion.key_hashes), limit=5),
        ref_labels=ranked_labels(set(conclusion.ref_hashes), limit=4),
        profile_labels=profile_labels,
        profile_recall_confidence=profile_conf,
        conclusion_lines=conclusion_lines,
        conflict_lines=conflict_lines,
        evidence_lines=_select_evidence_lines(conclusion, edge_by_id=edge_by_id, selected_graph_edge_ids=selected_edge_ids, node_label=node_label, is_verbalizable_hash=is_verbalizable_hash, evidence_ratio=EVIDENCE_EDGE_RATIO),
        search_context_parts=_select_search_context(conclusion, node_map=node_map, selected_graph_node_hashes=selected_node_hashes, is_verbalizable_hash=is_verbalizable_hash, limit=2),
    )


def render_answer_contract(contract: AnswerContract) -> str:
    lines = ["[AnswerContract]", f"continuity={contract.continuity}", f"max_sentences={contract.max_sentences}"]
    if contract.key_labels:
        lines.append("key_concepts=" + ", ".join(contract.key_labels))
    if contract.ref_labels:
        lines.append("reference_concepts=" + ", ".join(contract.ref_labels))
    if contract.profile_labels:
        confidence = f"{contract.profile_recall_confidence:.2f}" if contract.profile_recall_confidence is not None else "unknown"
        lines.extend(["[ProfileRecall]", "active=true", f"confidence={confidence}", "context=" + ", ".join(contract.profile_labels)])
    if contract.conclusion_lines:
        lines.append("[ConclusionGraph]")
        lines.extend(f"- {line}" for line in contract.conclusion_lines)
    if contract.conflict_lines:
        lines.append("[ClaimConflict]")
        lines.extend(f"- {line}" for line in contract.conflict_lines)
    if contract.evidence_lines:
        lines.append("[EvidenceEdges]")
        lines.extend(f"- {line}" for line in contract.evidence_lines)
    if contract.search_context_parts:
        lines.append("[SearchContext]")
        lines.extend(f"- {part}" for part in contract.search_context_parts)
    return "\n".join(lines)
