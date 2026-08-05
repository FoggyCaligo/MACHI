from __future__ import annotations

import json
from typing import Any

from config import (
    GENERAL_REPLY_MAX_CONTINUATIONS,
    GENERAL_REPLY_NUM_PREDICT,
    GENERAL_REPLY_TIMEOUT,
)
from prompts.response_builder import build_messages
from tools.reply_guard import build_guard_context
from tools.response_runner import ResponseRunResult, ResponseRunner


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


def _call_tool(func_name: str, func_args: dict[str, Any]) -> Any:
    if func_name == "trusted_search":
        from tools.trusted_search import trusted_search

        return trusted_search(**func_args)
    raise KeyError(f"Unknown tool: {func_name}")


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

        try:
            initial_result = self.runner.run(messages=messages, model=model, tools=tool_schema())
        except Exception as exc:
            print(f"[AGENT] Tool decision pass failed: {exc}")
            return self.runner.run(messages=messages, model=model).text

        if not initial_result.tool_calls:
            return initial_result.text

        try:
            final_result = self._respond_with_tool_calls(
                messages=messages,
                initial_result=initial_result,
                model=model,
            )
            return final_result.text
        except Exception as exc:
            print(f"[AGENT] Tool execution failed: {exc}")
            return self.runner.run(messages=messages, model=model).text

    def _respond_with_tool_calls(
        self,
        *,
        messages: list[dict],
        initial_result: ResponseRunResult,
        model: str | None = None,
    ) -> ResponseRunResult:
        tool_messages: list[dict[str, Any]] = []

        for tool_call in initial_result.tool_calls or []:
            function = tool_call.get("function") or {}
            func_name = str(function.get("name") or "").strip()
            raw_args = function.get("arguments")
            tool_call_id = str(tool_call.get("id") or "").strip()
            if isinstance(raw_args, str):
                func_args = json.loads(raw_args or "{}")
            elif isinstance(raw_args, dict):
                func_args = raw_args
            else:
                func_args = {}

            try:
                result = _call_tool(func_name, func_args)
                content = json.dumps(result, ensure_ascii=False, indent=2)
            except Exception as exc:
                content = json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2)

            tool_message: dict[str, Any] = {
                "role": "tool",
                "content": content,
            }
            if func_name:
                tool_message["name"] = func_name
            if tool_call_id:
                tool_message["tool_call_id"] = tool_call_id
            tool_messages.append(tool_message)

        if not tool_messages:
            return self.runner.run(messages=messages, model=model)

        followup_messages = list(messages)
        if initial_result.message:
            followup_messages.append(initial_result.message)
        followup_messages.extend(tool_messages)
        return self.runner.run(messages=followup_messages, model=model)
