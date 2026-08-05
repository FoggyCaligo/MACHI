from config import REVIEW_SYSTEM_PROMPT_PATH
from prompts.prompt_loader import load_prompt_text


def build_file_review_messages(file_path: str, code_content: str, question: str) -> list[dict]:
    system_prompt = load_prompt_text(REVIEW_SYSTEM_PROMPT_PATH)

    user_prompt = (
        f"[대상 파일]\n{file_path}\n\n"
        f"[질문]\n{question}\n\n"
        f"[코드 원문]\n{code_content}"
    )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]