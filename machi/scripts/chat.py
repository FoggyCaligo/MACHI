import requests
from datetime import datetime
from pathlib import Path
import socket
import uuid
import sys

# =========================
# Configuration
# =========================

OLLAMA_API = "http://localhost:11434/api/chat"
MODEL_NAME = "machi"

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MEMORY_DIR = PROJECT_ROOT / "memory" / "conversations"





# =========================
# BootStrap
# =========================
BOOTSTRAP_PROMPT = """
아래는 이전 세션의 요약이다.
이 요약은 현재 세션의 전제로만 사용하라.

규칙:
- 요약의 내용을 사실로 가정하되, 필요하면 검증 질문을 제안한다.
- 요약에 없는 내용은 추측하지 않는다.
- 현재 세션의 주제 전환을 방해하지 않는다.

[이전 세션 요약]
"""
def get_latest_summary():
    if not SUMMARY_DIR.exists():
        return None

    summaries = sorted(
        SUMMARY_DIR.glob("*.summary.md"),
        key=lambda p: p.stat().st_mtime,
        reverse=True
    )

    return summaries[0] if summaries else None

def build_messages(user_input, bootstrap_summary=None, first_turn=False):
    messages = []

    if first_turn and bootstrap_summary:
        messages.append({
            "role": "system",
            "content": BOOTSTRAP_PROMPT + "\n" + bootstrap_summary
        })

    messages.append({
        "role": "user",
        "content": user_input
    })

    return messages




# =========================
# Summary Initialization
# =========================

SUMMARY_DIR = PROJECT_ROOT / "memory" / "summaries"
SUMMARY_DIR.mkdir(parents=True, exist_ok=True)

SUMMARY_PROMPT = """
아래는 사용자와 AI의 대화 로그다.
이 대화를 다음 세션에서 이어서 사고할 수 있도록 요약하라.

요약 규칙:
- 한국어로 작성한다.
- 감정 묘사는 최소화한다.
- 결정된 사항을 명확히 분리한다.
- 미결 쟁점과 다음 질문을 구분한다.
- 불필요한 대화 흐름은 제거한다.

출력 형식:

## 핵심 요약
- ...

## 결정된 사항
- ...

## 미결 / 보류
- ...

## 다음 세션 제안
- ...
"""

def generate_summary(log_path):
    try:
        conversation_text = log_path.read_text(encoding="utf-8")

        payload = {
            "model": MODEL_NAME,
            "messages": [
                {"role": "system", "content": SUMMARY_PROMPT},
                {"role": "user", "content": conversation_text}
            ],
            "stream": False
        }

        response = requests.post(
            OLLAMA_API,
            json=payload,
            timeout=300
        )
        response.raise_for_status()

        summary_text = response.json()["message"]["content"]

        summary_path = SUMMARY_DIR / (log_path.stem + ".summary.md")
        summary_path.write_text(summary_text, encoding="utf-8")

        return summary_path

    except Exception as e:
        return f"[ERROR] Summary generation failed: {e}"

# =========================
# pattern signal
# =========================
PATTERNS_FILE = PROJECT_ROOT / "memory" / "patterns.md"
PATTERN_SIGNAL_PROMPT = """
아래는 한 세션의 요약이다.
이 요약을 바탕으로 '관측 가능한 패턴 신호'만 추출하라.

규칙:
- 진단하지 않는다.
- 단정하지 않는다.
- 성격 평가를 하지 않는다.
- 추측은 제거한다.
- 요약에 명시적으로 드러난 내용만 사용한다.

출력 형식은 반드시 다음을 따른다:

## 관측된 패턴 신호
- (패턴 이름): (관측 근거 한 줄)

패턴 이름 예시는 다음 범주에서만 선택한다:
- High-Confidence Clarity
- Productive Deep-Thinking
- Over-Depth / Saturation
- Anxiety-Laced Reasoning
- Self-Trust Collapse
- Ethical Boundary Activation
- Responsibility Overload
- Avoidance of Destructive Thought

해당되는 것이 없으면:
## 관측된 패턴 신호
- 없음
"""
def generate_pattern_signal(summary_path, session_id):
    try:
        summary_text = summary_path.read_text(encoding="utf-8")

        payload = {
            "model": MODEL_NAME,
            "messages": [
                {"role": "system", "content": PATTERN_SIGNAL_PROMPT},
                {"role": "user", "content": summary_text}
            ],
            "stream": False
        }

        response = requests.post(
            OLLAMA_API,
            json=payload,
            timeout=300
        )
        response.raise_for_status()

        signal_text = response.json()["message"]["content"]

        with open(PATTERNS_FILE, "a", encoding="utf-8") as f:
            f.write("\n---\n")
            f.write(f"\n### {session_id}\n\n")
            f.write(signal_text.strip() + "\n")

        return True

    except Exception as e:
        print(f"[WARN] Pattern signal generation failed: {e}")
        return False









