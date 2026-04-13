from __future__ import annotations

import json
from typing import Any

import requests

from config import (
    GENERAL_REPLY_MAX_CONTINUATIONS,
    GENERAL_REPLY_NUM_PREDICT,
    GENERAL_REPLY_TIMEOUT,
    OLLAMA_BASE_URL,
    OLLAMA_DEFAULT_MODEL,
    settings,
)
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

    try:
        resp = requests.post(
            f"{OLLAMA_BASE_URL}/api/chat",
            json=payload,
            timeout=300,  # 5분 타임아웃
        )
    except requests.exceptions.Timeout as exc:
        model_name = str(payload.get("model") or OLLAMA_DEFAULT_MODEL)
        raise RuntimeError(
            f"OLLAMA_TIMEOUT: 모델 '{model_name}' 응답이 300초 안에 오지 않았습니다."
        ) from exc

    resp.raise_for_status()
    return resp.json()


class Agent:
    def __init__(self) -> None:
        self.runner = ResponseRunner(
            timeout=GENERAL_REPLY_TIMEOUT,
            num_predict=GENERAL_REPLY_NUM_PREDICT,
            max_continuations=GENERAL_REPLY_MAX_CONTINUATIONS,
        )

    def _build_messages(self, user_message: str, context: dict) -> list[dict]:
        enriched_context = dict(context)
        enriched_context["reply_guard"] = build_guard_context(context).to_dict()
        return build_messages(user_message=user_message, context=enriched_context)

    def respond(self, user_message: str, context: dict, model: str | None = None) -> str:
        messages = self._build_messages(user_message=user_message, context=context)
        tool_result = self._respond_with_optional_tools(messages, model=model)
        if tool_result:
            return tool_result

        result = self.runner.run(messages, model=model)
        return result.text

    def _respond_with_optional_tools(self, messages: list[dict], model: str | None = None) -> str | None:
        """모델이 tool 호출을 선택하면 tool을 실행하고, 아니면 단일 응답을 그대로 사용한다."""
        tools = tool_schema()

        try:
            response = call_ollama(messages, tools=tools, model=model)
            message = response.get("message") or {}
            content = str(message.get("content") or "").strip()

            tool_calls = message.get("tool_calls") or []
            if tool_calls:
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
                    followup_messages = list(messages) + [
                        message,
                        {
                            "role": "tool",
                            "content": "\n\n".join(tool_results),
                        },
                    ]
                    final_response = call_ollama(followup_messages, model=model)
                    final_message = final_response.get("message") or {}
                    final_content = str(final_message.get("content") or "").strip()
                    return final_content or None

                return None

            return content or None

        except Exception as e:
            print(f"[AGENT] Tool 사용 실패: {e}")
            return None

        return None
