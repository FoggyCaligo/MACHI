from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class IntentSnapshot:
    drive_name: str = 'user_delight'
    live_intent: str = 'graph_grounded_reasoning'
    snapshot_intent: str = 'graph_grounded_reasoning'
    previous_snapshot_intent: str | None = None
    shifted: bool = False
    continuation: bool = False
    shift_reason: str | None = None
    sufficiency_score: float = 0.0
    stop_threshold: float = 0.62
    should_stop: bool = False
    evidence: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_metadata(self) -> dict[str, Any]:
        return {
            'drive_name': self.drive_name,
            'live_intent': self.live_intent,
            'snapshot_intent': self.snapshot_intent,
            'previous_snapshot_intent': self.previous_snapshot_intent,
            'shifted': self.shifted,
            'continuation': self.continuation,
            'shift_reason': self.shift_reason,
            'sufficiency_score': round(self.sufficiency_score, 6),
            'stop_threshold': round(self.stop_threshold, 6),
            'should_stop': self.should_stop,
            'evidence': list(self.evidence),
            'metadata': dict(self.metadata),
        }
