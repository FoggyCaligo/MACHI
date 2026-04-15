from __future__ import annotations

from functools import lru_cache
from pathlib import Path


def _resolve_prompt_path(prompt_path: str | Path) -> Path:
    path = Path(prompt_path)
    if path.is_absolute():
        return path
    return Path(__file__).resolve().parent.parent / path


@lru_cache(maxsize=64)
def load_prompt_text(prompt_path: str | Path) -> str:
    path = _resolve_prompt_path(prompt_path)
    text = path.read_text(encoding='utf-8').strip()
    if not text:
        raise ValueError(f'프롬프트 파일이 비어 있습니다: {path}')
    return text
