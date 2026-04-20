"""HashResolver — 토큰 → address_hash 변환."""
from __future__ import annotations

import hashlib
import re
import unicodedata


# ── 정규화 ────────────────────────────────────────────────────────────────────

# 한국어 조사 목록 (제거 대상)
_KO_PARTICLES: frozenset[str] = frozenset({
    "은", "는", "이", "가", "을", "를", "에", "의",
    "도", "로", "으로", "와", "과", "이나", "나",
    "에서", "부터", "까지", "만", "도", "한테", "께",
})

# scope prefix — 의미 그래프 노드 해시와의 충돌 방지
_SCOPE_PREFIX = "word::"


def normalize_text(token: str) -> str:
    """토큰을 해시 계산에 쓸 정규화 형태로 변환한다.

    처리 순서:
    1. 유니코드 NFC 정규화
    2. 소문자 변환
    3. 앞뒤 공백/구두점 제거
    4. 한국어 조사 제거 (토큰 전체가 조사인 경우는 그대로 유지)
    """
    s = unicodedata.normalize("NFC", token)
    s = s.lower().strip().strip(".,!?;:'\"-()[]{}…")

    # 한국어 조사 제거: 토큰이 "단어+조사" 형태인 경우만 제거
    # 토큰 자체가 순수 조사인 경우(1자 조사 등)는 그대로 유지
    for particle in sorted(_KO_PARTICLES, key=len, reverse=True):
        if s.endswith(particle) and len(s) > len(particle):
            s = s[: -len(particle)]
            break

    return s


def compute_hash(token: str) -> str:
    """정규화된 토큰으로부터 address_hash를 계산한다.

    Returns:
        sha256 hex digest 앞 32자 (128비트)
    """
    normalized = normalize_text(token)
    raw = f"{_SCOPE_PREFIX}{normalized}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
