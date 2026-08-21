from __future__ import annotations

from dataclasses import dataclass

from ..core.agent.orchestrator import AgentOrchestrator
from ..core.graph.assistant_memory import AssistantMemoryRecorder
from ..core.graph.model_managed_memory import ModelManagedGraphMemoryService
from ..core.graph.repository import GraphRepository
from ..tools.account_authorization import (
    AccountAuthorizationChatModel,
    reset_account_role,
    set_account_role,
)
from ..tools.autonomy_tools import AutonomyChatModel
from ..tools.grounding_tools import EvidenceGroundingChatModel
from ..tools.graph_tools import GraphToolSuite
from ..tools.code_index_tools import CodeIndexToolSuite
from ..tools.document_tools import DocumentReadToolSuite
from ..tools.file_agent_tools import FileAgentToolSuite
from ..tools.file_navigation_tools import FileNavigationToolSuite
from ..tools.image_tools import ImageAnalyzeToolSuite
from ..tools.llm_client import ChatModel
from ..tools.manual_tools import ToolManualSuite
from ..tools.memory_context import (
    reset_memory_turn_scope,
    reset_memory_user_id,
    set_memory_turn_scope,
    set_memory_user_id,
)
from ..tools.model_tool_names import ModelToolNameAdapter
from ..tools.structured_context_model import StructuredContextOllamaToolChatModel
from ..tools.terminal_tools import TerminalToolSuite
from ..tools.tool_runtime import (
    get_file_working_root,
    reset_file_task_message,
    reset_file_working_root,
    set_file_task_message,
    set_file_working_root,
)
from ..tools.turn_cycle import (
    TurnCycleChatModel,
    TurnCycleToolSuite,
    reset_turn_cycle_state,
    set_turn_cycle_state,
)
from ..tools.web_search import HttpWebSearchTool, WebSearchTool
from ..tools.workspace_tools import WorkspaceFileToolSuite
from .download_tokens import default_download_token_store


@dataclass
class PipelineResult:
    text: str
    used_tools: list[str]
    memory_writes: list[str]
    tool_events: list[dict]


TRIAL_TOOL_NAMES = {
    "graph_search",
    "write_memory",
    "revise_memory",
    "finish_memory_commit",
    "latest_search",
    "market_snapshot",
    "web_research",
    "tool_manual",
}


class Pipeline:
    def __init__(
        self,
        *,
        graph_repo: GraphRepository | None = None,
        chat_model: ChatModel | None = None,
        web_search: WebSearchTool | None = None,
    ) -> None:
        self._graph_repo = graph_repo or GraphRepository()
        self._memory = ModelManagedGraphMemoryService(self._graph_repo)
        self._assistant_memory = AssistantMemoryRecorder(self._graph_repo)
        self._tools = GraphToolSuite(self._memory)
        base_chat_model = AccountAuthorizationChatModel(
            ModelToolNameAdapter(chat_model or StructuredContextOllamaToolChatModel())
        )
        self._chat_model = TurnCycleChatModel(
            EvidenceGroundingChatModel(AutonomyChatModel(base_chat_model))
        )
        self._web_search = web_search or HttpWebSearchTool()
        self._file_working_roots: dict[str, str] = {}
        self._orchestrator = AgentOrchestrator(
            memory_service=self._memory,
            graph_tools=self._tools,
            chat_model=self._chat_model,
            web_search=self._web_search,
        )
        self._orchestrator.register_tool_registry(
            WorkspaceFileToolSuite(token_store=default_download_token_store).build_registry()
        )
        self._orchestrator.register_tool_registry(FileNavigationToolSuite().build_registry())
        self._orchestrator.register_tool_registry(FileAgentToolSuite().build_registry())
        self._orchestrator.register_tool_registry(CodeIndexToolSuite().build_registry())
        self._orchestrator.register_tool_registry(DocumentReadToolSuite().build_registry())
        self._orchestrator.register_tool_registry(ImageAnalyzeToolSuite().build_registry())
        self._orchestrator.register_tool_registry(TerminalToolSuite().build_registry())
        self._orchestrator.register_tool_registry(TurnCycleToolSuite().build_registry())
        self._orchestrator.register_tool_registry(
            ToolManualSuite(self._orchestrator.tool_registry).build_registry()
        )

    async def run(
        self,
        *,
        user_id: str,
        message: str,
        model: str | None = None,
        session_id: str | None = None,
        account_role: str = "owner",
    ) -> PipelineResult:
        conversation_key = f"{user_id}::{session_id or 'default'}"
        root_token = set_file_working_root(self._file_working_roots.get(conversation_key, "."))
        task_tokens = set_file_task_message(message)
        account_role_token = set_account_role(account_role)
        memory_user_token = set_memory_user_id(user_id)
        memory_turn_token = set_memory_turn_scope(message)
        turn_cycle_token = set_turn_cycle_state()
        try:
            result = await self._orchestrator.respond(
                user_id=user_id,
                message=message,
                model=model,
                session_id=session_id,
                allowed_tool_names=TRIAL_TOOL_NAMES if account_role == "trial" else None,
            )
            if _successful_memory_commit(result.tool_events):
                self._memory.graphize_user_utterance(
                    user_id=user_id,
                    text=message,
                    session_id=session_id,
                )
            self._assistant_memory.record(
                user_id=user_id,
                text=result.text,
                session_id=session_id,
            )
            self._file_working_roots[conversation_key] = get_file_working_root()
        finally:
            reset_turn_cycle_state(turn_cycle_token)
            reset_memory_turn_scope(memory_turn_token)
            reset_memory_user_id(memory_user_token)
            reset_account_role(account_role_token)
            reset_file_task_message(task_tokens)
            reset_file_working_root(root_token)
        semantic_writes = [
            "semantic_memory"
            for event in result.tool_events
            if str(event.get("tool") or "") in {"write_memory", "revise_memory"}
            and isinstance(event.get("result"), dict)
            and event["result"].get("ok") is True
        ]
        raw_writes = [item for item in result.memory_writes if item == "user_utterance"]
        return PipelineResult(
            text=result.text,
            used_tools=[
                str(event.get("tool"))
                for event in result.tool_events
                if event.get("tool") and event.get("tool") != "finish_memory_commit"
            ],
            memory_writes=[*raw_writes, *semantic_writes, "assistant_utterance"],
            tool_events=result.tool_events,
        )

    def close(self) -> None:
        self._graph_repo.close()


def _successful_memory_commit(tool_events: list[dict]) -> bool:
    mutation_ok = any(
        str(event.get("tool") or "") in {"write_memory", "revise_memory"}
        and isinstance(event.get("result"), dict)
        and event["result"].get("ok") is True
        for event in tool_events
    )
    finish_ok = any(
        str(event.get("tool") or "") == "finish_memory_commit"
        and isinstance(event.get("result"), dict)
        and event["result"].get("ok") is True
        for event in tool_events
    )
    return mutation_ok and finish_ok
