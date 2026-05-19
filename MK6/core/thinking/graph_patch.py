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
