from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal


NodeKind = Literal["concept", "relation", "event", "goal"]
FormationSource = Literal["ingest", "differentiation", "search"]


@dataclass(slots=True)
class Node:
    address_hash: str
    node_kind: NodeKind
    formation_source: FormationSource
    labels: list[str] = field(default_factory=list)
    is_abstract: bool = False          # 공통부 추출로 형성된 레이블 없는 구조 노드
    trust_score: float = 0.5
    stability_score: float = 0.5
    is_active: bool = True
    embedding: list[float] | None = None
    payload: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # ── 직렬화 헬퍼 ─────────────────────────────────────────────────────────

    def labels_json(self) -> str:
        return json.dumps(self.labels, ensure_ascii=False)

    def payload_json(self) -> str:
        return json.dumps(self.payload, ensure_ascii=False)

    @staticmethod
    def labels_from_json(s: str) -> list[str]:
        v = json.loads(s)
        return v if isinstance(v, list) else []

    @staticmethod
    def payload_from_json(s: str) -> dict:
        v = json.loads(s)
        return v if isinstance(v, dict) else {}

    def primary_label(self) -> str:
        """언어화 시 첫 번째 레이블을 대표값으로 사용. 없으면 빈 문자열."""
        return self.labels[0] if self.labels else ""

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc)
