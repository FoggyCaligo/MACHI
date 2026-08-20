from __future__ import annotations

from dataclasses import dataclass

from ..entities.edge import Edge
from ..entities.node import Node


@dataclass(frozen=True, slots=True)
class GoalAxisRef:
    """GlobalGoalGraph의 하위 목표 축 조회 결과.

    이 객체는 의미 본체가 아니다. 의미 본체는 GoalRoot와 axis_node 사이의
    edge 구조다. label_key는 디버깅/문서화용 안정 식별자에 가깝다.
    """

    label_key: str
    node: Node
    edge_from_root: Edge
    priority_rank: int


@dataclass(frozen=True, slots=True)
class GoalView:
    """GoalRoot 중심 목표 그래프의 읽기 전용 조회 결과.

    GoalView는 WorldGraph/TempThoughtGraph의 구조를 다루기 위한 projection이며,
    판단의 본체가 아니다. ThinkEngine은 이 값을 읽어서 목표 방향의 후보 경로를
    평가할 수 있지만, GoalView 자체를 WorldGraph에 저장하지 않는다.
    """

    root_node: Node
    axis_refs: tuple[GoalAxisRef, ...]

    @property
    def root_hash(self) -> str:
        return self.root_node.address_hash

    @property
    def global_goal_hashes(self) -> set[str]:
        return {axis.node.address_hash for axis in self.axis_refs}

    def axis_hash_by_key(self, label_key: str) -> str | None:
        for axis in self.axis_refs:
            if axis.label_key == label_key:
                return axis.node.address_hash
        return None
