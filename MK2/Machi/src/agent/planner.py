from .llm_ollama import OllamaLLM
from .memory import last_chats
import pathlib

def read_prompt(path: str) -> str:
    return pathlib.Path(path).read_text(encoding="utf-8")

def build_system_prompt(user_input: str) -> str:
    core = read_prompt("prompts/system_core.md")
    persona = read_prompt("prompts/persona_support.md")
    userm = read_prompt("prompts/user_model.md")
    hist = last_chats(12)
    hist_txt = "\n".join([f"{r}: {c}" for r,c in hist])

    return f"""{core}

{persona}

{userm}

Recent conversation:
{hist_txt}

User says:
{user_input}

Respond in Korean.
If you propose an action that requires approval, clearly label it as:
ACTION_REQUEST: <type>
PAYLOAD: <json>
Otherwise, only give guidance.
"""

def respond(user_input: str) -> str:
    llm = OllamaLLM()
    prompt = build_system_prompt(user_input)
    return llm.chat(prompt, fast=False)
