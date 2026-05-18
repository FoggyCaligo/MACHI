from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..entities.node import Node
from ..entities.translated_graph import InputGraphBundle, TranslatedGraph
from .goal_view import GoalView


@dataclass(frozen=True, slots=True)
class TurnGoalView:
    """이번 턴 목적 view.

    TurnGoalView는 WorldGraph에 저장되는 의미 본체가 아니라 ThoughtEngine이 읽는
    임시 projection이다. 응답 타입 enum을 만들지 않고, 입력 그래프와 장기 목적
    그래프를 연결하는 최소 목적 구조만 제공한다.
    """

    source: str
    turn_goal_node: Node
    input_center_hashes: set[str] = field(default_factory=set)
    input_direct_hashes: set[str] = field(default_factory=set)
    input_context_hashes: set[str] = field(default_factory=set)
    empty_hints: list[str] = field(default_factory=list)
    long_term_goal_hashes: set[str] = field(default_factory=set)

    @property
    def turn_goal_hash(self) -> str:
        return self.turn_goal_node.address_hash


def build_turn_goal_view(translated: TranslatedGraph, goal_view: GoalView) -> TurnGoalView:
    """TranslatedGraph와 장기 GoalView에서 이번 턴 목적 view를 만든다."""
    bundle = translated.input_bundle or InputGraphBundle(source=translated.source)
    turn_goal_hash = _turn_goal_hash(translated.source)
    now = datetime.now(timezone.utc)
    node = Node(
        address_hash=turn_goal_hash,
        node_kind="goal",
        formation_source="runtime",
        labels=["TurnGoal", "이번 턴 목적"],
        is_abstract=False,
        trust_score=1.0,
        stability_score=0.2,
        is_active=True,
        embedding=None,
        payload={
            "runtime_view": True,
            "goal_scope": "turn",
            "source": translated.source,
            "note": "이번 턴 입력 그래프와 장기 목적 그래프를 연결하는 임시 목적 view다.",
        },
        created_at=now,
        updated_at=now,
    )
    return TurnGoalView(
        source=translated.source,
        turn_goal_node=node,
        input_center_hashes=set(bundle.center_hashes),
        input_direct_hashes=set(bundle.direct_hashes),
        input_context_hashes=set(bundle.context_hashes),
        empty_hints=list(bundle.empty_hints),
        long_term_goal_hashes=set(goal_view.global_goal_hashes),
    )


def _turn_goal_hash(source: str) -> str:
    return hashlib.sha256(f"turn-goal::{source}".encode("utf-8")).hexdigest()[:32]
