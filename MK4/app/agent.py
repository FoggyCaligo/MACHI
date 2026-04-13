from __future__ import annotations

import json
from typing import Any

import requests

from config import OLLAMA_BASE_URL, OLLAMA_DEFAULT_MODEL, settings
from prompts.response_builder import build_messages
from tools.reply_guard import build_guard_context
from tools.response_runner import ResponseRunner
from tools.trusted_search import trusted_search


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


TOOL_IMPL = {
    "trusted_search": trusted_search,
}


def call_ollama(messages, tools=None, model=None):
    payload = {
        "model": model or OLLAMA_DEFAULT_MODEL,
        "messages": messages,
        "stream": False,
    }

    if tools:
        payload["tools"] = tools

    resp = requests.post(
        f"{OLLAMA_BASE_URL}/api/chat",
        json=payload,
        timeout=300,  # 5분 타임아웃
    )

    resp.raise_for_status()
    return resp.json()


class Agent:
    def __init__(self) -> None:
        self.runner = ResponseRunner(
            timeout=45,  # GENERAL_REPLY_TIMEOUT
            num_predict=512,  # GENERAL_REPLY_NUM_PREDICT
            max_continuations=3,  # GENERAL_REPLY_MAX_CONTINUATIONS
        )

    def respond(self, user_message: str, context: dict, model: str | None = None) -> str:
        # 먼저 tool을 사용한 응답 시도
        tool_result = self._try_with_tools(user_message, context, model)
        if tool_result:
            return tool_result

        # tool이 필요 없으면 기존 방식으로 응답
        enriched_context = dict(context)
        enriched_context["reply_guard"] = build_guard_context(context).to_dict()
        messages = build_messages(user_message=user_message, context=enriched_context)
        result = self.runner.run(messages, model=model)
        return result.text

    def _try_with_tools(self, user_message: str, context: dict, model: str | None = None) -> str | None:
        """Tool을 사용한 응답을 시도. 필요 없으면 None 반환."""
        enriched_context = dict(context)
        enriched_context["reply_guard"] = build_guard_context(context).to_dict()
        messages = build_messages(user_message=user_message, context=enriched_context)

        # tool schema 추가
        tools = tool_schema()

        try:
            response = call_ollama(messages, tools=tools, model=model)

            # tool call이 있는지 확인
            if "tool_calls" in response.get("message", {}):
                tool_calls = response["message"]["tool_calls"]
                tool_results = []

                for tool_call in tool_calls:
                    func_name = tool_call["function"]["name"]
                    func_args = json.loads(tool_call["function"]["arguments"])

                    if func_name in TOOL_IMPL:
                        try:
                            result = TOOL_IMPL[func_name](**func_args)
                            tool_results.append(f"[{func_name} 결과]\n{json.dumps(result, ensure_ascii=False, indent=2)}")
                        except Exception as e:
                            tool_results.append(f"[{func_name} 오류]\n{str(e)}")

                if tool_results:
                    # tool 결과를 포함한 새로운 메시지로 재요청
                    messages.append(response["message"])
                    messages.append({
                        "role": "tool",
                        "content": "\n\n".join(tool_results)
                    })

                    final_response = call_ollama(messages, model=model)
                    return final_response["message"]["content"]

        except Exception as e:
            # tool 사용 실패 시 기존 방식으로 fallback
            print(f"[AGENT] Tool 사용 실패: {e}")
            return None

        return None
