from config import SYSTEM_PROMPT_PATH
from prompts.prompt_loader import load_prompt_text


def _clean_text(text: str | None, max_len: int = 220) -> str:
    if not text:
        return ""
    text = " ".join(str(text).strip().split())
    if len(text) > max_len:
        return text[:max_len].rstrip() + "..."
    return text


def _pick_memory_text(item: dict, preferred_keys: list[str], max_len: int = 220) -> str:
    for key in preferred_keys:
        value = item.get(key)
        cleaned = _clean_text(value, max_len=max_len)
        if cleaned:
            return cleaned
    return ""


def build_messages(user_message: str, context: dict) -> list[dict]:
    system_prompt = load_prompt_text(SYSTEM_PROMPT_PATH)

    profiles = context.get("profiles", [])[:2]
    corrections = context.get("corrections", [])[:1]
    summaries = context.get("summaries", [])[:1]
    episodes = context.get("episodes", [])[:2]
    states = context.get("states", [])[:2]
    recent_messages = context.get("recent_messages", [])[-4:]

    memory_lines: list[str] = []

    if profiles:
        memory_lines.append("[사용자 프로필]")
        for p in profiles:
            topic = _clean_text(p.get("topic"), max_len=60)
            content = _pick_memory_text(
                p,
                preferred_keys=["content", "value", "summary"],
                max_len=180,
            )
            if topic and content:
                memory_lines.append(f"- {topic}: {content}")
            elif content:
                memory_lines.append(f"- {content}")

    if corrections:
        memory_lines.append("[최근 정정]")
        for c in corrections:
            topic = _clean_text(c.get("topic"), max_len=60)
            content = _pick_memory_text(
                c,
                preferred_keys=["content", "value", "summary"],
                max_len=180,
            )
            if topic and content:
                memory_lines.append(f"- {topic}: {content}")
            elif content:
                memory_lines.append(f"- {content}")

    if states:
        memory_lines.append("[현재 상태]")
        for s in states:
            key = _clean_text(s.get("key"), max_len=60)
            value = _clean_text(s.get("value"), max_len=160)
            if key and value:
                memory_lines.append(f"- {key}: {value}")
            elif value:
                memory_lines.append(f"- {value}")

    if summaries:
        memory_lines.append("[관련 요약 기억]")
        for s in summaries:
            topic = _clean_text(s.get("topic"), max_len=60)
            content = _pick_memory_text(
                s,
                preferred_keys=["content", "summary", "value"],
                max_len=180,
            )
            if topic and content:
                memory_lines.append(f"- {topic}: {content}")
            elif content:
                memory_lines.append(f"- {content}")

    if episodes:
        memory_lines.append("[관련 에피소드]")
        for e in episodes:
            topic = _clean_text(
                e.get("topic") or e.get("title"),
                max_len=60,
            )
            content = _pick_memory_text(
                e,
                preferred_keys=["summary", "content", "description"],
                max_len=180,
            )
            if topic and content:
                memory_lines.append(f"- {topic}: {content}")
            elif content:
                memory_lines.append(f"- {content}")

    if recent_messages:
        memory_lines.append("[최근 대화]")
        for m in recent_messages:
            role = "사용자" if m.get("role") == "user" else "AI"
            content = _clean_text(m.get("content"), max_len=120)
            if content:
                memory_lines.append(f"- {role}: {content}")

    memory_text = "\n".join(memory_lines).strip()

    if memory_text:
        user_content = (
            f"[참고 기억]\n"
            f"{memory_text}\n\n"
            f"[현재 사용자 요청]\n"
            f"{_clean_text(user_message, max_len=1000)}"
        )
    else:
        user_content = _clean_text(user_message, max_len=1000)

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]