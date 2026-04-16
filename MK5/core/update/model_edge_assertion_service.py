from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from config import (
    MODEL_EDGE_ASSERTION_NUM_PREDICT,
    MODEL_EDGE_ASSERTION_TEMPERATURE,
    MODEL_EDGE_ASSERTION_TIMEOUT_SECONDS,
    build_ollama_options,
)
from core.entities.edge import Edge
from core.entities.graph_event import GraphEvent
from core.entities.thought_view import ThoughtView
from storage.unit_of_work import UnitOfWork
from tools.ollama_client import (
    OllamaClient,
    OllamaClientError,
    OllamaModelNotFoundError,
    OllamaResponseError,
    OllamaTimeoutError,
)

_NO_MODEL = 'mk5-graph-core'

_VALID_FAMILIES: frozenset[str] = frozenset({'concept', 'relation'})
_VALID_CONNECT_TYPES: frozenset[str] = frozenset({'flow', 'neutral', 'opposite', 'conflict'})

_SYSTEM_PROMPT = (
    'Graph edge assertion analyzer. '
    'Given a user message and the active knowledge graph nodes, '
    'identify new structural relationships to record as edges. '
    'Rules:\n'
    '- Use ONLY node ids from the provided list.\n'
    '- edge_family must be "concept" or "relation".\n'
    '- connect_type must be "flow", "neutral", "opposite", or "conflict".\n'
    '- relation_detail.kind: a short snake_case label (e.g. subtype_of, name_variant, '
    'creator_of, used_for, located_in, opposes, member_of).\n'
    '- Only assert edges clearly implied by the user message. Do not invent.\n'
    'Output strict JSON only - no prose, no markdown:\n'
    '{"new_edges": [{"from_node_id": <int>, "to_node_id": <int>, '
    '"edge_family": <str>, "connect_type": <str>, '
    '"relation_detail": {"kind": <str>, "note": <str>}}]}'
)

_INITIAL_TRUST: float = 0.58
_INITIAL_WEIGHT: float = 0.25


@dataclass(slots=True)
class AssertedEdgeResult:
    from_node_id: int
    to_node_id: int
    edge_family: str
    connect_type: str
    kind: str
    edge_id: int | None = None
    action: str = 'created'


@dataclass(slots=True)
class ModelEdgeAssertionResult:
    attempted: bool
    asserted_edges: list[AssertedEdgeResult] = field(default_factory=list)
    error: str | None = None
    raw_response: str | None = None

    @property
    def created_edge_ids(self) -> list[int]:
        return [e.edge_id for e in self.asserted_edges if e.action == 'created' and e.edge_id is not None]

    @property
    def reinforced_edge_ids(self) -> list[int]:
        return [e.edge_id for e in self.asserted_edges if e.action == 'reinforced' and e.edge_id is not None]

    def to_debug(self) -> dict[str, Any]:
        return {
            'attempted': self.attempted,
            'created_count': len(self.created_edge_ids),
            'reinforced_count': len(self.reinforced_edge_ids),
            'skipped_count': sum(1 for e in self.asserted_edges if e.action == 'skipped'),
            'error': self.error,
            'asserted_edges': [
                {
                    'action': e.action,
                    'from_node_id': e.from_node_id,
                    'to_node_id': e.to_node_id,
                    'edge_family': e.edge_family,
                    'connect_type': e.connect_type,
                    'kind': e.kind,
                    'edge_id': e.edge_id,
                }
                for e in self.asserted_edges
            ],
        }


