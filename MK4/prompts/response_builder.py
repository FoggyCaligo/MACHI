from config import SYSTEM_PROMPT_PATH
from prompts.prompt_loader import load_prompt_text


MEMORY_NOISE_PATTERNS = (
    "당신은 특정 사용자를 장기적으로 보조하는 개인 ai 어시스턴트다",
    "이 시스템 프롬프트는",
    "최종 운영 지시",
    "답변 형식 가이드",
    "사용자 기본 모델",
    "assistant는",
    "어시스턴트는",
)

POLICY_ECHO_PATTERNS = (
    "현재 턴의 명시적 진술",
    "최신 correction",
    "기계적으로 복사하지",
    "기억한다고 가장하지",
    "예/아니오형이면 먼저 직접 대답",
    "과거 memory의 인칭",
)

GENERIC_NOISE_KEYS = {
    "response_style",
    "current_mood",
}


def _clean_text(text: str | None, max_len: int = 220) -> str:
    if not text:
        return ""
    text = " ".join(str(text).strip().split())
    if len(text) > max_len:
        return text[:max_len].rstrip() + "..."
    return text


def _looks_like_system_prompt_text(text: str | None) -> bool:
    if not text:
        return False

    lowered = " ".join(str(text).strip().lower().split())

    if len(lowered) >= 260:
        for pattern in MEMORY_NOISE_PATTERNS:
            if pattern in lowered:
                return True

    if lowered.startswith("당신은 ") and ("사용자" in lowered or "어시스턴트" in lowered):
        return True

    if "[시스템]" in str(text) or "[system]" in lowered:
        return True

    return False


def _looks_like_policy_echo(text: str | None) -> bool:
    if not text:
        return False

    lowered = " ".join(str(text).strip().lower().split())
    if not lowered:
        return False

    for pattern in POLICY_ECHO_PATTERNS:
        if pattern in lowered:
            return True
    return False


def _topic_label(item: dict) -> str:
    return _clean_text(
        item.get("topic_summary") or item.get("topic_name") or item.get("topic") or item.get("key") or item.get("title"),
        max_len=60,
    )


def _should_skip_memory_item(item: dict, candidate_text: str) -> bool:
    topic_or_key = _topic_label(item).strip().lower()

    if topic_or_key in GENERIC_NOISE_KEYS and _looks_like_system_prompt_text(candidate_text):
        return True

    if _looks_like_system_prompt_text(candidate_text):
        return True

    if _looks_like_policy_echo(candidate_text):
        return True

    return False


def _pick_memory_text(item: dict, preferred_keys: list[str], max_len: int = 220) -> str:
    for key in preferred_keys:
        value = item.get(key)
        cleaned = _clean_text(value, max_len=max_len)
        if cleaned:
            return cleaned
    return ""


def _normalize_memory_line(label: str, text: str) -> str:
    cleaned = _clean_text(text, max_len=180)
    if not cleaned:
        return ""

    lowered = cleaned.lower()

    replacements = (
        ("이 사용자는 ", ""),
        ("사용자는 ", ""),
        ("당신은 ", ""),
        ("당신이 ", ""),
    )
    for src, dst in replacements:
        if lowered.startswith(src):
            cleaned = cleaned[len(src):]
            break

    if not cleaned:
        return ""

    return f"- {label}: {cleaned}" if label else f"- {cleaned}"


def _summarize_recent_messages(recent_messages: list[dict], *, max_sentences: int = 5, max_chars: int = 520) -> str:
    if not recent_messages:
        return ""

    chunks: list[str] = []
    for message in recent_messages[-max_sentences:]:
        role = message.get("role")
        content = _clean_text(message.get("content"), max_len=95)
        if not content:
            continue

        if role == "assistant" and (_looks_like_system_prompt_text(content) or _looks_like_policy_echo(content)):
            continue

        if role == "user":
            sentence = f"사용자는 {content}"
        else:
            sentence = f"assistant는 {content}라고 답했다"

        chunks.append(sentence.rstrip(" .") + ".")

    if not chunks:
        return ""

    summary = " ".join(chunks)
    if len(summary) > max_chars:
        summary = summary[:max_chars].rstrip() + "..."
    return summary


def build_messages(user_message: str, context: dict) -> list[dict]:
    system_prompt = load_prompt_text(SYSTEM_PROMPT_PATH)

    profiles = context.get("profiles", [])[:2]
    corrections = context.get("corrections", [])[:2]
    summaries = context.get("summaries", [])[:1]
    episodes = context.get("episodes", [])[:2]
    states = context.get("states", [])[:2]
    recent_messages = context.get("recent_messages", [])[-4:]

    memory_lines: list[str] = []

    if profiles:
        section_lines: list[str] = []
        for p in profiles:
            topic = _topic_label(p)
            content = _pick_memory_text(
                p,
                preferred_keys=["content", "value", "summary"],
                max_len=180,
            )
            if _should_skip_memory_item(p, content):
                continue
            line = _normalize_memory_line(topic, content)
            if line:
                section_lines.append(line)
        if section_lines:
            memory_lines.append("[사용자 프로필]")
            memory_lines.extend(section_lines)

    if corrections:
        section_lines = []
        for c in corrections:
            topic = _topic_label(c)
            content = _pick_memory_text(
                c,
                preferred_keys=["content", "value", "summary"],
                max_len=180,
            )
            if _should_skip_memory_item(c, content):
                continue
            line = _normalize_memory_line(topic, content)
            if line:
                section_lines.append(line)
        if section_lines:
            memory_lines.append("[최근 정정]")
            memory_lines.extend(section_lines)

    if states:
        section_lines = []
        for s in states:
            key = _clean_text(s.get("key"), max_len=60)
            value = _clean_text(s.get("value"), max_len=160)
            if _should_skip_memory_item(s, value):
                continue
            line = _normalize_memory_line(key, value)
            if line:
                section_lines.append(line)
        if section_lines:
            memory_lines.append("[현재 상태]")
            memory_lines.extend(section_lines)

    if summaries:
        section_lines = []
        for s in summaries:
            topic = _topic_label(s)
            content = _pick_memory_text(
                s,
                preferred_keys=["content", "summary", "value"],
                max_len=180,
            )
            if _should_skip_memory_item(s, content):
                continue
            line = _normalize_memory_line(topic, content)
            if line:
                section_lines.append(line)
        if section_lines:
            memory_lines.append("[관련 요약 기억]")
            memory_lines.extend(section_lines)

    if episodes:
        section_lines = []
        for e in episodes:
            topic = _topic_label(e)
            content = _pick_memory_text(
                e,
                preferred_keys=["summary", "content", "description"],
                max_len=180,
            )
            if _should_skip_memory_item(e, content):
                continue
            line = _normalize_memory_line(topic, content)
            if line:
                section_lines.append(line)
        if section_lines:
            memory_lines.append("[관련 에피소드]")
            memory_lines.extend(section_lines)

    recent_summary = _summarize_recent_messages(recent_messages)
    if recent_summary:
        memory_lines.append("[최근 대화 요약]")
        memory_lines.append(recent_summary)

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
