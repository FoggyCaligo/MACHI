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

# 한글 1자 이상, 또는 영숫자 시작 조합 (단독 구두점 제외)
_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_+\-./#]*|[가-힣]+")

# 한국어 조사·의존형태소 불용어 집합.
# 단독 토큰으로 등장 시 제거한다.
# 대명사(그, 난, 나, 너, 이것, 저것 등)는 의미 있는 참조 개념이므로 포함하지 않는다.
_KO_PARTICLES: frozenset[str] = frozenset({
    # 격조사
    "이", "가", "을", "를", "은", "는", "의",
    # 처소·방향·상대 조사
    "에", "에서", "에게", "한테", "께", "로", "으로", "서",
    # 접속 조사
    "와", "과", "이랑", "랑", "하고",
    # 보조사
    "도", "만", "부터", "까지", "마저", "조차", "밖에", "나마",
    "라도", "이라도", "이나", "이든",
    # 연결·전성 어미 단독 분리형
    "고", "며", "이며", "이고", "인",
    # 서술격조사 단독 분리형
    "이야", "야", "이다",
})


def extract_tokens(sentence: str) -> list[str]:
    """문장에서 토큰을 추출한다.

    한글 1자도 토큰이 될 수 있다. 단, 조사·의존형태소는 _KO_PARTICLES로 제거한다.
    대명사(그, 난, 나 등)는 의미 개념으로 취급하여 유지한다.
    """
    return [t for t in _TOKEN_RE.findall(sentence) if t not in _KO_PARTICLES]


def tokenize(text: str) -> list[list[str]]:
    """텍스트 전체를 문장별 토큰 목록으로 변환한다.

    Returns:
        list of sentences, each sentence is a list of token strings
    """
    sentences = split_sentences(text)
    return [extract_tokens(s) for s in sentences]
