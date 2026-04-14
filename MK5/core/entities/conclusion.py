from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ContradictionSignal:
    edge_id: int
    source_node_id: int
    target_node_id: int
    edge_type: str
    severity: str
    reason: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RevisionAction:
    edge_id: int
    action: str
    reason: str
    before_trust: float
    after_trust: float
    before_pressure: float
    after_pressure: float
    deactivated: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ConflictRecord:
    edge_id: int
    source_node_id: int
    target_node_id: int
    edge_type: str
    severity: str
    reason: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TrustChangeRecord:
    edge_id: int
    reason: str
    before_trust: float
    after_trust: float
    before_pressure: float
    after_pressure: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RevisionDecisionRecord:
    edge_id: int
    action: str
    reason: str
    deactivated: bool
    before_trust: float
    after_trust: float
    before_pressure: float
    after_pressure: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class DerivedActionLayer:
    response_mode: str
    answer_goal: str
    suggested_actions: list[str] = field(default_factory=list)
    do_not_claim: list[str] = field(default_factory=list)
    tone_hint: str = 'natural_concise_korean'
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CoreConclusion:
    session_id: str
    message_id: int | None
    user_input_summary: str
    inferred_intent: str
    activated_concepts: list[int] = field(default_factory=list)
    key_relations: list[int] = field(default_factory=list)
    detected_conflicts: list[ConflictRecord] = field(default_factory=list)
    trust_changes: list[TrustChangeRecord] = field(default_factory=list)
    revision_decisions: list[RevisionDecisionRecord] = field(default_factory=list)
    explanation_summary: str = ''
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ThoughtResult:
    session_id: str
    message_id: int | None
    contradiction_signals: list[ContradictionSignal] = field(default_factory=list)
    trust_updates: list[RevisionAction] = field(default_factory=list)
    revision_actions: list[RevisionAction] = field(default_factory=list)
    core_conclusion: CoreConclusion | None = None
    derived_action: DerivedActionLayer | None = None
    summary: str = ''
    metadata: dict[str, Any] = field(default_factory=dict)
