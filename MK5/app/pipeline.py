from __future__ import annotations

from dataclasses import dataclass

from ..core.agent.orchestrator import AgentOrchestrator
from ..core.graph.repository import GraphRepository
from ..core.graph.service import GraphMemoryService
from ..tools.graph_tools import GraphToolSuite
from ..tools.document_tools import DocumentReadToolSuite
from ..tools.image_tools import ImageAnalyzeToolSuite
from ..tools.llm_client import ChatModel, OllamaToolChatModel
from ..tools.terminal_tools import TerminalToolSuite
from ..tools.web_search import HttpWebSearchTool, WebSearchTool
from ..tools.workspace_tools import WorkspaceFileToolSuite


@dataclass
class PipelineResult:
    text: str
    used_tools: list[str]
    memory_writes: list[str]
    tool_events: list[dict]


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
        self._tools = GraphToolSuite(self._memory)
        self._chat_model = chat_model or OllamaToolChatModel()
        self._web_search = web_search or HttpWebSearchTool()
        self._orchestrator = AgentOrchestrator(
            memory_service=self._memory,
            graph_tools=self._tools,
            chat_model=self._chat_model,
            web_search=self._web_search,
        )
        self._orchestrator.register_tool_registry(WorkspaceFileToolSuite().build_registry())
        self._orchestrator.register_tool_registry(DocumentReadToolSuite().build_registry())
        self._orchestrator.register_tool_registry(ImageAnalyzeToolSuite().build_registry())
        self._orchestrator.register_tool_registry(TerminalToolSuite().build_registry())

    async def run(
        self,
        *,
        user_id: str,
        message: str,
        model: str | None = None,
        image_model: str | None = None,
        session_id: str | None = None,
    ) -> PipelineResult:
        result = await self._orchestrator.respond(
            user_id=user_id,
            message=message,
            model=model,
            image_model=image_model,
            session_id=session_id,
        )
        return PipelineResult(
            text=result.text,
            used_tools=result.used_tools,
            memory_writes=result.memory_writes,
            tool_events=result.tool_events,
        )

    def close(self) -> None:
        self._graph_repo.close()
