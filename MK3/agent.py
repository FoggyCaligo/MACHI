from __future__ import annotations

import json
from typing import Any

import requests

from config import settings
from memory import build_memory_context, get_recent_messages
from trusted_search import trusted_search


def tool_schema() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": "trusted_search",
                "description": (
                    "Search trusted sources only. Prioritize official documentation and papers. "
                    "Use this whenever the question requires up-to-date facts, technical docs, papers, or verifiable references."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query in English or Korean, optimized for official docs and papers.",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Maximum number of final trusted results.",
                            "default": 8,
                        },
                    },
                    "required": ["query"],
                },
            },
        }
    ]


SYSTEM_PROMPT = """
너는 로컬 Gemma 기반 개인 비서다.

규칙:
1) 반드시 한국어로 답한다.
2) 사용자의 선호를 반영해 구조 -> 메커니즘 -> 관계 -> 적용 순서로 설명을 우선한다.
3) 팩트가 흔들리거나 최신성이 중요한 질문은 trusted_search 도구를 먼저 사용한다.
4) trusted_search 결과에서는 공식 문서와 논문만 근거로 삼는다. 신뢰도가 낮거나 출처가 불명확한 웹페이지는 근거로 사용하지 않는다.
5) 사실과 추정을 구분한다.
6) 최종 답변 말미에는 [1], [2]처럼 근거 번호를 붙여라.
7) 도구를 쓰지 않아도 되는 단순 대화에서는 바로 대답하되, 확신이 낮으면 도구를 써라.
8) 사용자의 NEED는 구조적 이해와 논리 검증이다. 위로나 인정은 필요 충족 뒤에 덧붙여라.
""".strip()


def build_messages(user_input: str) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": build_memory_context()},
    ]
    messages.extend(get_recent_messages(limit=settings.recent_message_limit))
    messages.append({"role": "user", "content": user_input})
    return messages


TOOL_IMPL = {
    "trusted_search": trusted_search,
}

def call_ollama(messages, tools=None):
    payload = {
        "model": settings.ollama_model,
        "messages": messages,
        "stream": False,
    }

    if tools:
        payload["tools"] = tools

    resp = requests.post(
        f"{settings.ollama_base_url}/api/chat",
        json=payload,
        timeout=settings.ollama_timeout_seconds,
    )

    print("=== OLLAMA REQUEST PAYLOAD ===")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print("=== OLLAMA STATUS ===", resp.status_code)
    print("=== OLLAMA RESPONSE TEXT ===")
    print(resp.text)

    resp.raise_for_status()
    return resp.json()

def run_agent(user_input: str) -> tuple[str, list[dict[str, Any]]]:
    messages = build_messages(user_input)
    tool_traces: list[dict[str, Any]] = []

    for _ in range(settings.max_tool_rounds):
        response = call_ollama(messages)
        message = response["message"]
        tool_calls = message.get("tool_calls") or []

        if not tool_calls:
            return message.get("content", ""), tool_traces

        messages.append(message)

        for tool_call in tool_calls:
            fn = tool_call["function"]["name"]
            args = tool_call["function"].get("arguments", {}) or {}
            if fn not in TOOL_IMPL:
                result = {"error": f"Unknown tool: {fn}"}
            else:
                try:
                    result = TOOL_IMPL[fn](**args)
                except Exception as e:
                    result = {"error": str(e), "tool": fn, "arguments": args}

            tool_traces.append({"name": fn, "arguments": args, "result": result})
            messages.append(
                {
                    "role": "tool",
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )

    return "도구 호출 라운드 한도에 도달했습니다. 질문을 더 좁혀 주세요.", tool_traces
