from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .edge import EdgeFamily, ConnectType

if TYPE_CHECKING:
    from .node import Node
    from .edge import Edge


# ── 국소 그래프 ───────────────────────────────────────────────────────────────

@dataclass(slots=True)
class LocalSubgraph:
    """특정 노드를 중심으로 N-hop 이내의 노드·엣지 묶음.

    LocalGraphExtractor가 생성한다.
    ConceptPointer에 포함되어 Think 루프에 전달된다.
    """

    center_hash: str
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    hop_radius: int = 2


# ── LangToGraph 반환 타입 ─────────────────────────────────────────────────────

@dataclass(slots=True)
class ConceptPointer:
    """그래프에서 찾은 개념 노드에 대한 참조.

    node_id는 address_hash와 동일하다 (MK6에서 통합).
    local_subgraph는 해당 노드 중심의 N-hop 국소 그래프다.
    """

    address_hash: str
    local_subgraph: LocalSubgraph


@dataclass(slots=True)
class EmptySlot:
    """그래프에서 찾지 못한 개념 자리.

    번역 시점에 즉시 검색하지 않는다.
    Think 루프가 필요 시 직접 처리한다.
    """

    concept_hint: str    # 번역하려 했던 의미 단위 (원문 토큰 또는 구)
    unfound: bool = True


ConceptRef = ConceptPointer | EmptySlot


@dataclass(slots=True)
class TranslatedEdge:
    """LangToGraph가 번역한 관계 하나.

    source_ref / target_ref 각각은 ConceptPointer 또는 EmptySlot이다.
    connect_type이 불확실하면 neutral을 할당하고
    proposed_connect_type에 후보를 보존한다.
    """

    source_ref: ConceptRef
    target_ref: ConceptRef
    edge_family: EdgeFamily
    connect_type: ConnectType
    confidence: float
    proposed_connect_type: str | None = None  # 불확실한 경우 후보 보존


@dataclass(slots=True)
class TranslatedGraph:
    """LangToGraph의 최종 반환값.

    언어 입력 한 단위(문장 또는 구)를 그래프 표현으로 번역한 결과다.
    저장이 아니라 번역이므로 World Graph는 변경되지 않는다.

    near_refs: centroid에 가까운 토큰 그룹 → GraphToLang 핵심 키워드 후보.
    far_refs:  centroid에서 먼 토큰 그룹  → GraphToLang 참고 개념 후보.
    두 그룹은 언어 구조(임베딩 중요도)에만 근거하며, 그래프 상태와 무관하다.
    """

    nodes: list[ConceptRef]
    edges: list[TranslatedEdge]
    source: str                                          # 원문 (provenance용)
    near_refs: list[ConceptRef] = field(default_factory=list)   # 핵심 키워드 후보
    far_refs:  list[ConceptRef] = field(default_factory=list)   # 참고 개념 후보
