from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ... import config
from ..goal import GOAL_ROOT_HASH, GLOBAL_GOAL_AXIS_SEEDS
from ..profile import is_profile_reference_edge, is_user_profile_node, profile_context_labels
from ..utils.hash_resolver import ANCHOR_ASSISTANT, ANCHOR_USER

if TYPE_CHECKING:
    from ..entities.edge import Edge
    from ..entities.node import Node
    from ..thinking.thought_engine import ConclusionView


@dataclass(frozen=True, slots=True)
class AnswerContract:
    """GraphToLang에 넘길 결정론적 응답 계약.

    이 구조는 LLM 호출 없이 ConclusionView에서 컴파일된다. LLM은 이 contract를
    자연어로 언어화만 한다.
    """

    mode: str
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
    response_policies: list[str] = field(default_factory=list)


def build_answer_contract(conclusion: "ConclusionView") -> AnswerContract:
    """ConclusionView를 작은 AnswerContract로 압축한다.

    원칙:
    - raw graph edge dump를 GraphToLang에 넘기지 않는다.
    - selected ConclusionGraph가 있으면 그 국소 그래프를 우선한다.
    - selected graph가 비어 있으면 key/ref/profile 중심의 최소 contract만 만든다.
    - ProfileRecallView는 긴 자연어 지시문이 아니라 mode/labels/confidence로 표현한다.
    """

    node_map = {node.address_hash: node for node in conclusion.nodes}
    edge_by_id = {edge.edge_id: edge for edge in conclusion.edges}
    identity_names = {ANCHOR_USER: "사용자", ANCHOR_ASSISTANT: "AI"}
    internal_goal_hashes = {GOAL_ROOT_HASH, *(seed.node_hash for seed in GLOBAL_GOAL_AXIS_SEEDS)}
    if conclusion.goal_hash:
        internal_goal_hashes.add(conclusion.goal_hash)

    def is_internal_goal_hash(address_hash: str) -> bool:
        return address_hash in internal_goal_hashes

    def is_internal_profile_hash(address_hash: str) -> bool:
        node = node_map.get(address_hash)
        return bool(node and is_user_profile_node(node))

    def is_verbalizable_hash(address_hash: str) -> bool:
        return not is_internal_goal_hash(address_hash) and not is_internal_profile_hash(address_hash)

    def node_label(address_hash: str) -> str:
        if address_hash in identity_names:
            return identity_names[address_hash]
        if is_internal_goal_hash(address_hash):
            return "내부 목표"
        if is_internal_profile_hash(address_hash):
            return "사용자 프로필"
        node = node_map.get(address_hash)
        if node and node.labels:
            return node.labels[0]
        return address_hash[:8]

    def display_degree(address_hash: str) -> int:
        degree = 0
        for edge in conclusion.edges:
            if edge.is_temporary and not (edge.edge_family == "relation" and edge.source_hash in identity_names):
                continue
            if is_profile_reference_edge(edge):
                continue
            if is_internal_goal_hash(edge.source_hash) or is_internal_goal_hash(edge.target_hash):
                continue
            if is_internal_profile_hash(edge.source_hash) or is_internal_profile_hash(edge.target_hash):
                continue
            if address_hash in {edge.source_hash, edge.target_hash}:
                degree += 1
        return degree

    def ranked_labels(hashes: set[str], *, limit: int) -> list[str]:
        ranked_hashes = sorted(
            (h for h in hashes if is_verbalizable_hash(h)),
            key=lambda h: (-display_degree(h), node_label(h), h),
        )
        labels: list[str] = []
        for h in ranked_hashes:
            node = node_map.get(h)
            if node and (node.is_abstract or not node.labels):
                continue
            label = node_label(h)
            if label not in labels:
                labels.append(label)
            if len(labels) >= limit:
                break
        return labels

    key_labels = ranked_labels(set(conclusion.key_hashes), limit=5)
    ref_labels = ranked_labels(set(conclusion.ref_hashes), limit=4)

    profile_labels: list[str] = []
    profile_recall_confidence: float | None = None
    if conclusion.profile_activation_view and conclusion.profile_activation_view.is_active:
        profile_labels = profile_context_labels(conclusion.profile_activation_view, node_map, limit=4)
        if profile_labels:
            profile_recall_confidence = conclusion.profile_activation_view.confidence

    answer_graphs = [graph for graph in conclusion.selected_graphs if not graph.has_conflict_structure]
    conflict_graphs = [graph for graph in conclusion.selected_graphs if graph.has_conflict_structure]

    conclusion_lines = _render_conclusion_graph_lines(
        answer_graphs,
        edge_by_id=edge_by_id,
        node_label=node_label,
        is_verbalizable_hash=is_verbalizable_hash,
        limit=2,
    )
    conflict_lines = _render_conflict_graph_lines(
        conflict_graphs,
        node_label=node_label,
        is_verbalizable_hash=is_verbalizable_hash,
        limit=2,
    )

    selected_graph_node_hashes = {
        h
        for graph in conclusion.selected_graphs
        for h in graph.node_hashes
        if is_verbalizable_hash(h)
    }
    selected_graph_edge_ids = {
        edge_id
        for graph in conclusion.selected_graphs
        for edge_id in graph.edge_ids
    }

    evidence_lines = _select_evidence_lines(
        conclusion,
        edge_by_id=edge_by_id,
        selected_graph_edge_ids=selected_graph_edge_ids,
        node_label=node_label,
        is_verbalizable_hash=is_verbalizable_hash,
        limit=5,
    )

    search_context_parts = _select_search_context(
        conclusion,
        node_map=node_map,
        selected_graph_node_hashes=selected_graph_node_hashes,
        is_verbalizable_hash=is_verbalizable_hash,
        limit=2,
    )

    mode = _select_mode(
        has_conflict=bool(conflict_lines),
        has_profile=bool(profile_labels),
        has_conclusion=bool(conclusion_lines),
        has_search=bool(search_context_parts),
    )

    return AnswerContract(
        mode=mode,
        continuity=conclusion.topic_continuity,
        max_sentences=4 if mode != "conflict_resolution" else 5,
        key_labels=key_labels,
        ref_labels=ref_labels,
        profile_labels=profile_labels,
        profile_recall_confidence=profile_recall_confidence,
        conclusion_lines=conclusion_lines,
        conflict_lines=conflict_lines,
        evidence_lines=evidence_lines,
        search_context_parts=search_context_parts,
        response_policies=_response_policies(mode, has_profile=bool(profile_labels)),
    )


