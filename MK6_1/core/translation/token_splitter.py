"""TokenSplitter — 자연어 문자열을 표면 토큰 목록으로 분리한다."""
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

# 영숫자 시작 조합, 또는 한글 2자 이상 표면형.
# 이 계층은 토큰의 표면형만 추출하며 조사·어미 절단 같은 의미 정제를 하지 않는다.
# 신재용/재용/신재용이라고 같은 표면 차이는 문자열 규칙으로 분해하지 않는다.
# 이후 그래프 활성화, 임베딩 유사도, 반복 근거, ConceptMerge가 관계를 조정한다.
_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_+\-./#]*|[가-힣]{2,}")


def extract_tokens(sentence: str) -> list[str]:
    """문장에서 표면 토큰을 추출한다.

    TokenSplitter는 문자열을 그래프 입력 단위로 나누는 계층이다. 조사·어미,
    문법 기능어, 의미 기여도 판단은 여기서 문자열 규칙으로 처리하지 않고
    이후 graph activation / keyword score / relation reasoning 단계에서 다룬다.

    표면형이 서로 닮았다는 이유만으로 여기서 분리하거나 병합하지 않는다. 동일성,
    부분-전체성, alias, surface variant 판단은 graph edge와 merge 정책의 책임이다.
    """
    return _TOKEN_RE.findall(sentence)


def tokenize(text: str) -> list[list[str]]:
    """텍스트 전체를 문장별 토큰 목록으로 변환한다.

    Returns:
        list of sentences, each sentence is a list of token strings
    """
    sentences = split_sentences(text)
    return [extract_tokens(s) for s in sentences]
