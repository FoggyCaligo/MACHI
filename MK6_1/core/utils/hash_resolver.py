"""Hash utilities for normalized concept and participant-anchor addresses."""
from __future__ import annotations

import hashlib
import unicodedata


_KO_PARTICLES: frozenset[str] = frozenset({
    "은", "는", "이", "가", "을", "를", "의", "에",
    "도", "로", "으로", "와", "과", "나", "랑",
    "에서", "부터", "까지", "만", "보다", "처럼", "께",
})

_SCOPE_PREFIX = "word::"
_PARTICIPANT_SCOPE_PREFIX = "identity_anchor::"

PARTICIPANT_USER = "participant_user"
PARTICIPANT_ASSISTANT = "participant_assistant"
PARTICIPANT_SEARCH = "participant_search"

ANCHOR_USER = hashlib.sha256(f"{_PARTICIPANT_SCOPE_PREFIX}{PARTICIPANT_USER}".encode("utf-8")).hexdigest()[:32]
ANCHOR_ASSISTANT = hashlib.sha256(f"{_PARTICIPANT_SCOPE_PREFIX}{PARTICIPANT_ASSISTANT}".encode("utf-8")).hexdigest()[:32]


def normalize_text(token: str) -> str:
    """Normalize a token before hashing."""
    s = unicodedata.normalize("NFC", token)
    s = s.lower().strip().strip(".,!?;:'\"-()[]{}")

    for particle in sorted(_KO_PARTICLES, key=len, reverse=True):
        if s.endswith(particle) and len(s) > len(particle):
            s = s[: -len(particle)]
            break

    return s


def compute_hash(token: str) -> str:
    """Return the stable world-graph address hash for a token."""
    normalized = normalize_text(token)
    raw = f"{_SCOPE_PREFIX}{normalized}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def participant_anchor_hash(session_id: str, participant_key: str) -> str:
    """Return a session-scoped participant anchor hash."""
    payload = f"{_PARTICIPANT_SCOPE_PREFIX}{session_id}::{participant_key}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]
