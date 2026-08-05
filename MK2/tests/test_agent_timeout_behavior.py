import unittest
from unittest.mock import patch

from app.agent import Agent, tool_schema
from app.api import _http_error_from_exception
from config import (
    CHAT_UPDATE_EXTRACT_TIMEOUT,
    GENERAL_REPLY_MAX_CONTINUATIONS,
    GENERAL_REPLY_NUM_PREDICT,
    GENERAL_REPLY_TIMEOUT,
    OLLAMA_LIST_TIMEOUT,
    OLLAMA_TIMEOUT,
    PROFILE_ATTACHMENT_EXTRACT_TIMEOUT,
    ROUTE_CLASSIFY_TIMEOUT,
)
from app.text_attachment_route_resolver import TextAttachmentRouteResolver
from memory.services.chat_evidence_service import ChatEvidenceService
from profile_analysis.services.profile_attachment_ingest_service import ProfileAttachmentIngestService
from project_analysis.services.project_profile_route_resolver import ProjectProfileRouteResolver
from tools.ollama_client import OllamaClient
from tools.response_runner import ResponseRunResult


class AgentTimeoutBehaviorTests(unittest.TestCase):
    def test_ollama_client_defaults_come_from_config(self) -> None:
        client = OllamaClient()

        self.assertEqual(client.timeout, OLLAMA_TIMEOUT)
        self.assertEqual(OllamaClient.list_local_models.__defaults__[1], OLLAMA_LIST_TIMEOUT)
        self.assertEqual(OllamaClient.list_local_model_names.__defaults__[1], OLLAMA_LIST_TIMEOUT)

    def test_agent_runner_uses_configured_timeout_settings(self) -> None:
        agent = Agent()

        self.assertEqual(agent.runner.client.timeout, GENERAL_REPLY_TIMEOUT)
        self.assertEqual(agent.runner.client.num_predict, GENERAL_REPLY_NUM_PREDICT)
        self.assertEqual(agent.runner.max_continuations, GENERAL_REPLY_MAX_CONTINUATIONS)

    def test_no_tool_call_returns_tool_decision_runner_result(self) -> None:
        agent = Agent()
        runner_result = ResponseRunResult(
            text="runner response",
            truncated=False,
            continuation_count=0,
            tool_calls=[],
        )

        with patch.object(agent.runner, "run", return_value=runner_result) as mocked_run:
            result = agent.respond("hello", {})

        self.assertEqual(result, "runner response")
        mocked_run.assert_called_once()
        self.assertEqual(mocked_run.call_args.kwargs["tools"], tool_schema())

    def test_tool_call_uses_runner_for_both_initial_and_final_pass(self) -> None:
        agent = Agent()
        initial_result = ResponseRunResult(
            text="",
            truncated=False,
            continuation_count=0,
            message={
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "trusted_search",
                            "arguments": "{\"query\": \"latest python docs\"}",
                        }
                    }
                ],
            },
            tool_calls=[
                {
                    "function": {
                        "name": "trusted_search",
                        "arguments": "{\"query\": \"latest python docs\"}",
                    }
                }
            ],
        )
        final_result = ResponseRunResult(
            text="tool-backed response",
            truncated=False,
            continuation_count=0,
            tool_calls=[],
        )

        with patch.object(agent.runner, "run", side_effect=[initial_result, final_result]) as mocked_run:
            with patch("app.agent._call_tool", return_value={"results": []}):
                result = agent.respond("latest docs?", {})

        self.assertEqual(result, "tool-backed response")
        self.assertEqual(mocked_run.call_count, 2)
        self.assertEqual(mocked_run.call_args_list[0].kwargs["tools"], tool_schema())
        self.assertNotIn("tools", mocked_run.call_args_list[1].kwargs)
        followup_messages = mocked_run.call_args_list[1].kwargs["messages"]
        self.assertEqual(followup_messages[-1]["role"], "tool")
        self.assertEqual(followup_messages[-1]["name"], "trusted_search")

    def test_ollama_client_sanitize_preserves_tool_call_metadata(self) -> None:
        client = OllamaClient()

        sanitized = client._sanitize_messages(
            [
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "function": {
                                "name": "trusted_search",
                                "arguments": "{\"query\": \"latest python docs\"}",
                            },
                        }
                    ],
                },
                {
                    "role": "tool",
                    "name": "trusted_search",
                    "tool_call_id": "call-1",
                    "content": "{\"results\": []}",
                },
            ]
        )

        self.assertEqual(len(sanitized), 2)
        self.assertEqual(sanitized[0]["role"], "assistant")
        self.assertIn("tool_calls", sanitized[0])
        self.assertEqual(sanitized[1]["role"], "tool")
        self.assertEqual(sanitized[1]["name"], "trusted_search")
        self.assertEqual(sanitized[1]["tool_call_id"], "call-1")

    def test_tool_decision_failure_falls_back_to_plain_runner(self) -> None:
        agent = Agent()
        fallback_result = ResponseRunResult(
            text="runner fallback",
            truncated=False,
            continuation_count=0,
            tool_calls=[],
        )

        with patch.object(agent.runner, "run", side_effect=[RuntimeError("boom"), fallback_result]) as mocked_run:
            with patch("builtins.print"):
                result = agent.respond("hello", {})

        self.assertEqual(result, "runner fallback")
        self.assertEqual(mocked_run.call_count, 2)
        self.assertEqual(mocked_run.call_args_list[0].kwargs["tools"], tool_schema())
        self.assertNotIn("tools", mocked_run.call_args_list[1].kwargs)

    def test_tool_execution_failure_falls_back_to_plain_runner(self) -> None:
        agent = Agent()
        initial_result = ResponseRunResult(
            text="",
            truncated=False,
            continuation_count=0,
            message={"role": "assistant", "content": "", "tool_calls": []},
            tool_calls=[
                {
                    "function": {
                        "name": "trusted_search",
                        "arguments": "{\"query\": \"latest python docs\"}",
                    }
                }
            ],
        )
        fallback_result = ResponseRunResult(
            text="runner fallback",
            truncated=False,
            continuation_count=0,
            tool_calls=[],
        )

        with patch.object(agent.runner, "run", side_effect=[initial_result, fallback_result]) as mocked_run:
            with patch.object(agent, "_respond_with_tool_calls", side_effect=RuntimeError("tool boom")):
                with patch("builtins.print"):
                    result = agent.respond("latest docs?", {})

        self.assertEqual(result, "runner fallback")
        self.assertEqual(mocked_run.call_count, 2)
        self.assertEqual(mocked_run.call_args_list[0].kwargs["tools"], tool_schema())
        self.assertNotIn("tools", mocked_run.call_args_list[1].kwargs)

    def test_timeout_errors_map_to_gateway_timeout(self) -> None:
        http_exc = _http_error_from_exception(
            RuntimeError("OLLAMA_TIMEOUT: model 'qwen2.5:3b' did not answer within 240 seconds")
        )

        self.assertEqual(http_exc.status_code, 504)
        self.assertIn("240", http_exc.detail)

    def test_route_and_extract_services_use_configured_timeouts(self) -> None:
        text_route_resolver = TextAttachmentRouteResolver()
        project_route_resolver = ProjectProfileRouteResolver()
        chat_evidence_service = ChatEvidenceService()
        attachment_ingest_service = ProfileAttachmentIngestService()

        self.assertEqual(text_route_resolver.client.timeout, ROUTE_CLASSIFY_TIMEOUT)
        self.assertEqual(project_route_resolver.client.timeout, ROUTE_CLASSIFY_TIMEOUT)
        self.assertEqual(chat_evidence_service.extraction_service.client.timeout, CHAT_UPDATE_EXTRACT_TIMEOUT)
        self.assertEqual(
            attachment_ingest_service.extraction_service.client.timeout,
            PROFILE_ATTACHMENT_EXTRACT_TIMEOUT,
        )


if __name__ == "__main__":
    unittest.main()
