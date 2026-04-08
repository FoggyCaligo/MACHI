from config import SYSTEM_PROMPT_PATH


def build_messages(user_message: str, context: dict) -> list[dict]:
    with open(SYSTEM_PROMPT_PATH, "r", encoding="utf-8") as f:
        system_prompt = f.read()

    context_text = f"Context: {context}"
    return [
        {"role": "system", "content": system_prompt},
        {"role": "system", "content": context_text},
        {"role": "user", "content": user_message},
    ]
