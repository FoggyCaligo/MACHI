from __future__ import annotations

from pathlib import Path


_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _resolve_prompt_path(prompt_path: str | Path) -> Path:
    path = Path(prompt_path)
    if path.is_absolute():
        return path
    if path.exists():
        return path.resolve()
    candidate = (_PROJECT_ROOT / path).resolve()
    return candidate


def load_prompt_text(prompt_path: str | Path) -> str:
    path = _resolve_prompt_path(prompt_path)
    text = path.read_text(encoding='utf-8').strip()
    if not text:
        raise ValueError(f'프롬프트 파일이 비어 있습니다: {path}')
    return text
