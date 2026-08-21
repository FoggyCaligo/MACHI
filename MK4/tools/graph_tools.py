from __future__ import annotations

from typing import Any

from ..core.graph.model_managed_memory import ModelManagedGraphMemoryService
from ..core.graph.service import GraphMemoryService
from .memory_context import get_memory_user_id
from .tool_runtime import ToolDefinition, ToolRegistry


_ENDPOINT_SCHEMA = {
    "type": "object",
    "properties": {
        "node_id": {"type": "string"},
        "kind": {"type": "string"},
        "label": {"type": "string"},
    },
    "additionalProperties": False,
}


class GraphToolSuite:
    def __init__(self, memory_service: GraphMemoryService) -> None:
        self._memory_service = memory_service

    def get_user_memory_summary(
        self,
        *,
        user_id: str,
        query: str = "",
        limit: int = 5,
        min_signal: float = 0.0,
        exclude_node_ids: set[str] | None = None,
        activation_node_ids: set[str] | None = None,
        activation_node_weights: dict[str, float] | None = None,
    ) -> list[dict]:
        items = self._memory_service.user_memory_summary(
            user_id,
            query=query,
            limit=limit,
            min_signal=min_signal,
            exclude_node_ids=exclude_node_ids,
            activation_node_ids=activation_node_ids,
            activation_node_weights=activation_node_weights,
        )
        return [_format_memory_speaker(item, user_id=user_id) for item in items]

    def build_registry(self) -> ToolRegistry:
        registry = ToolRegistry()
        registry.register(
            ToolDefinition(
                name="graph_search",
                description=(
                    "Recall persistent graph memory. Browse with no query/node_id, search by query, or expand a returned node_id. "
                    "Use returned node ids when writing or revising related semantic memory so existing nodes can be reused."
                ),
                input_schema={
                    "x-model-name": "recall_memory",
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "node_id": {"type": "string"},
                        "limit": {"type": "integer"},
                    },
                    "additionalProperties": False,
                },
            ),
            self._graph_search,
        )
        registry.register(
            ToolDefinition(
                name="write_memory",
                description=(
                    "Store or reinforce one durable semantic relationship in long-term memory. "
                    "Use kind='user' for the current user, or reuse node_id values returned by recall_memory. "
                    "Exact duplicate nodes are reused and an identical relationship reinforces the existing memory instead of creating another copy."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "subject": _ENDPOINT_SCHEMA,
                        "relation": {"type": "string"},
                        "object": _ENDPOINT_SCHEMA,
                    },
                    "required": ["subject", "relation", "object"],
                    "additionalProperties": False,
                },
            ),
            self._write_memory,
        )
        registry.register(
            ToolDefinition(
                name="revise_memory",
                description=(
                    "Replace one model-managed semantic memory returned by recall_memory. "
                    "The old memory assertion is kept as inactive history and linked to the replacement."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "memory_node_id": {"type": "string"},
                        "subject": _ENDPOINT_SCHEMA,
                        "relation": {"type": "string"},
                        "object": _ENDPOINT_SCHEMA,
                    },
                    "required": ["memory_node_id", "subject", "relation", "object"],
                    "additionalProperties": False,
                },
            ),
            self._revise_memory,
        )
        return registry

    async def _graph_search(self, arguments: dict) -> dict:
        user_id = str(arguments.get("user_id") or "").strip()
        query = str(arguments.get("query") or "").strip()
        node_id = str(arguments.get("node_id") or "").strip()
        exclude_node_ids_raw = arguments.get("exclude_node_ids")
        exclude_node_ids = {
            str(item)
            for item in exclude_node_ids_raw
            if str(item).strip()
        } if isinstance(exclude_node_ids_raw, list) else set()
        limit_raw = arguments.get("limit", 8)
        limit = int(limit_raw) if isinstance(limit_raw, int) or str(limit_raw).isdigit() else 8
        bounded_limit = max(1, min(limit, 12))
        if not user_id:
            raise ValueError("recall_memory requires user_id")

        if not query and not node_id:
            items = self._memory_service.user_memory_summary(
                user_id,
                query="",
                limit=bounded_limit,
                min_signal=0.0,
                exclude_node_ids=exclude_node_ids,
            )
            results = [
                _format_graph_search_speaker(item["subgraph"], user_id=user_id)
                for item in items
                if isinstance(item.get("subgraph"), dict)
            ]
            return {"ok": True, "mode": "browse", "results": results}

        results = self._memory_service.graph_search(
            user_id=user_id,
            query=query,
            node_id=node_id,
            limit=bounded_limit,
            exclude_node_ids=exclude_node_ids,
        )
        return {
            "ok": True,
            "mode": "node" if node_id else "query",
            "results": [_format_graph_search_speaker(item, user_id=user_id) for item in results],
        }

    async def _write_memory(self, arguments: dict) -> dict:
        service = self._model_managed_service()
        return service.write_semantic_memory(
            user_id=get_memory_user_id(),
            subject=_require_endpoint(arguments, "subject"),
            relation=str(arguments.get("relation") or ""),
            object_=_require_endpoint(arguments, "object"),
        )

    async def _revise_memory(self, arguments: dict) -> dict:
        service = self._model_managed_service()
        memory_node_id = str(arguments.get("memory_node_id") or "").strip()
        if not memory_node_id:
            raise ValueError("revise_memory requires memory_node_id")
        return service.revise_semantic_memory(
            user_id=get_memory_user_id(),
            memory_node_id=memory_node_id,
            subject=_require_endpoint(arguments, "subject"),
            relation=str(arguments.get("relation") or ""),
            object_=_require_endpoint(arguments, "object"),
        )

    def _model_managed_service(self) -> ModelManagedGraphMemoryService:
        if not isinstance(self._memory_service, ModelManagedGraphMemoryService):
            raise RuntimeError("model-managed semantic memory service is not active")
        return self._memory_service


