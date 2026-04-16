from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from config import (
    MODEL_FEEDBACK_NUM_PREDICT,
    MODEL_FEEDBACK_TEMPERATURE,
    MODEL_FEEDBACK_TIMEOUT_SECONDS,
    build_ollama_options,
)
from core.entities.conclusion import CoreConclusion
from core.entities.edge import Edge
from core.entities.thought_view import ThoughtView
from core.update.graph_commit_service import (
    EdgeConflictRequest,
    EdgeSupportRequest,
    GraphMutationPlan,
)
from tools.ollama_client import (
    OllamaClient,
    OllamaClientError,
    OllamaModelNotFoundError,
    OllamaResponseError,
    OllamaTimeoutError,
)

_NO_MODEL = 'mk5-graph-core'

# Compact system prompt — task boundary + output schema, nothing more.
_SYSTEM_PROMPT = (
    'Graph edge feedback analyzer. '
    'Given a user message and a list of graph edges, '
    'identify which edges the message directly supports or directly contradicts. '
    'Only reference edge ids from the provided list. '
    'Output strict JSON only — no prose, no markdown:\n'
    '{"support_edge_ids": [<int>], "conflict_edge_ids": [<int>]}'
)


@dataclass(slots=True)
class ModelFeedbackResult:
    """Outcome of one model feedback pass."""

    attempted: bool
    plan: GraphMutationPlan | None = None
    error: str | None = None
    raw_response: str | None = None
    support_edge_ids: list[int] = field(default_factory=list)
    conflict_edge_ids: list[int] = field(default_factory=list)

    def to_debug(self) -> dict[str, Any]:
        return {
            'attempted': self.attempted,
            'support_edge_ids': self.support_edge_ids,
            'conflict_edge_ids': self.conflict_edge_ids,
            'error': self.error,
        }


@dataclass(slots=True)
class ModelFeedbackService:
    """Extract structured graph mutations from the model's view of the current turn.

    The model sees a short list of active edge IDs + types and is asked which edges
    the user message supports or contradicts.  Valid IDs (verified against the thought
    view) are translated into an EdgeSupportRequest / EdgeConflictRequest plan for
    GraphCommitService to execute.

    Design constraints:
    - No-op if model is unavailable or model_name is the default graph-only sentinel.
    - Parse failure → no-op (error surfaced in result, not raised).
    - Only edge IDs present in thought_view.edges are accepted; hallucinated IDs are
      silently dropped.
    - The service does NOT call GraphCommitService itself; that is the caller's job.
    """

    client: OllamaClient | None = None
    max_edges_in_prompt: int = 24

    def __post_init__(self) -> None:
        if self.client is None:
            self.client = OllamaClient(timeout_seconds=MODEL_FEEDBACK_TIMEOUT_SECONDS)

    def extract(
        self,
        *,
        model_name: str,
        message: str,
        thought_view: ThoughtView,
        conclusion: CoreConclusion,
    ) -> ModelFeedbackResult:
        if not model_name.strip() or model_name == _NO_MODEL:
            return ModelFeedbackResult(attempted=False)

        eligible = self._eligible_edges(thought_view)
        if not eligible:
            return ModelFeedbackResult(attempted=False)

        eligible_id_set = {e.id for e in eligible if e.id is not None}
        user_prompt = self._build_user_prompt(
            message=message,
            conclusion=conclusion,
            edges=eligible[: self.max_edges_in_prompt],
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
                    temperature=MODEL_FEEDBACK_TEMPERATURE,
                    num_predict=MODEL_FEEDBACK_NUM_PREDICT,
                ),
            )
        except OllamaModelNotFoundError as exc:
            return ModelFeedbackResult(attempted=True, error=f'model_not_found: {exc}')
        except OllamaTimeoutError as exc:
            return ModelFeedbackResult(attempted=True, error=f'timeout: {exc}')
        except (OllamaClientError, OllamaResponseError) as exc:
            return ModelFeedbackResult(attempted=True, error=str(exc))

        raw = result.content or ''
        plan, support_ids, conflict_ids, parse_error = self._parse(
            raw, eligible_id_set=eligible_id_set, message_id=conclusion.message_id,
        )
        return ModelFeedbackResult(
            attempted=True,
            plan=plan,
            error=parse_error,
            raw_response=raw[:400],
            support_edge_ids=support_ids,
            conflict_edge_ids=conflict_ids,
        )

    # ── helpers ────────────────────────────────────────────────────────────────

    def _eligible_edges(self, thought_view: ThoughtView) -> list[Edge]:
        edges = [e for e in thought_view.edges if e.is_active and e.id is not None]
        # concept 엣지 우선, 그다음 trust 순
        edges.sort(key=lambda e: (1 if e.edge_family == 'concept' else 0, e.trust_score), reverse=True)
        return edges

    def _build_user_prompt(
        self,
        *,
        message: str,
        conclusion: CoreConclusion,
        edges: list[Edge],
    ) -> str:
        edge_lines = '\n'.join(
            f'id={e.id} {e.edge_family}/{e.connect_type} trust={round(e.trust_score, 2)}'
            for e in edges
        )
        summary = ' '.join((conclusion.user_input_summary or message or '').split())[:200]
        return (
            f'User message: {summary}\n\n'
            f'Active graph edges:\n{edge_lines}\n\n'
            'Which edge ids does the message directly support or contradict?\nJSON:'
        )

    def _parse(
        self,
        raw: str,
        *,
        eligible_id_set: set[int],
        message_id: int | None,
    ) -> tuple[GraphMutationPlan | None, list[int], list[int], str | None]:
        try:
            text = raw.strip()
            start = text.find('{')
            end = text.rfind('}')
            if start < 0 or end <= start:
                return None, [], [], 'no_json_object_found'
            parsed = json.loads(text[start: end + 1])
        except Exception as exc:
            return None, [], [], f'json_parse_error: {exc}'

        def _safe_ids(key: str) -> list[int]:
            return [
                int(v) for v in (parsed.get(key) or [])
                if isinstance(v, (int, float)) and int(v) in eligible_id_set
            ]

        support_ids = _safe_ids('support_edge_ids')
        conflict_ids = _safe_ids('conflict_edge_ids')

        if not support_ids and not conflict_ids:
            return None, [], [], None  # no-op, no error

        plan = GraphMutationPlan(
            reason='model_feedback',
            message_id=message_id,
            note='Edge mutations derived from model feedback on current turn.',
            support_requests=[EdgeSupportRequest(edge_id=eid) for eid in support_ids],
            conflict_requests=[EdgeConflictRequest(edge_id=eid) for eid in conflict_ids],
        )
        return plan, support_ids, conflict_ids, None
