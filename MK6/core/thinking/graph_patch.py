from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


PatchOp = Literal["add", "update", "remove", "merge", "fill_slot"]
PatchTargetKind = Literal["node", "edge", "slot", "pair"]


@dataclass(frozen=True, slots=True)
class GraphPatch:
    """현재 사고 턴에서 발생한 그래프 수정 단위.

    GraphPatch는 응답 타입이나 의미 ontology가 아니라, TempThoughtGraph 위에서 실제로
    일어난 구조 변경을 추적하는 실행 단위다.
    """

    op: PatchOp
    target_kind: PatchTargetKind
    target_id: str
    source_hash: str | None = None
    target_hash: str | None = None
    before: dict[str, Any] = field(default_factory=dict)
    after: dict[str, Any] = field(default_factory=dict)
    reason: str | None = None
    loop_index: int = 0

    @property
    def structural_key(self) -> tuple[str, str, str | None, str | None]:
        return (self.op, self.target_kind, self.source_hash, self.target_hash)


def patch_overlap_ratio(previous: list[GraphPatch], current: list[GraphPatch]) -> float:
    """두 patch 집합의 구조적 중복 비율을 계산한다.

    문자열 설명이 아니라 GraphPatch.structural_key를 기준으로 비교한다.
    current가 비어 있으면 더 진행할 수정이 없다고 보고 1.0을 반환한다.
    """
    if not current:
        return 1.0
    previous_keys = {patch.structural_key for patch in previous}
    if not previous_keys:
        return 0.0
    current_keys = [patch.structural_key for patch in current]
    overlap_count = sum(1 for key in current_keys if key in previous_keys)
    return overlap_count / len(current_keys)
