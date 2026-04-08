from config import PROJECT_ASK_SYSTEM_PROMPT_PATH
from prompts.prompt_loader import load_prompt_text


def _clean_text(text: str | None, max_len: int = 1400) -> str:
    if not text:
        return ""
    text = text.strip()
    if len(text) > max_len:
        return text[:max_len].rstrip() + "\n..."
    return text


def build_project_ask_messages(question: str, chunks: list[dict]) -> list[dict]:
    system_prompt = load_prompt_text(PROJECT_ASK_SYSTEM_PROMPT_PATH)

    chunk_blocks = []
    for i, chunk in enumerate(chunks, start=1):
        file_path = chunk["file_path"]
        start_line = chunk["start_line"]
        end_line = chunk["end_line"]
        content = _clean_text(chunk["content"], max_len=1400)

        block = (
            f"[근거 코드 {i}]\n"
            f"파일: {file_path}\n"
            f"줄: {start_line}-{end_line}\n"
            f"점수: {chunk['score']:.1f}\n"
            f"{content}"
        )
        chunk_blocks.append(block)

    evidence_text = "\n\n".join(chunk_blocks).strip()

    user_prompt = (
        f"[질문]\n{question}\n\n"
        f"[검색된 관련 코드]\n{evidence_text}"
    )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]