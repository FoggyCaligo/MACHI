from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from .edge import EdgeFamily, ConnectType

if TYPE_CHECKING:
    from .node import Node
    from .edge import Edge


ResolutionSource = Literal["exact_match", "semantic_local_candidate", "search_ingest", "profile_context", "unknown"]


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

    address_hash: 노드 식별자 (WorldGraph 조회 키).
    local_subgraph: 해당 노드 중심의 N-hop 국소 그래프 (TempThoughtGraph 로드용).
    importance: 문장 centroid 임베딩과의 cosine 유사도 기반 중요도 점수.
                ThoughtEngine이 key_hashes / ref_hashes 분류에 사용한다.
    resolution_source:
        - exact_match: 현재 입력 token surface가 words table과 직접 일치
        - semantic_local_candidate: exact match로 로드된 local graph 내부 후보와 임베딩 유사도로 연결
        - search_ingest/profile_context: 후속 단계용 예약값
    """

    address_hash: str
    local_subgraph: LocalSubgraph
    importance: float = 0.0
    resolution_source: ResolutionSource = "unknown"

    @property
    def is_direct_input_match(self) -> bool:
        return self.resolution_source == "exact_match"


@dataclass(slots=True)
class EmptySlot:
    """그래프에서 찾지 못한 개념 자리.

    번역 시점에 즉시 검색하지 않는다.
    Think 루프가 필요 시 직접 처리한다.

    importance: 문장 centroid 기반 중요도 점수.
                ingest 후 ThoughtEngine의 key/ref 분류에 사용된다.
    """

    concept_hint: str    # 번역하려 했던 의미 단위 (원문 토큰 또는 구)
    unfound: bool = True
    importance: float = 0.0


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
class InputGraphBundle:
    """현재 사용자 입력을 국소그래프 묶음으로 표현한 1단계 산출물.

    LangToGraph가 이미 만든 ConceptPointer/TranslatedEdge를 버리지 않고,
    입력 전체를 임시 사고 그래프의 단위로 명시한다.
    """

    source: str
    center_hashes: set[str] = field(default_factory=set)
    direct_hashes: set[str] = field(default_factory=set)
    context_hashes: set[str] = field(default_factory=set)
    empty_hints: list[str] = field(default_factory=list)
    local_subgraphs: list[LocalSubgraph] = field(default_factory=list)
    sentence_edges: list[TranslatedEdge] = field(default_factory=list)


@dataclass(slots=True)
class TranslatedGraph:
    """LangToGraph의 최종 반환값.

    언어 입력 한 단위(문장 또는 구)를 그래프 표현으로 번역한 결과다.
    저장이 아니라 번역이므로 World Graph는 변경되지 않는다.

    nodes: 문장에서 추출된 모든 ConceptRef (ConceptPointer + EmptySlot).
           중요도 필터링 없이 전체를 포함한다.
           각 ref의 importance 필드에 centroid 기반 중요도 점수가 담겨 있다.
           ThoughtEngine이 이 점수를 사용해 key/ref 분류를 수행한다.
    input_bundle: 현재 입력을 국소그래프 묶음으로 명시한 view.
                  1단계에서는 기존 nodes/edges와 동치 정보를 구조화해 보존한다.
    """

    nodes: list[ConceptRef]
    edges: list[TranslatedEdge]
    source: str    # 원문 (provenance용)
    input_bundle: InputGraphBundle | None = None
