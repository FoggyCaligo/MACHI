from __future__ import annotations

from ..core.graph.service import GraphMemoryService
from .tool_runtime import ToolDefinition, ToolRegistry


class GraphToolSuite:
    def __init__(self, memory_service: GraphMemoryService) -> None:
        self._memory_service = memory_service

    def get_user_memory_summary(self, *, user_id: str, limit: int = 5) -> list[str]:
        return self._memory_service.user_memory_summary(user_id, limit=limit)

    def build_registry(self) -> ToolRegistry:
        registry = ToolRegistry()
        registry.register(
            ToolDefinition(
                name="graph_search",
                description="Search the persistent graph memory for nodes related to the given query and user.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "user_id": {"type": "string"},
                        "query": {"type": "string"},
                        "limit": {"type": "integer"},
                    },
                    "required": ["user_id", "query"],
                    "additionalProperties": False,
                },
            ),
            self._graph_search,
        )
        return registry

    async def _graph_search(self, arguments: dict) -> dict:
        user_id = str(arguments.get("user_id") or "").strip()
        query = str(arguments.get("query") or "").strip()
        limit_raw = arguments.get("limit", 8)
        limit = int(limit_raw) if isinstance(limit_raw, int) or str(limit_raw).isdigit() else 8
        if not user_id:
            raise ValueError("graph_search requires user_id")
        if not query:
            raise ValueError("graph_search requires query")
        return {
            "results": self._memory_service.graph_search(user_id=user_id, query=query, limit=max(1, min(limit, 12)))
        }
