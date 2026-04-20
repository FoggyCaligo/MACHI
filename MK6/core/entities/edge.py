from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal


EdgeFamily = Literal["concept", "relation"]
ConnectType = Literal["flow", "neutral", "opposite", "conflict"]
ProvenanceSource = Literal["lang_to_graph", "model_assertion", "search", "differentiation"]


@dataclass(slots=True)
class Edge:
    edge_id: str                          # UUID
    source_hash: str                      # → nodes.address_hash
    target_hash: str                      # → nodes.address_hash
    edge_family: EdgeFamily
    connect_type: ConnectType
    provenance_source: ProvenanceSource
    proposed_connect_type: str | None = None   # 허용 집합 밖 제안 보존
    proposal_reason: str | None = None
    translation_confidence: float | None = None  # LangToGraph가 할당한 신뢰도
    support_count: int = 0
    conflict_count: int = 0
    contradiction_pressure: float = 0.0
    trust_score: float = 0.5
    edge_weight: float = 1.0
    is_active: bool = True
    is_temporary: bool = False
    payload: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # ── 직렬화 헬퍼 ─────────────────────────────────────────────────────────

    def payload_json(self) -> str:
        return json.dumps(self.payload, ensure_ascii=False)

    @staticmethod
    def payload_from_json(s: str) -> dict:
        v = json.loads(s)
        return v if isinstance(v, dict) else {}

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc)
