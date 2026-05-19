"""GoalAlignment — 임시 사고 그래프가 목적 그래프와 얼마나 만나는지 점수화한다.

수렴 판단은 단순히 그래프가 변했는지 여부만으로 보면 안 된다. 같은 수정이 반복되더라도
그 수정이 목적 그래프 쪽으로 계속 개선되고 있다면 루프를 유지해야 하고, 반대로 수정은
반복되지만 goal alignment가 거의 개선되지 않으면 사고를 멈춰야 한다.

이 모듈은 문자열 의미론을 보지 않는다. 입력 source, goal source, bounded activation path가
만나는 구조적 정도만 점수화한다.
"""
from __future__ import annotations

from dataclasses import dataclass

from ... import config
from ..entities.translated_graph import TranslatedGraph
from .activation import (
    _candidate_score,
    _combine_activation,
    _goal_source_hashes,
    _spread,
    _translated_hashes,
)
from .temp_thought_graph import TempThoughtGraph


@dataclass(frozen=True, slots=True)
class GoalAlignmentSnapshot:
    score: float
    aligned_count: int
    input_count: int
    goal_count: int


def score_goal_alignment(
    tg: TempThoughtGraph,
    translated: TranslatedGraph,
    *,
    conn,
    previous_key_hashes: set[str] | None = None,
    max_hops: int | None = None,
) -> GoalAlignmentSnapshot:
    """현재 임시 그래프의 목적 정렬 점수를 계산한다.

    score는 입력 activation과 goal activation이 만나는 후보들의 구조 점수 중 최대값이다.
    평균이나 합계를 쓰지 않는 이유는, 결론그래프는 모든 입력 노드의 평균이 아니라
    목적과 만나는 유효한 국소 그래프를 중심으로 선택되기 때문이다.
    """
    max_hops = config.THINK_ACTIVATION_HOPS if max_hops is None else max_hops

    input_sources = _translated_hashes(translated, tg)
    goal_sources = _goal_source_hashes(tg, conn)
    context_sources = {h for h in (previous_key_hashes or set()) if tg.get_node(h) is not None}

    if not input_sources or not goal_sources:
        return GoalAlignmentSnapshot(
            score=0.0,
            aligned_count=0,
            input_count=len(input_sources),
            goal_count=len(goal_sources),
        )

    input_paths = _spread(tg, input_sources, max_hops=max_hops)
    goal_paths = _spread(tg, goal_sources, max_hops=max_hops)
    context_paths = _spread(tg, context_sources, max_hops=max_hops)
    activation = _combine_activation(input_paths, goal_paths, context_paths, input_sources)

    meeting_hashes = [
        h for h, state in activation.items()
        if state.input_energy > 0 and state.goal_energy > 0 and h not in goal_sources
    ]
    if not meeting_hashes:
        return GoalAlignmentSnapshot(
            score=0.0,
            aligned_count=0,
            input_count=len(input_sources),
            goal_count=len(goal_sources),
        )

    best_score = max(
        _candidate_score(h, activation[h], input_sources)
        for h in meeting_hashes
    )
    return GoalAlignmentSnapshot(
        score=best_score,
        aligned_count=len(meeting_hashes),
        input_count=len(input_sources),
        goal_count=len(goal_sources),
    )
