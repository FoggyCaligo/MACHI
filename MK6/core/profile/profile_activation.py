from __future__ import annotations

from dataclasses import dataclass, field

from ..entities.edge import Edge
from ..entities.node import Node
from ..entities.translated_graph import ConceptPointer, EmptySlot, TranslatedGraph
from ..storage.world_graph import get_edges_for_node, get_node
from ..utils.hash_resolver import ANCHOR_USER, compute_hash
from .user_profile import ensure_user_profile, is_profile_reference_edge


MIN_PROFILE_CONTEXT_SCORE = 0.75
MIN_STRUCTURAL_CONTEXT_FOR_MATCH = 1
MIN_STRUCTURAL_CONTEXT_FOR_REFERENCE = 2


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
    seed_scores: dict[str, float] = field(default_factory=dict)
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
    - 현재 입력 direct concept과 profile_reference target이 겹칠 때만 활성화한다.
    - semantic_local_candidate는 주변 context 후보이지 activation cue가 아니다.
    - profile_reference edge 자체는 언어화 대상이 아니라 내부 context index다.
    - 활성화 seed는 문자열 패턴이 아니라 edge support/weight/구조 연결도 기준으로 정제한다.
    """
    profile_view = ensure_user_profile(conn, user_anchor_hash=user_anchor_hash)
    profile_hash = profile_view.profile_hash
    reference_edges = _profile_reference_edges(conn, profile_hash)
    reference_hashes = {
        edge.target_hash
        for edge in reference_edges
        if edge.source_hash == profile_hash and _is_active_node(conn, edge.target_hash)
    }
    current_hashes = _translated_direct_hashes(translated)
    matched_hashes = current_hashes.intersection(reference_hashes)

    if not matched_hashes:
        return ProfileActivationView(
            profile_hash=profile_hash,
            reference_hashes=reference_hashes,
            matched_hashes=set(),
            seed_hashes=set(),
            seed_scores={},
            confidence=0.0,
            activation_reason=None,
        )

    scored_edges: list[tuple[float, Edge]] = []
    seed_scores: dict[str, float] = {}
    for edge in reference_edges:
        if edge.target_hash not in reference_hashes:
            continue
        structural_context = _structural_context_count(
            conn,
            edge.target_hash,
            profile_hash=profile_hash,
            user_anchor_hash=user_anchor_hash,
        )
        matched = edge.target_hash in matched_hashes
        if not _is_reference_seed_allowed(edge, structural_context, matched=matched):
            continue

        score = _reference_seed_score(edge, structural_context, matched=matched)
        if score < MIN_PROFILE_CONTEXT_SCORE:
            continue
        seed_scores[edge.target_hash] = score
        scored_edges.append((score, edge))

    ranked_edges = sorted(
        scored_edges,
        key=lambda item: (item[1].target_hash not in matched_hashes, -item[0], -item[1].support_count, -item[1].edge_weight),
    )

    seed_hashes: set[str] = set()
    for score, edge in ranked_edges:
        if len(seed_hashes) >= max_seed_refs:
            break
        seed_hashes.add(edge.target_hash)
        seed_scores[edge.target_hash] = score

    if not seed_hashes:
        return ProfileActivationView(
            profile_hash=profile_hash,
            reference_hashes=reference_hashes,
            matched_hashes=matched_hashes,
            seed_hashes=set(),
            seed_scores={},
            confidence=0.0,
            activation_reason=None,
        )

    confidence = min(1.0, 0.35 + 0.1 * len(seed_hashes) + 0.1 * len(seed_hashes.intersection(matched_hashes)))
    return ProfileActivationView(
        profile_hash=profile_hash,
        reference_hashes=reference_hashes,
        matched_hashes=matched_hashes,
        seed_hashes=seed_hashes,
        seed_scores=seed_scores,
        confidence=confidence,
        activation_reason="current_direct_input_overlaps_profile_reference",
    )


def profile_context_labels(view: ProfileActivationView, node_map: dict[str, Node], *, limit: int = 8) -> list[str]:
    """GraphToLang에 줄 사용자 맥락 라벨을 만든다.

    profile edge 자체가 아니라, 활성화된 seed concept의 label만 노출한다.
    라벨 선정은 문자열 차단 목록이 아니라 ProfileActivationView의 구조 점수에 따른다.
    """
    labels: list[str] = []
    ranked_hashes = sorted(
        view.seed_hashes,
        key=lambda h: (h not in view.matched_hashes, -view.seed_scores.get(h, 0.0), h),
    )
    for h in ranked_hashes:
        if view.seed_scores.get(h, 0.0) < MIN_PROFILE_CONTEXT_SCORE:
            continue
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


def _translated_direct_hashes(translated: TranslatedGraph) -> set[str]:
    hashes: set[str] = set()
    for ref in translated.nodes:
        if isinstance(ref, ConceptPointer):
            if not ref.is_direct_input_match:
                continue
            hashes.add(ref.address_hash)
        elif isinstance(ref, EmptySlot) and ref.concept_hint.strip():
            hashes.add(compute_hash(ref.concept_hint.strip()))
    return hashes


def _is_active_node(conn, address_hash: str) -> bool:
    node = get_node(conn, address_hash)
    return bool(node and node.is_active)


def _structural_context_count(
    conn,
    address_hash: str,
    *,
    profile_hash: str,
    user_anchor_hash: str,
) -> int:
    """profile/user anchor 밖에서 해당 concept이 가진 구조 연결 수.

    단순히 사용자 발화에 한 번 등장한 개념보다, 다른 concept들과 실제 관계를 가진 개념을
    우선 재활성화하기 위한 구조 점수다.
    """
    count = 0
    for edge in get_edges_for_node(conn, address_hash):
        if not edge.is_active or edge.is_temporary:
            continue
        if is_profile_reference_edge(edge):
            continue
        other_hash = edge.target_hash if edge.source_hash == address_hash else edge.source_hash
        if other_hash in {profile_hash, user_anchor_hash}:
            continue
        if edge.connect_type == "conflict":
            continue
        count += 1
    return count


def _is_reference_seed_allowed(edge: Edge, structural_context: int, *, matched: bool) -> bool:
    if matched:
        return structural_context >= MIN_STRUCTURAL_CONTEXT_FOR_MATCH
    return structural_context >= MIN_STRUCTURAL_CONTEXT_FOR_REFERENCE and edge.support_count >= 2


def _reference_seed_score(edge: Edge, structural_context: int, *, matched: bool) -> float:
    match_bonus = 0.55 if matched else 0.0
    support_score = min(0.5, edge.support_count * 0.1)
    structure_score = min(0.7, structural_context * 0.18)
    weight_score = min(0.4, edge.edge_weight * 0.4)
    return match_bonus + support_score + structure_score + weight_score