def render_answer_contract(contract: AnswerContract) -> str:
    """AnswerContract를 작고 안정적인 텍스트 블록으로 렌더링한다."""

    lines: list[str] = [
        "[AnswerContract]",
        f"mode={contract.mode}",
        f"continuity={contract.continuity}",
        f"max_sentences={contract.max_sentences}",
    ]

    if contract.key_labels:
        lines.append("key_concepts=" + ", ".join(contract.key_labels))
    if contract.ref_labels:
        lines.append("reference_concepts=" + ", ".join(contract.ref_labels))

    if contract.profile_labels:
        confidence = (
            f"{contract.profile_recall_confidence:.2f}"
            if contract.profile_recall_confidence is not None
            else "unknown"
        )
        lines.extend([
            "[ProfileRecall]",
            "status=active",
            f"confidence={confidence}",
            "context=" + ", ".join(contract.profile_labels),
        ])

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

    if contract.response_policies:
        lines.append("[ResponsePolicy]")
        lines.extend(f"- {policy}" for policy in contract.response_policies)

    return "\n".join(lines)


def _select_mode(
    *,
    has_conflict: bool,
    has_profile: bool,
    has_conclusion: bool,
    has_search: bool,
) -> str:
    if has_conflict:
        return "conflict_resolution"
    if has_conclusion:
        return "conclusion_graph_response"
    if has_search:
        return "grounded_answer"
    if has_profile:
        return "limited_profile_recall"
    return "compact_structural_response"


def _response_policies(mode: str, *, has_profile: bool) -> list[str]:
    policies = [
        "한국어로 답한다.",
        "그래프 상태나 필드명을 사용자에게 나열하지 않는다.",
        "사용자의 설명을 장황하게 반복하지 않고 핵심 관계만 압축한다.",
        "AnswerContract에 없는 일반론을 길게 추가하지 않는다.",
    ]
    if has_profile:
        policies.append("현재 사용자 맥락은 확정 사실이 아니라 재활성화 후보로만 조심스럽게 반영한다.")
        policies.append("기억 부재, 처음 만남, 세션 초기화를 단정하지 않는다.")
    if mode == "compact_structural_response":
        policies.append("다음 설계 쟁점이 보이면 하나만 제시한다.")
    return policies


def _render_conclusion_graph_lines(
    graphs,
    *,
    edge_by_id: dict[str, "Edge"],
    node_label,
    is_verbalizable_hash,
    limit: int,
) -> list[str]:
    lines: list[str] = []
    for graph in graphs[:limit]:
        core = _labels_from_hashes(graph.core_hashes, node_label, is_verbalizable_hash, limit=5)
        bridge = _labels_from_hashes(graph.bridge_hashes, node_label, is_verbalizable_hash, limit=3)
        exceptions = _labels_from_hashes(graph.exception_hashes, node_label, is_verbalizable_hash, limit=2)
        edges = []
        for edge_id in sorted(graph.edge_ids):
            edge = edge_by_id.get(edge_id)
            if edge is None or edge.is_temporary or is_profile_reference_edge(edge):
                continue
            if not is_verbalizable_hash(edge.source_hash) or not is_verbalizable_hash(edge.target_hash):
                continue
            edges.append(f"{node_label(edge.source_hash)} -[{edge.connect_type}]-> {node_label(edge.target_hash)}")
            if len(edges) >= 3:
                break

        parts = []
        if core:
            parts.append("core=" + ", ".join(core))
        if bridge:
            parts.append("bridge=" + ", ".join(bridge))
        if exceptions:
            parts.append("exception=" + ", ".join(exceptions))
        if edges:
            parts.append("edges=" + "; ".join(edges))
        if parts:
            parts.append(f"score={graph.score:.3f}")
            lines.append(" / ".join(parts))
    return lines


