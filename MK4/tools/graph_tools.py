from __future__ import annotations

from typing import Any

from ..core.graph.model_managed_memory import ModelManagedGraphMemoryService
from ..core.graph.service import GraphMemoryService
from .memory_context import (
    get_memory_user_id,
    has_memory_turn_scope,
    mark_memory_mutation_succeeded,
    register_created_node_ids,
    register_recalled_node_ids,
    require_memory_mutation_enabled,
    require_scoped_node_id,
    resolve_writable_term,
)
from .tool_runtime import ToolDefinition, ToolRegistry


_ENDPOINT_SCHEMA = {
    "type": "object",
    "properties": {
        "node_id": {"type": "string"},
        "kind": {"type": "string"},
        "term_id": {"type": "string"},
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
                    "Recall persistent graph memory as one-hop focus neighborhoods. Browse with no query/node_id, "
                    "search by query, or expand a returned node_id. Additional recall calls are allowed."
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
                    "Write or reinforce one semantic relationship after the answer draft is fixed. Existing endpoints "
                    "must use recalled/created node_id values; new endpoints must use term_id from the current turn's "
                    "writable_terms. Identical relationships reinforce existing graph support."
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
                    "Modify only the current turn graph scope after the answer draft is fixed. operation='connect' "
                    "adds/reinforces an edge between already recalled/created nodes; operation='update_node' merges "
                    "model attributes into one in-scope node; operation='replace' supersedes an in-scope semantic "
                    "memory and may use writable term_id values for replacement endpoints."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["connect", "update_node", "replace"]},
                        "memory_node_id": {"type": "string"},
                        "node_id": {"type": "string"},
                        "attributes": {"type": "object"},
                        "subject": _ENDPOINT_SCHEMA,
                        "relation": {"type": "string"},
                        "object": _ENDPOINT_SCHEMA,
                    },
                    "required": ["operation"],
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
            if has_memory_turn_scope():
                register_recalled_node_ids(_result_node_ids(results))
            return {"ok": True, "mode": "browse", "depth": 1, "results": results}

        results = self._memory_service.graph_search(
            user_id=user_id,
            query=query,
            node_id=node_id,
            limit=bounded_limit,
            exclude_node_ids=exclude_node_ids,
        )
        formatted = [_format_graph_search_speaker(item, user_id=user_id) for item in results]
        if has_memory_turn_scope():
            register_recalled_node_ids(_result_node_ids(formatted))
        return {
            "ok": True,
            "mode": "node" if node_id else "query",
            "depth": 1,
            "results": formatted,
        }

    async def _write_memory(self, arguments: dict) -> dict:
        require_memory_mutation_enabled()
        service = self._model_managed_service()
        result = service.write_semantic_memory(
            user_id=get_memory_user_id(),
            subject=_scoped_endpoint(arguments, "subject", allow_new=True),
            relation=str(arguments.get("relation") or ""),
            object_=_scoped_endpoint(arguments, "object", allow_new=True),
        )
        register_created_node_ids(_memory_result_node_ids(result))
        mark_memory_mutation_succeeded()
        return result

    async def _revise_memory(self, arguments: dict) -> dict:
        require_memory_mutation_enabled()
        service = self._model_managed_service()
        operation = str(arguments.get("operation") or "").strip()
        user_id = get_memory_user_id()

        if operation == "connect":
            result = service.connect_memory_nodes(
                user_id=user_id,
                subject=_scoped_endpoint(arguments, "subject", allow_new=False),
                relation=str(arguments.get("relation") or ""),
                object_=_scoped_endpoint(arguments, "object", allow_new=False),
            )
            register_created_node_ids(_memory_result_node_ids(result))
            mark_memory_mutation_succeeded()
            return result

        if operation == "update_node":
            node_id = require_scoped_node_id(str(arguments.get("node_id") or ""))
            attributes = arguments.get("attributes")
            if not isinstance(attributes, dict):
                raise ValueError("update_node requires attributes object")
            result = service.update_memory_node(user_id=user_id, node_id=node_id, attributes=dict(attributes))
            mark_memory_mutation_succeeded()
            return result

        if operation == "replace":
            memory_node_id = require_scoped_node_id(str(arguments.get("memory_node_id") or ""))
            result = service.revise_semantic_memory(
                user_id=user_id,
                memory_node_id=memory_node_id,
                subject=_scoped_endpoint(arguments, "subject", allow_new=True),
                relation=str(arguments.get("relation") or ""),
                object_=_scoped_endpoint(arguments, "object", allow_new=True),
            )
            register_created_node_ids(_memory_result_node_ids(result))
            mark_memory_mutation_succeeded()
            return result

        raise ValueError("revise_memory operation must be connect, update_node, or replace")

    def _model_managed_service(self) -> ModelManagedGraphMemoryService:
        if not isinstance(self._memory_service, ModelManagedGraphMemoryService):
            raise RuntimeError("model-managed semantic memory service is not active")
        return self._memory_service


def _scoped_endpoint(arguments: dict[str, Any], name: str, *, allow_new: bool) -> dict[str, Any]:
    endpoint = arguments.get(name)
    if not isinstance(endpoint, dict):
        raise ValueError(f"{name} must be an object")
    node_id = str(endpoint.get("node_id") or "").strip()
    if node_id:
        return {"node_id": require_scoped_node_id(node_id)}
    kind = str(endpoint.get("kind") or "").strip()
    if kind.casefold() == "user":
        return {"kind": "user"}
    term_id = str(endpoint.get("term_id") or "").strip()
    if not allow_new:
        raise ValueError(f"{name} must use an in-scope node_id for this operation")
    if not term_id:
        raise ValueError(f"{name} requires an in-scope node_id, kind='user', or writable term_id")
    return {"kind": kind or "concept", "label": resolve_writable_term(term_id)}


def _result_node_ids(results: list[dict]) -> set[str]:
    node_ids: set[str] = set()
    for item in results:
        if not isinstance(item, dict):
            continue
        focus = item.get("focus")
        if isinstance(focus, dict) and str(focus.get("node_id") or "").strip():
            node_ids.add(str(focus["node_id"]))
        relations = item.get("relations")
        if isinstance(relations, list):
            for relation in relations:
                if isinstance(relation, dict) and str(relation.get("node_id") or "").strip():
                    node_ids.add(str(relation["node_id"]))
    return node_ids


def _memory_result_node_ids(result: dict[str, Any]) -> set[str]:
    return {
        str(result[key])
        for key in ("memory_node_id", "subject_node_id", "object_node_id", "node_id")
        if str(result.get(key) or "").strip()
    }


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
