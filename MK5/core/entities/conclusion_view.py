from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from core.entities.conclusion import ConflictRecord, RevisionDecisionRecord, TrustChangeRecord

if TYPE_CHECKING:
    from core.entities.edge import Edge
    from core.entities.node import Node


@dataclass(slots=True)
class ConclusionView:
    """Think→Search 루프 종료 후 구성되는 의도 기반 결론 구조.

    CoreConclusion이 루프 내부 전용 중간 산물인 것과 달리,
    ConclusionView는 Verbalization 계층이 유일하게 참조하는 최종 결론 구조다.

    사용자 입력의 핵심 키워드(intent_keywords)를 기준으로 ThoughtView에서
    정합적인 노드/엣지를 룰 기반으로 선별하여 구성된다.
    (MK1 원설계: "의도 필터 → 활성화된 서브그래프 → 정합 수렴 → 결론 구조 → 언어화")
    """

    session_id: str
    message_id: int | None

    # ── 사용자 입력 ───────────────────────────────────────────────────────────
    user_input_summary: str              # 사용자 입력 요약 (최대 180자)

    # ── 의도 ─────────────────────────────────────────────────────────────────
    intent_keywords: list[str]           # 사용자 입력 핵심 키워드 (topic_terms 기반)
    inferred_intent: str                 # 의도 카테고리 (IntentManager 산출)

    # ── 선별된 그래프 구조 ────────────────────────────────────────────────────
    intent_aligned_nodes: list[Node]     # 의도 키워드와 정합적인 노드
    supporting_edges: list[Edge]         # 선별된 정합 엣지
    contradicted_nodes: list[Node]       # 저신뢰/충돌로 제외된 노드
    logical_sequence: list[int]          # 노드 ID 논리 순서 (trust_score 내림차순)
    confidence: float                    # 선별 노드 평균 trust_score

    # ── Verbalization 호환 필드 (선별 구조에서 파생, 빌드 시 채워짐) ──────────
    activated_concepts: list[int]        # intent_aligned_nodes의 node ID 목록
    key_relations: list[int]             # supporting_edges의 edge ID 목록
    explanation_summary: str             # 룰 기반 생성된 구조적 설명 요약

    # ── Think 결과 레코드 (TemplateVerbalizer 참조용) ─────────────────────────
    detected_conflicts: list[ConflictRecord] = field(default_factory=list)
    trust_changes: list[TrustChangeRecord] = field(default_factory=list)
    revision_decisions: list[RevisionDecisionRecord] = field(default_factory=list)

    # ── 메타데이터 ────────────────────────────────────────────────────────────
    metadata: dict[str, Any] = field(default_factory=dict)
    # metadata 주요 키 (CoreConclusion.metadata에서 pass-through):
    #   search_context       - _attach_search_context()가 채움
    #   intent_snapshot      - IntentSnapshot.to_metadata()
    #   topic_terms          - intent_keywords와 동일 출처
    #   previous_topic_terms
    #   topic_continuity
    #   previous_tone_hint
    #   recent_memory_messages
    #   recent_memory_count
