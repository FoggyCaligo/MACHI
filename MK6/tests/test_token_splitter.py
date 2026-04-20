"""TokenSplitter 단위 테스트."""
import pytest
from MK6.core.translation.token_splitter import split_sentences, extract_tokens, tokenize


def test_split_sentences_newline():
    text = "첫 문장\n둘째 문장"
    parts = split_sentences(text)
    assert len(parts) == 2
    assert parts[0] == "첫 문장"


def test_split_sentences_english_period():
    text = "Hello world. This is a test."
    parts = split_sentences(text)
    assert len(parts) >= 2


def test_split_sentences_cjk_period():
    text = "안녕하세요。반갑습니다。"
    parts = split_sentences(text)
    assert len(parts) == 2


def test_extract_tokens_korean_single_char():
    # 한글 1자도 토큰이 되어야 함
    tokens = extract_tokens("이 사과가 맛있다")
    assert "이" in tokens
    assert "사과가" in tokens or "사과" in tokens


def test_extract_tokens_english():
    tokens = extract_tokens("apple is a fruit")
    assert "apple" in tokens
    assert "fruit" in tokens


def test_extract_tokens_mixed():
    tokens = extract_tokens("Python으로 만든 AI")
    assert "Python" in tokens
    assert "AI" in tokens


def test_extract_tokens_special_chars_excluded():
    tokens = extract_tokens("hello, world!")
    assert "," not in tokens
    assert "!" not in tokens


def test_tokenize_structure():
    result = tokenize("첫 문장입니다.\n둘째 문장입니다.")
    assert isinstance(result, list)
    assert all(isinstance(s, list) for s in result)
    assert len(result) >= 1


def test_extract_tokens_underscore_in_word():
    # 코드 식별자 패턴 — 영문+언더스코어
    tokens = extract_tokens("snake_case variable")
    assert "snake_case" in tokens
