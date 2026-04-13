from __future__ import annotations

import logging
import math
from functools import lru_cache
from typing import Iterable

from config import TOPIC_EMBEDDING_MODEL


# sentence_transformers 내부의 BertModel LOAD REPORT 경고 억제
# ("embeddings.position_ids | UNEXPECTED" 등 모델 로드 시 발생하는 무해한 경고)
logging.getLogger("sentence_transformers").setLevel(logging.ERROR)


class EmbeddingDependencyError(RuntimeError):
    """Raised when the embedding dependency is unavailable."""


@lru_cache(maxsize=1)
def _load_model():
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise EmbeddingDependencyError(
            "sentence-transformers 가 설치되지 않았습니다. requirements.txt 설치 후 다시 시도해 주세요."
        ) from exc

    try:
        # local_files_only=True: 캐시된 모델만 사용, HF Hub 체크 생략
        return SentenceTransformer(TOPIC_EMBEDDING_MODEL, local_files_only=True)
    except Exception:
        pass

    # 캐시가 없는 최초 실행 등 예외 상황에만 Hub에서 다운로드
    try:
        from sentence_transformers import SentenceTransformer
        return SentenceTransformer(TOPIC_EMBEDDING_MODEL)
    except Exception as exc:
        raise EmbeddingDependencyError(
            f"임베딩 모델을 로드하지 못했습니다: {TOPIC_EMBEDDING_MODEL}"
        ) from exc


def _prepare_text(text: str, kind: str) -> str:
    normalized = " ".join((text or "").strip().split())
    if not normalized:
        return ""
    prefix = "query: " if kind == "query" else "passage: "
    return f"{prefix}{normalized}"


def embed_text(text: str, *, kind: str = "query") -> list[float]:
    prepared = _prepare_text(text, kind)
    if not prepared:
        return []
    try:
        model = _load_model()
        vector = model.encode(
            prepared,
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
        return [float(x) for x in vector.tolist()]
    except EmbeddingDependencyError:
        raise
    except Exception as exc:
        raise EmbeddingDependencyError(
            f"임베딩 계산에 실패했습니다: {TOPIC_EMBEDDING_MODEL}"
        ) from exc


def embed_texts(texts: Iterable[str], *, kind: str = "passage") -> list[list[float]]:
    prepared = [_prepare_text(text, kind) for text in texts]
    non_empty_indexes = [idx for idx, text in enumerate(prepared) if text]
    if not non_empty_indexes:
        return [[] for _ in prepared]
    try:
        model = _load_model()
        vectors = model.encode(
            [prepared[idx] for idx in non_empty_indexes],
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
        result: list[list[float]] = [[] for _ in prepared]
        for idx, vector in zip(non_empty_indexes, vectors.tolist()):
            result[idx] = [float(x) for x in vector]
        return result
    except EmbeddingDependencyError:
        raise
    except Exception as exc:
        raise EmbeddingDependencyError(
            f"임베딩 계산에 실패했습니다: {TOPIC_EMBEDDING_MODEL}"
        ) from exc


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return float(dot / (left_norm * right_norm))