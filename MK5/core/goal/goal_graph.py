from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone

from ..entities.edge import Edge
from ..entities.node import Node
from ..storage.world_graph import (
    get_edge_by_endpoints,
    get_node,
    insert_edge,
    insert_node,
    update_edge,
    update_node,
)
from .goal_view import GoalAxisRef, GoalView


GOAL_ROOT_HASH = hashlib.sha256(b"goal::machi_ai_intent").hexdigest()[:32]


@dataclass(frozen=True, slots=True)
class GoalAxisSeed:
    """GlobalGoalGraph 초기 목표 축 seed.

    label_key는 안정적 bootstrap 식별자다. Runtime 판단은 이 문자열이 아니라
    생성된 노드/엣지 구조를 통해 이루어져야 한다.
    """

    label_key: str
    labels: tuple[str, ...]
    priority_rank: int
    edge_weight: float
    description: str

    @property
    def node_hash(self) -> str:
        return _stable_hash(f"goal-axis::{self.label_key}")

    @property
    def edge_id(self) -> str:
        return _stable_hash(f"goal-edge::{GOAL_ROOT_HASH}->{self.node_hash}")


GLOBAL_GOAL_AXIS_SEEDS: tuple[GoalAxisSeed, ...] = (
    GoalAxisSeed(
        label_key="honesty",
        labels=("정직성", "Honesty"),
        priority_rank=1,
        edge_weight=1.00,
        description="모르는 것은 모른다고 말하고, 확실하지 않은 것은 불확실하다고 표시한다.",
    ),
    GoalAxisSeed(
        label_key="accuracy",
        labels=("정확성", "Accuracy"),
        priority_rank=2,
        edge_weight=0.95,
        description="사실, 코드, 구조, 논리의 오류를 가능한 한 줄인다.",
    ),
    GoalAxisSeed(
        label_key="long_term_user_benefit",
        labels=("사용자 장기 이익", "Long-term user benefit"),
        priority_rank=3,
        edge_weight=0.90,
        description="즉각적인 만족보다 사용자의 장기적 이해와 문제 해결에 유리한 방향을 우선한다.",
    ),
    GoalAxisSeed(
        label_key="structural_understanding",
        labels=("구조적 이해", "Structural understanding"),
        priority_rank=4,
        edge_weight=0.85,
        description="단편 답변보다 구조, 메커니즘, 관계, 적용 가능성을 설명한다.",
    ),
    GoalAxisSeed(
        label_key="actionability",
        labels=("실행 가능성", "Actionability"),
        priority_rank=5,
        edge_weight=0.80,
        description="필요한 경우 사용자가 실제로 적용할 수 있는 형태로 정리한다.",
    ),
    GoalAxisSeed(
        label_key="context_continuity",
        labels=("맥락 유지", "Context continuity"),
        priority_rank=6,
        edge_weight=0.75,
        description="현재 대화 흐름, 이전 결정, 프로젝트 철학을 유지한다.",
    ),
    GoalAxisSeed(
        label_key="natural_expression",
        labels=("표현의 자연스러움", "Natural expression"),
        priority_rank=7,
        edge_weight=0.70,
        description="최종 응답을 사용자가 이해 가능한 언어로 표현한다.",
    ),
)


def _stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


def initialize_global_goal_graph(conn) -> GoalView:
    """GlobalGoalGraph를 WorldGraph에 idempotent하게 bootstrap한다.

    이 함수는 GoalRoot와 7개 global goal axis, 그리고 GoalRoot → axis edge를
    보장한다. 여러 번 호출해도 중복 node/edge를 만들지 않는다.

    단기 호환을 위해 GoalRoot는 node_kind="goal"을 유지한다. 하위 목표 축은
    concept node로 둔다. Goal 의미의 본체는 node_kind가 아니라 root→axis edge다.
    """
    now = datetime.now(timezone.utc)
    root = _ensure_goal_root(conn, now)
    axis_refs: list[GoalAxisRef] = []

    for seed in GLOBAL_GOAL_AXIS_SEEDS:
        axis_node = _ensure_goal_axis_node(conn, seed, now)
        edge = _ensure_goal_axis_edge(conn, root.address_hash, seed, now)
        axis_refs.append(
            GoalAxisRef(
                label_key=seed.label_key,
                node=axis_node,
                edge_from_root=edge,
                priority_rank=seed.priority_rank,
            )
        )

    conn.commit()
    return GoalView(root_node=root, axis_refs=tuple(axis_refs))


