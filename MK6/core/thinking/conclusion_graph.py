from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


PathDirection = Literal["forward", "reverse"]
ConclusionGraphKind = Literal["answer", "correction"]
RejectionReason = Literal[
    "input_restatement",
    "insufficient_goal_alignment",
    "insufficient_support",
    "conflict_dominant",
    "superseded_by_better_graph",
]


@dataclass(slots=True)
class ActivationState:
    """Think 루프의 다축 activation 상태.

    Activation은 결론 그 자체가 아니다. 노드/엣지 위로 퍼지는 임시 상태이며,
    최종 결론은 이 상태를 근거로 선택된 국소 그래프(ConclusionGraph)다.
    """

    input_energy: float = 0.0
    goal_energy: float = 0.0
    context_energy: float = 0.0
    evidence_energy: float = 0.0
    conflict_pressure: float = 0.0
    novelty_score: float = 0.0

    @property
    def support_energy(self) -> float:
        return self.input_energy + self.goal_energy + self.context_energy + self.evidence_energy

    @property
    def net_energy(self) -> float:
        return self.support_energy - self.conflict_pressure

    @property
    def is_goal_aligned(self) -> bool:
        return self.input_energy > 0 and self.goal_energy > 0


@dataclass(frozen=True, slots=True)
class ReasoningStep:
    """국소 그래프 안에서 한 edge를 따라 이동한 기록."""

    source_hash: str
    edge_id: str
    target_hash: str
    direction: PathDirection = "forward"
    weight: float = 1.0


@dataclass(frozen=True, slots=True)
class ReasoningPath:
    """입력/Goal/evidence/conflict와 conclusion graph를 잇는 경로.

    경로는 문자열 설명이 아니라 node_hash/edge_id의 구조적 기록이다.
    """

    start_hash: str
    end_hash: str
    steps: tuple[ReasoningStep, ...] = ()
    path_weight: float = 1.0

    @property
    def node_hashes(self) -> tuple[str, ...]:
        if not self.steps:
            return (self.start_hash, self.end_hash) if self.start_hash != self.end_hash else (self.start_hash,)
        hashes = [self.start_hash]
        for step in self.steps:
            hashes.append(step.target_hash if step.direction == "forward" else step.source_hash)
        return tuple(hashes)

    @property
    def edge_ids(self) -> tuple[str, ...]:
        return tuple(step.edge_id for step in self.steps)


@dataclass(slots=True)
class ConclusionGraph:
    """답변에 사용될 결론 국소 그래프.

    Machi에서 결론은 단일 노드가 아니다. 입력 그래프와 Goal 그래프 사이에서
    선택된 node/edge 집합이며, 조건/예외/행동/bridge까지 포함하는 구조다.

    role 필드는 node_kind가 아니다. 같은 노드라도 다른 ConclusionGraph 안에서는
    다른 역할을 가질 수 있다. 역할은 이 결론 그래프 내부의 위치와 경로에서 나온다.
    """

    graph_id: str
    graph_kind: ConclusionGraphKind = "answer"
    input_hashes: set[str] = field(default_factory=set)
    goal_hashes: set[str] = field(default_factory=set)
    node_hashes: set[str] = field(default_factory=set)
    edge_ids: set[str] = field(default_factory=set)

    core_hashes: set[str] = field(default_factory=set)
    condition_hashes: set[str] = field(default_factory=set)
    exception_hashes: set[str] = field(default_factory=set)
    action_hashes: set[str] = field(default_factory=set)
    bridge_hashes: set[str] = field(default_factory=set)

    support_paths: list[ReasoningPath] = field(default_factory=list)
    goal_paths: list[ReasoningPath] = field(default_factory=list)
    conflict_paths: list[ReasoningPath] = field(default_factory=list)
    contrast_paths: list[ReasoningPath] = field(default_factory=list)

    score: float = 0.0
    uncertainty: float = 0.0
    activation: dict[str, ActivationState] = field(default_factory=dict)

    @property
    def is_goal_aligned(self) -> bool:
        return bool(self.input_hashes and self.goal_hashes and self.node_hashes)

    @property
    def has_non_input_structure(self) -> bool:
        return bool(self.node_hashes - self.input_hashes)

    @property
    def is_likely_restatement(self) -> bool:
        """입력 그래프 반복 가능성.

        문자열 유사도가 아니라 구조 기준이다. 입력 밖 구조가 없고, goal/support path가
        부족하면 재진술 후보로 본다. 최종 판정은 ThinkEngine의 graph-level scoring이 한다.
        """
        return (
            not self.has_non_input_structure
            and not self.goal_paths
            and not self.support_paths
            and not self.condition_hashes
            and not self.exception_hashes
            and not self.action_hashes
        )


@dataclass(slots=True)
class RejectedConclusionGraph:
    """후보였지만 최종 결론에서 제외/강등된 국소 그래프."""

    graph: ConclusionGraph
    reason: RejectionReason
    competing_graph_id: str | None = None
    notes: list[str] = field(default_factory=list)
