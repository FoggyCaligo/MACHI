from .llm_ollama import OllamaLLM
from .memory import add_chat

def daily_briefing():
    llm = OllamaLLM()
    prompt = """한국어로 간결하게:
1) 오늘의 우선순위 3개
2) 리스크/주의 3개
3) 30분 안에 할 수 있는 '시동 행동' 1개
사용자 성향: 구조→메커니즘→적용.
"""
    msg = llm.chat(prompt, fast=True)
    add_chat("assistant", f"[DAILY_BRIEFING]\n{msg}")