def load_goal_view(conn) -> GoalView | None:
    """이미 bootstrap된 GlobalGoalGraph를 읽기 전용 GoalView로 조회한다."""
    root = get_node(conn, GOAL_ROOT_HASH)
    if root is None or not root.is_active:
        return None

    axis_refs: list[GoalAxisRef] = []
    for seed in GLOBAL_GOAL_AXIS_SEEDS:
        axis_node = get_node(conn, seed.node_hash)
        edge = get_edge_by_endpoints(conn, root.address_hash, seed.node_hash)
        if axis_node is None or edge is None or not axis_node.is_active or not edge.is_active:
            continue
        axis_refs.append(
            GoalAxisRef(
                label_key=seed.label_key,
                node=axis_node,
                edge_from_root=edge,
                priority_rank=seed.priority_rank,
            )
        )

    return GoalView(root_node=root, axis_refs=tuple(axis_refs))


def _ensure_goal_root(conn, now: datetime) -> Node:
    existing = get_node(conn, GOAL_ROOT_HASH)
    if existing is not None:
        if not existing.is_active:
            existing.is_active = True
            existing.touch()
            update_node(conn, existing)
        return existing

    root = Node(
        address_hash=GOAL_ROOT_HASH,
        node_kind="goal",
        formation_source="system_policy",
        labels=["GoalRoot", "목표", "AI_intent"],
        is_abstract=False,
        trust_score=1.0,
        stability_score=1.0,
        is_active=True,
        embedding=None,
        payload={
            "policy": "global_goal_root",
            "note": "Goal 의미의 본체는 이 label이 아니라 GoalRoot에서 하위 목표 축으로 향하는 edge 구조다.",
        },
        created_at=now,
        updated_at=now,
    )
    insert_node(conn, root)
    return root


def _ensure_goal_axis_node(conn, seed: GoalAxisSeed, now: datetime) -> Node:
    existing = get_node(conn, seed.node_hash)
    if existing is not None:
        changed = False
        if not existing.is_active:
            existing.is_active = True
            changed = True
        if existing.payload.get("goal_axis") != seed.label_key:
            existing.payload["goal_axis"] = seed.label_key
            existing.payload["priority_rank"] = seed.priority_rank
            existing.payload["description"] = seed.description
            changed = True
        if changed:
            existing.touch()
            update_node(conn, existing)
        return existing

    node = Node(
        address_hash=seed.node_hash,
        node_kind="concept",
        formation_source="system_policy",
        labels=list(seed.labels),
        is_abstract=False,
        trust_score=1.0,
        stability_score=1.0,
        is_active=True,
        embedding=None,
        payload={
            "goal_axis": seed.label_key,
            "priority_rank": seed.priority_rank,
            "description": seed.description,
            "note": "목표 축 label은 표현 힌트이며, Goal 의미의 본체는 GoalRoot와의 edge 구조다.",
        },
        created_at=now,
        updated_at=now,
    )
    insert_node(conn, node)
    return node


def _ensure_goal_axis_edge(
    conn,
    root_hash: str,
    seed: GoalAxisSeed,
    now: datetime,
) -> Edge:
    existing = get_edge_by_endpoints(conn, root_hash, seed.node_hash)
    if existing is not None:
        changed = False
        if not existing.is_active:
            existing.is_active = True
            changed = True
        if existing.provenance_source != "system_policy":
            existing.provenance_source = "system_policy"
            changed = True
        if existing.edge_family != "relation":
            existing.edge_family = "relation"
            changed = True
        if existing.connect_type != "flow":
            existing.connect_type = "flow"
            changed = True
        if existing.edge_weight != seed.edge_weight:
            existing.edge_weight = seed.edge_weight
            changed = True
        if existing.payload.get("goal_axis") != seed.label_key:
            existing.payload["goal_axis"] = seed.label_key
            existing.payload["priority_rank"] = seed.priority_rank
            existing.payload["description"] = seed.description
            changed = True
        if changed:
            existing.touch()
            update_edge(conn, existing)
        return existing

    edge = Edge(
        edge_id=seed.edge_id,
        source_hash=root_hash,
        target_hash=seed.node_hash,
        edge_family="relation",
        connect_type="flow",
        provenance_source="system_policy",
        proposed_connect_type="goal_axis",
        proposal_reason="GlobalGoalGraph bootstrap",
        support_count=1,
        conflict_count=0,
        contradiction_pressure=0.0,
        trust_score=1.0,
        edge_weight=seed.edge_weight,
        is_active=True,
        is_temporary=False,
        payload={
            "goal_axis": seed.label_key,
            "priority_rank": seed.priority_rank,
            "description": seed.description,
        },
        created_at=now,
        updated_at=now,
    )
    insert_edge(conn, edge)
    return edge
