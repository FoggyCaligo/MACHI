from __future__ import annotations

from ..core.graph.service import GraphMemoryService
from .tool_runtime import ToolDefinition, ToolRegistry


class GraphToolSuite:
    def __init__(self, memory_service: GraphMemoryService) -> None:
        self._memory_service = memory_service

    def get_user_memory_summary(
        self,
        *,
        user_id: str,
        query: str = "",
        limit: int = 5,
        exclude_node_ids: set[str] | None = None,
        activation_node_ids: set[str] | None = None,
    ) -> list[str]:
        return self._memory_service.user_memory_summary(
            user_id,
            query=query,
            limit=limit,
            exclude_node_ids=exclude_node_ids,
            activation_node_ids=activation_node_ids,
        )

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
        registry.register(
            ToolDefinition(
                name="record_memory_correction",
                description="Replace an incorrect user fact while preserving correction history.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "user_id": {"type": "string"},
                        "previous_fact_id": {"type": "string"},
                        "replacement_text": {"type": "string"},
                        "session_id": {"type": ["string", "null"]},
                    },
                    "required": ["user_id", "previous_fact_id", "replacement_text"],
                    "additionalProperties": False,
                },
            ),
            self._record_memory_correction,
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

    async def _record_memory_correction(self, arguments: dict) -> dict:
        user_id = str(arguments.get("user_id") or "").strip()
        previous_fact_id = str(arguments.get("previous_fact_id") or "").strip()
        replacement_text = str(arguments.get("replacement_text") or "").strip()
        session_id_raw = arguments.get("session_id")
        session_id = str(session_id_raw) if session_id_raw is not None else None
        replacement_id = self._memory_service.record_fact_correction(
            user_id=user_id,
            previous_fact_id=previous_fact_id,
            replacement_text=replacement_text,
            session_id=session_id,
        )
        return {"replacement_fact_id": replacement_id}
