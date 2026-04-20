"""TokenSplitter — 자연어 문자열을 토큰 목록으로 분리한다."""
from __future__ import annotations

import re


# ── 문장 분리 ─────────────────────────────────────────────────────────────────

_SENTENCE_SPLIT_RE = re.compile(
    r"(?:\r?\n)+"                          # 개행
    r"|(?<=[.!?])\s+"                      # 기본 영어 종결
    r"|(?<=[。．｡])"                       # CJK 마침표
    r"|(?<=[！？｢｣])\s*"                  # 전각 느낌표/물음표
    r"|(?<=[‼‽⁇⁈⁉])\s*"                 # 복합 구두점
    r"|(?<=[…‥])\s*"                      # 말줄임표
    r"|(?<=[؟۔।॥។៕၊])\s*"              # 아랍/인도/동남아
    r"|(?<=[᙮᠃᠉])\s*"                   # 캐나다 음절/몽골
    r"|(?<=[።፧፨])\s*"                    # 에티오피아
)


def split_sentences(text: str) -> list[str]:
    """텍스트를 문장 단위로 분리한다."""
    parts = _SENTENCE_SPLIT_RE.split(text)
    return [p.strip() for p in parts if p.strip()]


# ── 토큰 추출 ─────────────────────────────────────────────────────────────────

# 영숫자 시작 조합, 또는 한글 2자 이상.
# 한글 1자 토큰은 단독 조사·어미이므로 정규식 수준에서 제외한다 (MK5 방식).
_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_+\-./#]*|[가-힣]{2,}")

# 한국어 조사·어미 목록 (길이 내림차순).
# 토큰 끝에서 한 번만 제거한다 — 파티클 토큰을 별도 생성하지 않는다 (MK5 정책).
# 제거 후 어간이 2자 미만이면 제거하지 않는다.
_KO_PARTICLES: tuple[str, ...] = tuple(sorted((
    "으로", "에서", "에게", "한테", "까지", "부터", "처럼", "보다", "하고",
    "이랑", "이며", "이고", "이야", "이다", "이나", "이든", "이라도",
    "나마", "마저", "조차", "밖에", "라도",
    "은", "는", "이", "가", "을", "를", "에", "의", "도", "로", "과", "와", "만", "랑",
    "고", "며",
), key=len, reverse=True))


def _strip_ko_particle(token: str) -> str:
    """한글 토큰 끝에서 조사를 제거하고 어간을 반환한다.

    - 제거 후 어간이 2자 이상일 때만 제거한다 (MK5 정책: len(token) > len(particle) + 1).
    - 첫 번째로 매칭된 조사 하나만 제거한다 (길이 내림차순이므로 최장 일치 우선).

    예:
        "글록의"      → "글록"
        "사고과정을"  → "사고과정"
        "나는"        → "나는"   (어간 1자 → 제거 안 함)
        "서울에서"    → "서울"
        "에서"        → "에서"   (2자 토큰, 어간 0자 → 제거 안 함)
    """
    for particle in _KO_PARTICLES:
        if token.endswith(particle) and len(token) > len(particle) + 1:
            return token[: -len(particle)]
    return token


def extract_tokens(sentence: str) -> list[str]:
    """문장에서 토큰을 추출한다.

    - 한글: 2자 이상만 추출 후 조사를 후미에서 제거 → 단일 어간 토큰 반환.
    - 영숫자: 그대로 반환.
    - 단독 파티클 토큰을 생성하지 않으므로 노이즈 노드 문제가 발생하지 않는다.
    """
    result: list[str] = []
    for token in _TOKEN_RE.findall(sentence):
        if token and "\uAC00" <= token[0] <= "\uD7A3":
            result.append(_strip_ko_particle(token))
        else:
            result.append(token)
    return result


def tokenize(text: str) -> list[list[str]]:
    """텍스트 전체를 문장별 토큰 목록으로 변환한다.

    Returns:
        list of sentences, each sentence is a list of token strings
    """
    sentences = split_sentences(text)
    return [extract_tokens(s) for s in sentences]
