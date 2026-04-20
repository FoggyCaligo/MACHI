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

# 한국어 조사·의존형태소 접미 목록.
# 토큰 끝에서 분리해 어간과 조사를 별도 토큰으로 만든다.
# 조사 토큰은 임베딩 기반 중요도 점수가 낮아 near+far 필터에서 자연스럽게 탈락한다.
# 길이 내림차순 정렬 — 긴 접미사 먼저 매칭해 부분 매칭 방지 ("으로" 우선, "로" 후순위)
_KO_SUFFIXES: tuple[str, ...] = tuple(sorted((
    # 격조사·처소조사 (다자)
    "에서", "에게", "한테", "으로", "이랑",
    # 보조사 (다자)
    "이라도", "나마", "마저", "조차", "밖에", "부터", "까지", "하고", "라도",
    # 연결·서술격 어미 (다자)
    "이며", "이고", "이야", "이다", "이나", "이든",
    # 격조사·접속조사 (단자)
    "의", "을", "를", "은", "는", "에", "로", "와", "과", "랑",
    # 보조사 (단자)
    "도", "만",
    # 연결 어미 (단자)
    "고", "며",
), key=len, reverse=True))

# 조사 분리 시 어간 최소 글자 수.
# 1글자 어간("나", "그" 등 대명사)은 분리하지 않아 의미 있는 참조 개념을 보존한다.
_KO_STEM_MIN = 2


def _split_ko_suffix(token: str) -> list[str]:
    """한글 토큰 끝에서 조사를 분리한다.

    어간이 _KO_STEM_MIN자 이상일 때만 분리한다.
    분리된 조사는 별도 토큰으로 반환한다.

    예:
        "글록의"      → ["글록", "의"]
        "개발자와"    → ["개발자", "와"]
        "장기기억그래프와" → ["장기기억그래프", "와"]
        "나는"        → ["나는"]   (어간 1자 → 분리 안 함)
        "그는"        → ["그는"]   (어간 1자 → 분리 안 함)
    """
    for suffix in _KO_SUFFIXES:
        if token.endswith(suffix):
            stem = token[: -len(suffix)]
            if len(stem) >= _KO_STEM_MIN:
                return [stem, suffix]
    return [token]


def extract_tokens(sentence: str) -> list[str]:
    """문장에서 토큰을 추출한다.

    영숫자 토큰은 그대로 반환한다.
    한글 토큰은 끝 조사를 분리해 [어간, 조사] 형태로 반환한다.
    조사 토큰은 중요도 점수가 낮아 near+far 필터에서 자연스럽게 탈락한다.
    """
    result: list[str] = []
    for token in _TOKEN_RE.findall(sentence):
        if token and "\uAC00" <= token[0] <= "\uD7A3":
            result.extend(_split_ko_suffix(token))
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
