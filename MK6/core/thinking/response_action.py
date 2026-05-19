from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Awaitable, Callable

from ..entities.edge import Edge
from ..entities.node import Node
from ..entities.translated_graph import ConceptPointer, EmptySlot, TranslatedGraph
from ..profile import ProfileActivationView
from ..utils.hash_resolver import ANCHOR_ASSISTANT, ANCHOR_USER, compute_hash
from .conclusion_graph import ActivationState, ConclusionGraph, ReasoningPath

if TYPE_CHECKING:
    from .thought_engine import ConclusionView


EmbedFn = Callable[[str], Awaitable[list[float]]]

RESPONSE_ACTION_VIEW_SCOPE = "response_action"
TURN_RESPONSE_LABEL = "응답하기"


async def build_response_action_graph(
    conclusion: "ConclusionView",
    translated: TranslatedGraph,
    profile_activation_view: ProfileActivationView | None,
    embed_fn: EmbedFn,
) -> ConclusionGraph:
    """selected 결론이 비어 있을 때 단일 TurnConclusionGraph를 만든다.

    응답 행위를 greeting/question/request 같은 family로 분류하지 않는다. 그런 분류는
    response kind ontology를 계속 늘리는 방향으로 흐르기 쉽다. 이 계층은 오직 하나의
    구조만 만든다.

    - AI가
    - 현재 사용자에게
    - 이번 턴 입력 그래프를 근거로
    - 다음 발화를 생성한다

    입력의 세부 의미는 별도 family 문자열이 아니라 input_hashes/support_paths/context
    연결로 남긴다. GraphToLang은 이 결론 그래프를 보고 다음 발화를 언어화한다.
    """
    del embed_fn

    node_map = {node.address_hash: node for node in conclusion.nodes}
    display_hashes = _rank_target_display_hashes(profile_activation_view, node_map)
    context_hashes = _translated_input_hashes(translated)
    confidence = _structural_confidence(
        input_count=len(context_hashes),
        display_count=len(display_hashes),
        profile_confidence=profile_activation_view.confidence if profile_activation_view else 0.0,
    )

    graph = _make_turn_response_graph(
        conclusion,
        display_hashes=display_hashes,
        context_hashes=context_hashes,
        confidence=confidence,
    )
    print(
        f"[response_action] selected graph={graph.graph_id} "
        f"action=turn_response target_display={_format_hashes(display_hashes)} "
        f"context={_format_hashes(sorted(context_hashes))}"
    )
    return graph


def _structural_confidence(*, input_count: int, display_count: int, profile_confidence: float) -> float:
    base = 0.55
    base += min(0.25, input_count * 0.05)
    base += min(0.10, display_count * 0.05)
    base += min(0.10, max(0.0, profile_confidence) * 0.10)
    return min(1.0, base)


def _rank_target_display_hashes(
    view: ProfileActivationView | None,
    node_map: dict[str, Node],
    *,
    limit: int = 2,
) -> list[str]:
    if view is None:
        return []
    candidates = set(view.display_hashes or set()) | set(view.matched_hashes or set())
    ranked = sorted(
        candidates,
        key=lambda h: (
            h not in view.display_hashes,
            -view.display_scores.get(h, view.seed_scores.get(h, 0.0)),
            h,
        ),
    )
    result: list[str] = []
    for h in ranked:
        node = node_map.get(h)
        if node is None or node.is_abstract or not node.labels:
            continue
        result.append(h)
        if len(result) >= limit:
            break
    return result


