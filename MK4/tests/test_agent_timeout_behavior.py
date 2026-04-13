import unittest
from unittest.mock import patch

from app.agent import Agent
from app.api import _http_error_from_exception
from config import (
    GENERAL_REPLY_MAX_CONTINUATIONS,
    GENERAL_REPLY_NUM_PREDICT,
    GENERAL_REPLY_TIMEOUT,
)
from tools.response_runner import ResponseRunResult


class AgentTimeoutBehaviorTests(unittest.TestCase):
    def test_agent_runner_uses_configured_timeout_settings(self) -> None:
        agent = Agent()

        self.assertEqual(agent.runner.client.timeout, GENERAL_REPLY_TIMEOUT)
        self.assertEqual(agent.runner.client.num_predict, GENERAL_REPLY_NUM_PREDICT)
        self.assertEqual(agent.runner.max_continuations, GENERAL_REPLY_MAX_CONTINUATIONS)

    def test_plain_tool_enabled_response_is_used_without_runner_fallback(self) -> None:
        agent = Agent()

        with patch("app.agent.call_ollama", return_value={"message": {"content": "plain response"}}):
            with patch.object(agent.runner, "run", side_effect=AssertionError("runner should not be called")):
                result = agent.respond("안녕? 나에 대해 기억하고 있니?", {})

        self.assertEqual(result, "plain response")

    def test_tool_failure_falls_back_to_runner(self) -> None:
        agent = Agent()

        with patch("app.agent.call_ollama", side_effect=RuntimeError("boom")):
            with patch("builtins.print"):
                with patch.object(
                    agent.runner,
                    "run",
                    return_value=ResponseRunResult(
                        text="runner fallback",
                        truncated=False,
                        continuation_count=0,
                    ),
                ):
                    result = agent.respond("안녕?", {})

        self.assertEqual(result, "runner fallback")

    def test_timeout_errors_map_to_gateway_timeout(self) -> None:
        http_exc = _http_error_from_exception(
            RuntimeError("OLLAMA_TIMEOUT: 모델 'qwen2.5:3b' 응답이 240초 안에 오지 않았습니다.")
        )

        self.assertEqual(http_exc.status_code, 504)
        self.assertIn("240초", http_exc.detail)


if __name__ == "__main__":
    unittest.main()
