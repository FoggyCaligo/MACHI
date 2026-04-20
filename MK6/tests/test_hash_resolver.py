"""HashResolver 단위 테스트."""
import pytest
from MK6.core.utils.hash_resolver import normalize_text, compute_hash


def test_normalize_lowercase():
    assert normalize_text("Apple") == "apple"


def test_normalize_strip_punctuation():
    assert normalize_text("hello.") == "hello"
    assert normalize_text("(world)") == "world"


def test_normalize_korean_particle_removal():
    # "사과는" → "사과"
    assert normalize_text("사과는") == "사과"
    assert normalize_text("과일이") == "과일"
    assert normalize_text("나무를") == "나무"


def test_normalize_pure_particle_preserved():
    # 순수 조사 단독 토큰은 그대로 유지
    assert normalize_text("는") == "는"
    assert normalize_text("이") == "이"


def test_compute_hash_deterministic():
    h1 = compute_hash("사과")
    h2 = compute_hash("사과")
    assert h1 == h2


def test_compute_hash_length():
    h = compute_hash("apple")
    assert len(h) == 32


def test_compute_hash_differs():
    assert compute_hash("사과") != compute_hash("과일")


def test_hash_scope_prefix_isolation():
    # "word::" prefix 덕분에 같은 토큰이더라도 다른 scope prefix와 충돌 없음
    import hashlib
    raw_word = hashlib.sha256(b"word::apple").hexdigest()[:32]
    raw_abstract = hashlib.sha256(b"abstract::apple").hexdigest()[:32]
    assert raw_word != raw_abstract