def _render_conflict_graph_lines(
    graphs,
    *,
    node_label,
    is_verbalizable_hash,
    limit: int,
) -> list[str]:
    lines: list[str] = []
    for graph in graphs[:limit]:
        current = _labels_from_hashes(graph.core_hashes, node_label, is_verbalizable_hash, limit=4)
        previous = _labels_from_hashes(
            graph.exception_hashes | graph.condition_hashes,
            node_label,
            is_verbalizable_hash,
            limit=4,
        )
        conflicts = []
        for path in graph.conflict_paths[:3]:
            for step in path.steps:
                if not is_verbalizable_hash(step.source_hash) or not is_verbalizable_hash(step.target_hash):
                    continue
                conflicts.append(f"{node_label(step.source_hash)} -[conflict]-> {node_label(step.target_hash)}")
                if len(conflicts) >= 3:
                    break
            if len(conflicts) >= 3:
                break

        parts = []
        if current:
            parts.append("current=" + ", ".join(current))
        if previous:
            parts.append("previous=" + ", ".join(previous))
        if conflicts:
            parts.append("conflicts=" + "; ".join(conflicts))
        if parts:
            parts.append(f"uncertainty={graph.uncertainty:.2f}")
            lines.append(" / ".join(parts))
    return lines


def _labels_from_hashes(hashes, node_label, is_verbalizable_hash, *, limit: int) -> list[str]:
    labels: list[str] = []
    for h in sorted(hashes, key=lambda value: node_label(value)):
        if not is_verbalizable_hash(h):
            continue
        label = node_label(h)
        if label not in labels:
            labels.append(label)
        if len(labels) >= limit:
            break
    return labels


def _select_evidence_lines(
    conclusion: "ConclusionView",
    *,
    edge_by_id: dict[str, "Edge"],
    selected_graph_edge_ids: set[str],
    node_label,
    is_verbalizable_hash,
    limit: int,
) -> list[str]:
    """GraphToLang에 넘길 근거 edge를 최대 limit개로 제한한다."""

    evidence: list[tuple[int, float, str]] = []
    used_keys: set[tuple[str, str, str]] = set()
    key_or_ref_hashes = set(conclusion.key_hashes) | set(conclusion.ref_hashes)

    def add_edge(edge: "Edge", *, priority: int) -> None:
        if len(evidence) >= limit * 3:
            return
        if is_profile_reference_edge(edge):
            return
        if edge.is_temporary and not (edge.edge_family == "relation" and edge.source_hash == ANCHOR_USER):
            return
        if not is_verbalizable_hash(edge.source_hash) or not is_verbalizable_hash(edge.target_hash):
            return
        key = (edge.source_hash, edge.target_hash, edge.connect_type)
        if key in used_keys:
            return
        used_keys.add(key)
        evidence.append((
            priority,
            -edge.edge_weight,
            f"{node_label(edge.source_hash)} -[{edge.connect_type}, {edge.edge_weight:.2f}]-> {node_label(edge.target_hash)}",
        ))

    for edge_id in selected_graph_edge_ids:
        edge = edge_by_id.get(edge_id)
        if edge is not None:
            add_edge(edge, priority=0)

    for edge in conclusion.edges:
        if edge.source_hash == ANCHOR_USER and edge.target_hash in key_or_ref_hashes:
            add_edge(edge, priority=1)

    for edge in conclusion.edges:
        if edge.source_hash not in key_or_ref_hashes and edge.target_hash not in key_or_ref_hashes:
            continue
        if edge.connect_type == "neutral" and edge.edge_weight < 1.0:
            continue
        add_edge(edge, priority=2)

    return [line for _, _, line in sorted(evidence)[:limit]]


def _select_search_context(
    conclusion: "ConclusionView",
    *,
    node_map: dict[str, "Node"],
    selected_graph_node_hashes: set[str],
    is_verbalizable_hash,
    limit: int,
) -> list[str]:
    snippets: list[str] = []
    seen: set[str] = set()
    allowed_search_hashes = selected_graph_node_hashes.intersection(conclusion.search_node_hashes)
    allowed_search_hashes = {h for h in allowed_search_hashes if is_verbalizable_hash(h)}

    for h in sorted(allowed_search_hashes):
        node = node_map.get(h)
        if node is None:
            continue
        summary = node.payload.get("search_summary", "")
        if not summary:
            continue
        snippet = summary[:350]
        if snippet in seen:
            continue
        seen.add(snippet)
        snippets.append(snippet)
        if len(snippets) >= limit:
            break
    return snippets
