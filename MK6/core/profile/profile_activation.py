from __future__ import annotations

from dataclasses import dataclass, field

from ..entities.edge import Edge
from ..entities.node import Node
from ..entities.translated_graph import ConceptPointer, EmptySlot, TranslatedGraph
from ..storage.world_graph import get_edges_for_node, get_node
from ..utils.hash_resolver import ANCHOR_USER, compute_hash
from .user_profile import ensure_user_profile, is_profile_reference_edge


@dataclass(frozen=True, slots=True)
class ProfileActivationView:
    """이번 턴 Think에 넘길 사용자 프로필 기반 국소 활성화 뷰.

    UserProfile 자체는 내부 인덱스다. 이 View는 현재 입력과 profile_reference가
    구조적으로 겹칠 때, Think가 읽기 전용 context frontier로 사용할 seed를 제공한다.
    """

    profile_hash: str
    reference_hashes: set[str] = field(default_factory=set)
    matched_hashes: set[str] = field(default_factory=set)
    seed_hashes: set[str] = field(default_factory=set)
    confidence: float = 0.0
    activation_reason: str | None = None

    @property
    def is_active(self) -> bool:
        return bool(self.seed_hashes)


def build_profile_activation_view(
    conn,
    translated: TranslatedGraph,
    *,
    user_anchor_hash: str = ANCHOR_USER,
    max_seed_refs: int = 12,
) -> ProfileActivationView:
    """현재 입력에 대응하는 ProfileActivationView를 만든다.

    규칙:
    - UserProfile은 항상 보장한다.
    - 하지만 profile reference 전체를 항상 활성화하지는 않는다.
    - 현재 입력 concept과 profile reference target이 겹칠 때만 활성화한다.
    - profile_reference edge 자체는 언어화 대상이 아니라 내부 context index다.
    """
    profile_view = ensure_user_profile(conn, user_anchor_hash=user_anchor_hash)
    profile_hash = profile_view.profile_hash
    reference_edges = _profile_reference_edges(conn, profile_hash)
    reference_hashes = {
        edge.target_hash
        for edge in reference_edges
        if edge.source_hash == profile_hash and _is_active_node(conn, edge.target_hash)
    }
    current_hashes = _translated_hashes(translated)
    matched_hashes = current_hashes.intersection(reference_hashes)

    if not matched_hashes:
        return ProfileActivationView(
            profile_hash=profile_hash,
            reference_hashes=reference_hashes,
            matched_hashes=set(),
            seed_hashes=set(),
            confidence=0.0,
            activation_reason=None,
        )

    ranked_edges = sorted(
        [edge for edge in reference_edges if edge.target_hash in reference_hashes],
        key=lambda edge: (edge.target_hash not in matched_hashes, -edge.support_count, -edge.edge_weight),
    )
    seed_hashes: set[str] = set(matched_hashes)
    for edge in ranked_edges:
        if len(seed_hashes) >= max_seed_refs:
            break
        seed_hashes.add(edge.target_hash)

    confidence = min(1.0, 0.45 + 0.15 * len(matched_hashes))
    return ProfileActivationView(
        profile_hash=profile_hash,
        reference_hashes=reference_hashes,
        matched_hashes=matched_hashes,
        seed_hashes=seed_hashes,
        confidence=confidence,
        activation_reason="current_input_overlaps_profile_reference",
    )


def profile_context_labels(view: ProfileActivationView, node_map: dict[str, Node], *, limit: int = 12) -> list[str]:
    """GraphToLang에 줄 사용자 맥락 라벨을 만든다.

    profile edge 자체가 아니라, 활성화된 seed concept의 label만 노출한다.
    """
    labels: list[str] = []
    for h in sorted(view.seed_hashes, key=lambda item: (item not in view.matched_hashes, item)):
        node = node_map.get(h)
        if node is None or node.is_abstract or not node.labels:
            continue
        label = node.labels[0]
        if label not in labels:
            labels.append(label)
        if len(labels) >= limit:
            break
    return labels


def _profile_reference_edges(conn, profile_hash: str) -> list[Edge]:
    return [
        edge for edge in get_edges_for_node(conn, profile_hash)
        if edge.source_hash == profile_hash and edge.is_active and is_profile_reference_edge(edge)
    ]


def _translated_hashes(translated: TranslatedGraph) -> set[str]:
    hashes: set[str] = set()
    for ref in translated.nodes:
        if isinstance(ref, ConceptPointer):
            hashes.add(ref.address_hash)
        elif isinstance(ref, EmptySlot) and ref.concept_hint.strip():
            hashes.add(compute_hash(ref.concept_hint.strip()))
    return hashes


def _is_active_node(conn, address_hash: str) -> bool:
    node = get_node(conn, address_hash)
    return bool(node and node.is_active)