@dataclass(slots=True)
class ModelEdgeAssertionService:
    uow_factory: Callable[[], UnitOfWork]
    client: OllamaClient | None = None
    max_nodes_in_prompt: int = 20
    max_edges_in_prompt: int = 12
    max_assertions_per_turn: int = 8
    reinforce_trust_delta: float = 0.015

    def __post_init__(self) -> None:
        if self.client is None:
            self.client = OllamaClient(timeout_seconds=MODEL_EDGE_ASSERTION_TIMEOUT_SECONDS)

    def assert_edges(
        self,
        *,
        model_name: str,
        message: str,
        thought_view: ThoughtView,
    ) -> ModelEdgeAssertionResult:
        if not model_name.strip() or model_name == _NO_MODEL:
            return ModelEdgeAssertionResult(attempted=False)

        eligible_nodes = self._eligible_nodes(thought_view)
        if not eligible_nodes:
            return ModelEdgeAssertionResult(attempted=False)

        valid_node_ids = {n.id for n in eligible_nodes if n.id is not None}
        key_edges = self._key_edges(thought_view)
        user_prompt = self._build_user_prompt(
            message=message,
            nodes=eligible_nodes[: self.max_nodes_in_prompt],
            key_edges=key_edges[: self.max_edges_in_prompt],
        )

        try:
            result = self.client.chat(
                model_name=model_name,
                messages=[
                    {'role': 'system', 'content': _SYSTEM_PROMPT},
                    {'role': 'user', 'content': user_prompt},
                ],
                stream=False,
                options=build_ollama_options(
                    temperature=MODEL_EDGE_ASSERTION_TEMPERATURE,
                    num_predict=MODEL_EDGE_ASSERTION_NUM_PREDICT,
                ),
            )
        except OllamaModelNotFoundError as exc:
            return ModelEdgeAssertionResult(attempted=True, error=f'model_not_found: {exc}')
        except OllamaTimeoutError as exc:
            return ModelEdgeAssertionResult(attempted=True, error=f'timeout: {exc}')
        except (OllamaClientError, OllamaResponseError) as exc:
            return ModelEdgeAssertionResult(attempted=True, error=str(exc))

        raw = result.content or ''
        parsed_assertions, parse_error = self._parse(raw, valid_node_ids=valid_node_ids)
        if parse_error:
            return ModelEdgeAssertionResult(attempted=True, error=parse_error, raw_response=raw[:400])

        if not parsed_assertions:
            return ModelEdgeAssertionResult(attempted=True, raw_response=raw[:400])

        asserted = self._apply(parsed_assertions[: self.max_assertions_per_turn])
        return ModelEdgeAssertionResult(
            attempted=True,
            asserted_edges=asserted,
            raw_response=raw[:400],
        )

    def _eligible_nodes(self, thought_view: ThoughtView):
        nodes = [n for n in thought_view.nodes if n.is_active and n.id is not None]
        nodes.sort(key=lambda n: (n.trust_score, n.stability_score), reverse=True)
        return nodes

    def _key_edges(self, thought_view: ThoughtView):
        edges = [e for e in thought_view.edges if e.is_active and e.id is not None]
        edges.sort(
            key=lambda e: (
                1 if e.edge_family == 'concept' else 0,
                e.trust_score,
            ),
            reverse=True,
        )
        return edges

    def _build_user_prompt(self, *, message: str, nodes, key_edges) -> str:
        summary = ' '.join(str(message or '').split())[:200]

        node_lines = '\n'.join(
            f'id={n.id} "{(n.normalized_value or n.raw_value or "").strip()}"'
            for n in nodes
        )
        edge_lines = '\n'.join(
            f'id={e.id} {e.edge_family}/{e.connect_type} node{e.source_node_id}->node{e.target_node_id}'
            + (f' kind={e.relation_detail.get("kind", "")}' if e.relation_detail.get('kind') else '')
            for e in key_edges
        )

        parts = [
            f'User message: {summary}',
            '',
            f'Active nodes:\n{node_lines}',
        ]
        if edge_lines:
            parts += ['', f'Existing key edges:\n{edge_lines}']
        parts += ['', 'What new edges does the user message assert?\nJSON:']
        return '\n'.join(parts)

    def _parse(
        self,
        raw: str,
        *,
        valid_node_ids: set[int],
    ) -> tuple[list[dict[str, Any]], str | None]:
        try:
            text = raw.strip()
            start = text.find('{')
            end = text.rfind('}')
            if start < 0 or end <= start:
                return [], 'no_json_object_found'
            parsed = json.loads(text[start: end + 1])
        except Exception as exc:
            return [], f'json_parse_error: {exc}'

        raw_edges = parsed.get('new_edges')
        if not isinstance(raw_edges, list):
            return [], None

        validated: list[dict[str, Any]] = []
        for item in raw_edges:
            if not isinstance(item, dict):
                continue
            try:
                from_id = int(item['from_node_id'])
                to_id = int(item['to_node_id'])
            except (KeyError, TypeError, ValueError):
                continue
            if from_id not in valid_node_ids or to_id not in valid_node_ids:
                continue
            if from_id == to_id:
                continue

            edge_family = str(item.get('edge_family', '')).strip()
            if edge_family not in _VALID_FAMILIES:
                continue

            raw_connect_type = str(item.get('connect_type', '')).strip()
            connect_type = raw_connect_type if raw_connect_type in _VALID_CONNECT_TYPES else 'neutral'

            detail_raw = item.get('relation_detail') or {}
            relation_detail: dict[str, Any] = dict(detail_raw) if isinstance(detail_raw, dict) else {}
            kind = str(relation_detail.get('kind', '')).strip() or 'unspecified'
            relation_detail['kind'] = kind
            relation_detail.setdefault('note', '')
            relation_detail['inferred_from'] = 'model_assertion'

            if raw_connect_type and raw_connect_type not in _VALID_CONNECT_TYPES:
                relation_detail.setdefault('proposed_connect_type', raw_connect_type)
                relation_detail.setdefault(
                    'proposal_reason',
                    'model_proposed_connect_type_outside_current_allowlist',
                )

            validated.append({
                'from_node_id': from_id,
                'to_node_id': to_id,
                'edge_family': edge_family,
                'connect_type': connect_type,
                'relation_detail': relation_detail,
            })

        return validated, None

    def _apply(self, assertions: list[dict[str, Any]]) -> list[AssertedEdgeResult]:
        results: list[AssertedEdgeResult] = []
        seen_pairs: set[tuple[int, int, str, str, str]] = set()

        with self.uow_factory() as uow:
            for assertion in assertions:
                from_id: int = assertion['from_node_id']
                to_id: int = assertion['to_node_id']
                edge_family: str = assertion['edge_family']
                connect_type: str = assertion['connect_type']
                relation_detail: dict[str, Any] = assertion['relation_detail']
                kind: str = relation_detail['kind']

                dedup_key = (from_id, to_id, edge_family, connect_type, kind)
                if dedup_key in seen_pairs:
                    results.append(AssertedEdgeResult(
                        from_node_id=from_id,
                        to_node_id=to_id,
                        edge_family=edge_family,
                        connect_type=connect_type,
                        kind=kind,
                        action='skipped',
                    ))
                    continue
                seen_pairs.add(dedup_key)

                existing = uow.edges.find_active_relation(
                    from_id,
                    to_id,
                    edge_family=edge_family,
                    connect_type=connect_type,
                )
                same_kind_existing = existing
                if same_kind_existing is None or (same_kind_existing.relation_detail.get('kind') or '') != kind:
                    outgoing_same_shape = uow.edges.list_outgoing(
                        from_id,
                        edge_families=[edge_family],
                        connect_types=[connect_type],
                        active_only=True,
                    )
                    same_kind_existing = next(
                        (
                            edge
                            for edge in outgoing_same_shape
                            if edge.target_node_id == to_id and (edge.relation_detail.get('kind') or '') == kind
                        ),
                        None,
                    )

                if same_kind_existing is not None and same_kind_existing.id is not None:
                    uow.edges.bump_support(
                        same_kind_existing.id,
                        delta=1,
                        trust_delta=self.reinforce_trust_delta,
                    )
                    results.append(AssertedEdgeResult(
                        from_node_id=from_id,
                        to_node_id=to_id,
                        edge_family=edge_family,
                        connect_type=connect_type,
                        kind=kind,
                        edge_id=same_kind_existing.id,
                        action='reinforced',
                    ))
                    continue

                event = uow.graph_events.add(GraphEvent(
                    event_uid=f'evt-{uuid4().hex}',
                    event_type='model_edge_asserted',
                    parsed_input={
                        'from_node_id': from_id,
                        'to_node_id': to_id,
                        'edge_family': edge_family,
                        'connect_type': connect_type,
                        'kind': kind,
                    },
                    effect={
                        'initial_trust': _INITIAL_TRUST,
                        'inferred_from': 'model_assertion',
                    },
                    note=str(relation_detail.get('note', ''))[:200],
                ))

                new_edge = uow.edges.add(Edge(
                    edge_uid=f'assertion-{uuid4().hex}',
                    source_node_id=from_id,
                    target_node_id=to_id,
                    edge_family=edge_family,
                    connect_type=connect_type,
                    relation_detail=relation_detail,
                    edge_weight=_INITIAL_WEIGHT,
                    trust_score=_INITIAL_TRUST,
                    support_count=1,
                    created_from_event_id=event.id,
                ))

                results.append(AssertedEdgeResult(
                    from_node_id=from_id,
                    to_node_id=to_id,
                    edge_family=edge_family,
                    connect_type=connect_type,
                    kind=kind,
                    edge_id=new_edge.id,
                    action='created',
                ))

            uow.commit()

        return results
