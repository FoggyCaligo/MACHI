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

# 한글 1자 이상, 또는 영숫자·기호 조합
_TOKEN_RE = re.compile(r"[A-Za-z0-9_+\-./#]+|[가-힣]+")


def extract_tokens(sentence: str) -> list[str]:
    """문장에서 토큰을 추출한다.

    한글 1자도 토큰이 될 수 있다 (조사 등 포함).
    """
    return _TOKEN_RE.findall(sentence)


def tokenize(text: str) -> list[list[str]]:
    """텍스트 전체를 문장별 토큰 목록으로 변환한다.

    Returns:
        list of sentences, each sentence is a list of token strings
    """
    sentences = split_sentences(text)
    return [extract_tokens(s) for s in sentences]