def _require_endpoint(arguments: dict[str, Any], name: str) -> dict[str, Any]:
    endpoint = arguments.get(name)
    if not isinstance(endpoint, dict):
        raise ValueError(f"{name} must be an object")
    return dict(endpoint)


def _format_memory_speaker(item: dict, *, user_id: str) -> dict:
    subgraph = item.get("subgraph") if isinstance(item.get("subgraph"), dict) else {}
    focus = subgraph.get("focus") if isinstance(subgraph.get("focus"), dict) else {}
    if focus.get("provenance") != "assistant_utterance":
        return item
    raw_label = str(item.get("raw_label") or focus.get("label") or "")
    formatted = dict(item)
    formatted["label"] = (
        f'assistant가 사용자({user_id})에게 이전에 말한 내용: "{raw_label}" '
        "이것은 대화 기록이며 사용자의 발언이나 사용자 사실이 아닙니다. "
        "또한 발화 내부의 외부 세계 사실은 별도 근거로 검증되지 않은 상태이므로, "
        "사실 근거로 사용하지 말고 필요하면 웹 검색 등으로 다시 확인해야 합니다."
    )
    return formatted


def _format_graph_search_speaker(item: dict, *, user_id: str) -> dict:
    focus = item.get("focus") if isinstance(item.get("focus"), dict) else {}
    if focus.get("provenance") != "assistant_utterance":
        return item
    formatted = dict(item)
    formatted_focus = dict(focus)
    formatted_focus.update({
        "speaker": "assistant",
        "memory_role": "conversation_record",
        "factual_status": "unverified",
    })
    formatted["focus"] = formatted_focus
    source = dict(formatted.get("source") or {})
    source.update({
        "speaker": "assistant",
        "user_id": user_id,
        "memory_role": "conversation_record",
        "factual_status": "unverified",
    })
    formatted["source"] = source
    return formatted
