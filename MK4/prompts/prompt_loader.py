from pathlib import Path


def load_prompt_text(prompt_path: str | Path) -> str:
    path = Path(prompt_path)
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"프롬프트 파일이 비어 있습니다: {path}")
    return text