from __future__ import annotations

import asyncio
import hashlib
import math
import uuid
from dataclasses import dataclass
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
MIN_ACTION_SCORE = 0.20
MIN_ACTION_MARGIN = 0.01

_ACTION_PROTOTYPES: dict[str, tuple[str, ...]] = {
    "greeting": (
        "사용자가 대화를 시작하며 인사했다. AI는 현재 사용자에게 인사로 응답한다.",
        "대화 상대가 자신을 소개하며 인사했다. AI는 그 사람에게 반갑게 인사한다.",
        "The user greeted the assistant. The assistant should greet the current user.",
    ),
    "answer_request": (
        "사용자가 정보나 설명을 요청했다. AI는 질문에 대한 내용을 답한다.",
        "The user asked a question and expects an informative answer.",
    ),
    "perform_request": (
        "사용자가 작업 수행을 요청했다. AI는 요청된 작업을 진행한다.",
        "The user requested an action, edit, or implementation from the assistant.",
    ),
    "context_update": (
        "사용자가 새 정보를 제공했다. AI는 대화 맥락과 세계 그래프를 갱신한다.",
        "The user provided contextual information for memory or state update.",
    ),
}

_proto_cache: dict[str, list[float]] | None = None
_proto_lock = asyncio.Lock()


@dataclass(frozen=True, slots=True)
class ResponseActionDecision:
    action_family: str
    score: float
    second_score: float

    @property
    def margin(self) -> float:
        return self.score - self.second_score

    @property
    def is_confident(self) -> bool:
        return self.score >= MIN_ACTION_SCORE and self.margin >= MIN_ACTION_MARGIN


async def build_response_action_graph(
    conclusion: "ConclusionView",
    translated: TranslatedGraph,
    profile_activation_view: ProfileActivationView | None,
    embed_fn: EmbedFn,
) -> ConclusionGraph | None:
    """selected 결론이 비어 있을 때 응답 행위 결론 그래프를 만든다.

    이 계층은 특정 표면 문자열 포함 여부를 보지 않는다. 현재 입력 전체의 임베딩을
    response action prototype들과 비교하고, ProfileActivationView의 구조화된 display
    후보를 target display로 사용한다.
    """
    decision = await _classify_response_action(translated.source, embed_fn)
    print(
        f"[response_action] candidate={decision.action_family} "
        f"score={decision.score:.4f} second={decision.second_score:.4f} "
        f"margin={decision.margin:.4f}"
    )
    if not decision.is_confident:
        print("[response_action] rejected reason=low_confidence")
        return None
    if decision.action_family != "greeting":
        print("[response_action] rejected reason=no_response_action_graph_for_family")
        return None

    node_map = {node.address_hash: node for node in conclusion.nodes}
    display_hashes = _rank_target_display_hashes(profile_activation_view, node_map)
    graph = _make_greeting_response_graph(
        conclusion,
        translated,
        display_hashes=display_hashes,
        confidence=decision.score,
    )
    print(
        f"[response_action] selected graph={graph.graph_id} "
        f"action=greeting target_display={_format_hashes(display_hashes)}"
    )
    return graph


async def _classify_response_action(source: str, embed_fn: EmbedFn) -> ResponseActionDecision:
    input_emb, proto_embs = await asyncio.gather(
        embed_fn(source),
        _prototype_embeddings(embed_fn),
    )
    scores = {
        action_family: _cosine(input_emb, proto_emb)
        for action_family, proto_emb in proto_embs.items()
    }
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    best_family, best_score = ranked[0]
    second_score = ranked[1][1] if len(ranked) > 1 else 0.0
    return ResponseActionDecision(best_family, best_score, second_score)


async def _prototype_embeddings(embed_fn: EmbedFn) -> dict[str, list[float]]:
    global _proto_cache
    if _proto_cache is not None:
        return _proto_cache
    async with _proto_lock:
        if _proto_cache is not None:
            return _proto_cache
        action_families = list(_ACTION_PROTOTYPES)
        prototype_texts = ["\n".join(_ACTION_PROTOTYPES[family]) for family in action_families]
        embeddings = await asyncio.gather(*[embed_fn(text) for text in prototype_texts])
        _proto_cache = dict(zip(action_families, embeddings))
        return _proto_cache


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        raise ValueError("Cannot compare zero-length embedding vector for response action classification")
    return dot / (na * nb)


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


def _make_greeting_response_graph(
    conclusion: "ConclusionView",
    translated: TranslatedGraph,
    *,
    display_hashes: list[str],
    confidence: float,
) -> ConclusionGraph:
    now = datetime.now(timezone.utc)
    target_hash = ANCHOR_USER
    actor_hash = ANCHOR_ASSISTANT
    action_hash = _stable_hash("response-action::greeting::assistant-to-current-user")

    action_node = Node(
        address_hash=action_hash,
        node_kind="event",
        formation_source="system_policy",
        labels=["인사하기", "greeting_response"],
        is_abstract=False,
        trust_score=confidence,
        stability_score=0.2,
        is_active=True,
        payload={
            "runtime_view": True,
            "response_action": True,
            "action_family": "greeting",
            "actor_hash": actor_hash,
            "target_hash": target_hash,
            "target_display_hashes": list(display_hashes),
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
    for edge in _response_action_edges(action_hash, actor_hash, target_hash, display_hashes, confidence, now):
        conclusion.edges.append(edge)
        edge_ids.add(edge.edge_id)

    input_hashes = _translated_input_hashes(translated)
    goal_hashes = {conclusion.goal_hash} if conclusion.goal_hash else set()
    node_hashes = {action_hash, actor_hash, target_hash, *display_hashes}

    first_input_hash = next(iter(sorted(input_hashes)), None)
    support_paths: list[ReasoningPath] = []
    if first_input_hash is not None:
        support_paths.append(ReasoningPath(start_hash=first_input_hash, end_hash=action_hash, steps=(), path_weight=confidence))

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

    return ConclusionGraph(
        graph_id=graph_id,
        input_hashes=input_hashes,
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


def _response_action_edges(
    action_hash: str,
    actor_hash: str,
    target_hash: str,
    display_hashes: list[str],
    confidence: float,
    now: datetime,
) -> list[Edge]:
    edges = [
        _runtime_edge(
            actor_hash,
            action_hash,
            proposed_connect_type="performs_response_action",
            confidence=confidence,
            now=now,
            role="actor",
        ),
        _runtime_edge(
            action_hash,
            target_hash,
            proposed_connect_type="response_action_target",
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
                proposed_connect_type="response_action_target_display",
                confidence=confidence,
                now=now,
                role="target_display",
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
        proposal_reason="response_action_conclusion_graph",
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


def _format_hashes(hashes: list[str]) -> str:
    return "[" + ",".join(h[:10] for h in hashes) + "]"