def _make_turn_response_graph(
    conclusion: "ConclusionView",
    *,
    display_hashes: list[str],
    context_hashes: set[str],
    confidence: float,
) -> ConclusionGraph:
    now = datetime.now(timezone.utc)
    target_hash = ANCHOR_USER
    actor_hash = ANCHOR_ASSISTANT
    action_hash = _stable_hash("turn-conclusion::assistant-response-to-current-user")

    action_node = Node(
        address_hash=action_hash,
        node_kind="event",
        formation_source="system_policy",
        labels=[TURN_RESPONSE_LABEL, "turn_response"],
        is_abstract=False,
        trust_score=confidence,
        stability_score=0.2,
        is_active=True,
        payload={
            "runtime_view": True,
            "response_action": True,
            "turn_conclusion": True,
            "actor_hash": actor_hash,
            "target_hash": target_hash,
            "target_display_hashes": list(display_hashes),
            "input_context_hashes": sorted(context_hashes),
            "confidence": confidence,
        },
        created_at=now,
        updated_at=now,
    )

    nodes_by_hash = {node.address_hash: node for node in conclusion.nodes}
    if action_hash not in nodes_by_hash:
        conclusion.nodes.append(action_node)
    else:
        nodes_by_hash[action_hash].payload.update(action_node.payload)

    edge_ids: set[str] = set()
    for edge in _turn_response_edges(action_hash, actor_hash, target_hash, display_hashes, context_hashes, confidence, now):
        conclusion.edges.append(edge)
        edge_ids.add(edge.edge_id)

    goal_hashes = {conclusion.goal_hash} if conclusion.goal_hash else set()
    node_hashes = {action_hash, actor_hash, target_hash, *display_hashes, *context_hashes}

    support_paths = [
        ReasoningPath(start_hash=h, end_hash=action_hash, steps=(), path_weight=confidence)
        for h in sorted(context_hashes)
    ]
    goal_paths: list[ReasoningPath] = []
    if conclusion.goal_hash:
        goal_paths.append(ReasoningPath(start_hash=conclusion.goal_hash, end_hash=action_hash, steps=(), path_weight=confidence))

    graph_id = _stable_hash(action_hash + "::" + "|".join(sorted(edge_ids)))
    activation = {
        action_hash: ActivationState(input_energy=confidence, goal_energy=confidence, novelty_score=1.0),
        actor_hash: ActivationState(goal_energy=confidence, context_energy=confidence),
        target_hash: ActivationState(input_energy=confidence, context_energy=confidence),
    }
    for display_hash in display_hashes:
        activation[display_hash] = ActivationState(input_energy=confidence, context_energy=confidence)
    for context_hash in context_hashes:
        activation[context_hash] = ActivationState(input_energy=confidence, context_energy=confidence * 0.5)

    return ConclusionGraph(
        graph_id=graph_id,
        input_hashes=set(context_hashes),
        goal_hashes=goal_hashes,
        node_hashes=node_hashes,
        edge_ids=edge_ids,
        core_hashes={action_hash},
        action_hashes={action_hash},
        bridge_hashes=set(display_hashes),
        support_paths=support_paths,
        goal_paths=goal_paths,
        score=confidence,
        uncertainty=max(0.0, 1.0 - confidence),
        activation=activation,
    )


def _turn_response_edges(
    action_hash: str,
    actor_hash: str,
    target_hash: str,
    display_hashes: list[str],
    context_hashes: set[str],
    confidence: float,
    now: datetime,
) -> list[Edge]:
    edges = [
        _runtime_edge(
            actor_hash,
            action_hash,
            proposed_connect_type="performs_turn_response",
            confidence=confidence,
            now=now,
            role="actor",
        ),
        _runtime_edge(
            action_hash,
            target_hash,
            proposed_connect_type="turn_response_target",
            confidence=confidence,
            now=now,
            role="target",
        ),
    ]
    for display_hash in display_hashes:
        edges.append(
            _runtime_edge(
                action_hash,
                display_hash,
                proposed_connect_type="turn_response_target_display",
                confidence=confidence,
                now=now,
                role="target_display",
            )
        )
    for context_hash in sorted(context_hashes):
        edges.append(
            _runtime_edge(
                context_hash,
                action_hash,
                proposed_connect_type="turn_response_context",
                confidence=confidence * 0.75,
                now=now,
                role="input_context",
            )
        )
    return edges


def _runtime_edge(
    source_hash: str,
    target_hash: str,
    *,
    proposed_connect_type: str,
    confidence: float,
    now: datetime,
    role: str,
) -> Edge:
    return Edge(
        edge_id=str(uuid.uuid4()),
        source_hash=source_hash,
        target_hash=target_hash,
        edge_family="relation",
        connect_type="flow",
        provenance_source="system_policy",
        proposed_connect_type=proposed_connect_type,
        proposal_reason="turn_response_conclusion_graph",
        translation_confidence=confidence,
        support_count=1,
        trust_score=confidence,
        edge_weight=confidence,
        is_active=True,
        is_temporary=True,
        payload={
            "runtime_view": True,
            "view_scope": RESPONSE_ACTION_VIEW_SCOPE,
            "response_action_edge": True,
            "response_action_role": role,
        },
        created_at=now,
        updated_at=now,
    )


def _translated_input_hashes(translated: TranslatedGraph) -> set[str]:
    hashes: set[str] = set()
    if translated.input_bundle is not None:
        hashes |= set(translated.input_bundle.direct_hashes)
        hashes |= {compute_hash(hint) for hint in translated.input_bundle.empty_hints if hint.strip()}
    for ref in translated.nodes:
        if isinstance(ref, ConceptPointer) and ref.is_direct_input_match:
            hashes.add(ref.address_hash)
        elif isinstance(ref, EmptySlot) and ref.concept_hint.strip():
            hashes.add(compute_hash(ref.concept_hint.strip()))
    return hashes


def _stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


def _format_hashes(hashes) -> str:
    return "[" + ",".join(str(h)[:10] for h in hashes) + "]"