# =========================
# Session Initialization
# =========================

def init_session():
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    hostname = socket.gethostname()
    session_id = uuid.uuid4().hex[:8]

    filename = f"{timestamp}_{hostname}_{session_id}.md"
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)

    log_path = MEMORY_DIR / filename

    header = f"""# Conversation Log
- Date: {datetime.now().isoformat()}
- Host: {hostname}
- Session ID: {session_id}
- Model: {MODEL_NAME}

---
"""

    log_path.write_text(header, encoding="utf-8")
    return log_path

# =========================
# Logging Utility
# =========================

def log_message(log_path, role, content):
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"\n## {role}\n{content.strip()}\n")

# =========================
# Ollama Interaction
# =========================
def query_ollama(message, bootstrap_summary=None, first_turn=False):
    payload = {
        "model": MODEL_NAME,
        "messages": build_messages(
            message,
            bootstrap_summary=bootstrap_summary,
            first_turn=first_turn
        ),
        "stream": False
    }

    try:
        response = requests.post(
            OLLAMA_API,
            json=payload,
            timeout=300
        )
        response.raise_for_status()
        return response.json()["message"]["content"]
    except requests.RequestException as e:
        return f"[ERROR] Ollama API request failed: {e}"

# =========================
# Main Loop
# =========================

def main():
    log_path = init_session()

    latest_summary_path = get_latest_summary()
    bootstrap_summary = None

    if latest_summary_path:
        bootstrap_summary = latest_summary_path.read_text(encoding="utf-8")
        print(f"Loaded summary: {latest_summary_path.name}")
    else:
        print("No previous summary found. Starting fresh.")

    print("Machi CLI Session Started")
    print(f"Log file: {log_path.name}")
    print("Type 'exit' or 'quit' to end the session.\n")

    first_turn = True

    print("Machi CLI Session Started")
    print(f"Log file: {log_path.name}")
    print("Type 'exit' or 'quit' to end the session.\n")

    while True:
        try:
            user_input = input("You > ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nSession terminated.")
            break

        if user_input.lower() in {"exit", "quit"}:
            print("Session closed.")
            break

        if not user_input:
            continue

        log_message(log_path, "User", user_input)

        assistant_reply = query_ollama(
            user_input,
            bootstrap_summary=bootstrap_summary,
            first_turn=first_turn
        )
        first_turn = False
        print(f"\nMachi > {assistant_reply}\n")

        log_message(log_path, "Machi", assistant_reply)

    log_message(
        log_path,
        "System",
        "Session ended normally."
    )
    print("\nGenerating session summary...")
    summary_path = generate_summary(log_path)

    if isinstance(summary_path, Path):
        print(f"Summary saved to: {summary_path.name}")

        session_id = log_path.stem
        print("Updating patterns.md with observed signals...")
        generate_pattern_signal(summary_path, session_id)

    else:
        print(summary_path)
# =========================
# Entry Point
# =========================

if __name__ == "__main__":
    main()



# YYYY-MM-DD_HH-MM-SS_HOSTNAME_SESSIONID.md
