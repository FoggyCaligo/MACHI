from __future__ import annotations

from dataclasses import dataclass

from ..core.agent.orchestrator import AgentOrchestrator
from ..core.graph.assistant_memory import AssistantMemoryRecorder
from ..core.graph.repository import GraphRepository
from ..core.graph.service import GraphMemoryService
from ..tools.autonomy_tools import AutonomyChatModel
from ..tools.grounding_tools import EvidenceGroundingChatModel
from ..tools.graph_tools import GraphToolSuite
from ..tools.code_index_tools import CodeIndexToolSuite
from ..tools.document_tools import DocumentReadToolSuite
from ..tools.file_agent_tools import FileAgentToolSuite
from ..tools.file_navigation_tools import FileNavigationToolSuite
from ..tools.image_tools import ImageAnalyzeToolSuite
from ..tools.llm_client import ChatModel, OllamaToolChatModel
from ..tools.manual_tools import ToolManualSuite
from ..tools.terminal_tools import TerminalToolSuite
from ..tools.tool_runtime import (
    get_file_working_root,
    reset_file_task_message,
    reset_file_working_root,
    set_file_task_message,
    set_file_working_root,
)
from ..tools.web_search import HttpWebSearchTool, WebSearchTool
from ..tools.work_plan_tools import WorkPlanToolSuite
from ..tools.work_planning import WorkPlanningChatModel
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
    "record_memory_correction",
    "work_plan",
    "work_step_complete",
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
        self._memory = GraphMemoryService(self._graph_repo)
        self._assistant_memory = AssistantMemoryRecorder(self._graph_repo)
        self._tools = GraphToolSuite(self._memory)
        base_chat_model = chat_model or OllamaToolChatModel()
        planned_chat_model = WorkPlanningChatModel(AutonomyChatModel(base_chat_model))
        self._chat_model = EvidenceGroundingChatModel(planned_chat_model)
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
        # Register agent-oriented overrides last so file_read/file_text_search/file_update
        # use narrow context and recovery-aware behavior without changing the stable base suite.
        self._orchestrator.register_tool_registry(FileAgentToolSuite().build_registry())
        self._orchestrator.register_tool_registry(CodeIndexToolSuite().build_registry())
        self._orchestrator.register_tool_registry(DocumentReadToolSuite().build_registry())
        self._orchestrator.register_tool_registry(ImageAnalyzeToolSuite().build_registry())
        self._orchestrator.register_tool_registry(TerminalToolSuite().build_registry())
        self._orchestrator.register_tool_registry(WorkPlanToolSuite().build_registry())
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
        try:
            result = await self._orchestrator.respond(
                user_id=user_id,
                message=message,
                model=model,
                session_id=session_id,
                allowed_tool_names=TRIAL_TOOL_NAMES if account_role == "trial" else None,
            )
            self._assistant_memory.record(
                user_id=user_id,
                text=result.text,
                session_id=session_id,
            )
            # Persist the logical file cwd exactly where the file tools ended.
            # It may be a project such as MK4/MK5, a parent-relative directory,
            # or an absolute path outside config.WORKSPACE_ROOT.
            self._file_working_roots[conversation_key] = get_file_working_root()
        finally:
            reset_file_task_message(task_tokens)
            reset_file_working_root(root_token)
        return PipelineResult(
            text=result.text,
            used_tools=result.used_tools,
            memory_writes=[*result.memory_writes, "assistant_utterance"],
            tool_events=result.tool_events,
        )

    def close(self) -> None:
        self._graph_repo.close()
