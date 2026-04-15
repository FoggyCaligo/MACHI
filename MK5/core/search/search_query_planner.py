from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from core.entities.conclusion import CoreConclusion
from core.entities.thought_view import ThoughtView
from core.search.search_need_evaluator import SearchNeedDecision
from tools.ollama_client import (
    OllamaClient,
    OllamaClientError,
    OllamaModelNotFoundError,
    OllamaResponseError,
)
from tools.prompt_loader import load_prompt_text


class SearchQueryPlannerError(RuntimeError):
    pass


@dataclass(slots=True)
class SearchPlan:
    queries: list[str]
    reason: str
    focus_terms: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SearchQueryPlanner:
    client: OllamaClient | None = None
    system_prompt_path: str = 'prompts/system/search_planner_system_prompt.txt'
    user_prompt_path: str = 'prompts/search/search_query_planner_prompt.txt'

    def __post_init__(self) -> None:
        if self.client is None:
            self.client = OllamaClient()

    def plan(
        self,
        *,
        model_name: str,
        message: str,
        thought_view: ThoughtView,
        conclusion: CoreConclusion,
        decision: SearchNeedDecision,
    ) -> SearchPlan:
        if not model_name.strip() or model_name == 'mk5-graph-core':
            raise SearchQueryPlannerError('search query planner requires a selectable LLM model')
        try:
            result = self.client.chat(
                model_name=model_name,
                messages=[
                    {'role': 'system', 'content': self._build_system_prompt()},
                    {
                        'role': 'user',
                        'content': self._build_user_prompt(
                            message=message,
                            thought_view=thought_view,
                            conclusion=conclusion,
                            decision=decision,
                        ),
                    },
                ],
                stream=False,
                options={'temperature': 0.1},
                response_format='json',
            )
        except OllamaModelNotFoundError as exc:
            raise SearchQueryPlannerError(str(exc)) from exc
        except (OllamaClientError, OllamaResponseError) as exc:
            raise SearchQueryPlannerError(str(exc)) from exc

        payload = self._parse_json(result.content)
        grounding_queries = self._normalize_queries(payload.get('grounding_queries') or [])
        comparison_queries = self._normalize_queries(payload.get('comparison_queries') or [])
        fallback_queries = self._normalize_queries(payload.get('queries') or [])

        queries: list[str] = []
        for item in grounding_queries + comparison_queries + fallback_queries:
            if item in queries:
                continue
            queries.append(item)
            if len(queries) >= 6:
                break
        reason = ' '.join(str(payload.get('reason') or '').split()).strip() or decision.gap_summary
        focus_terms = [
            ' '.join(str(item or '').split()).strip()
            for item in (payload.get('focus_terms') or [])
            if ' '.join(str(item or '').split()).strip()
        ]
        if not queries:
            raise SearchQueryPlannerError('search planner returned no usable queries')
        return SearchPlan(
            queries=queries,
            reason=reason,
            focus_terms=focus_terms[:6],
            metadata={
                'raw': payload,
                'grounding_queries': grounding_queries,
                'comparison_queries': comparison_queries,
            },
        )

    def _build_system_prompt(self) -> str:
        return load_prompt_text(self.system_prompt_path)

    def _build_user_prompt(
        self,
        *,
        message: str,
        thought_view: ThoughtView,
        conclusion: CoreConclusion,
        decision: SearchNeedDecision,
    ) -> str:
        template = load_prompt_text(self.user_prompt_path)
        return template.format(
            user_input=message,
            inferred_intent=conclusion.inferred_intent,
            gap_summary=decision.gap_summary,
            target_terms=self._format_lines(decision.target_terms),
            active_nodes=self._format_active_nodes(thought_view),
            current_summary=conclusion.explanation_summary or '- 없음',
        )

    def _format_lines(self, items: list[str]) -> str:
        if not items:
            return '- 없음'
        return '\n'.join(f'- {item}' for item in items[:6])

    def _format_active_nodes(self, thought_view: ThoughtView) -> str:
        lines: list[str] = []
        seen: set[str] = set()
        for activated in thought_view.seed_nodes:
            node = activated.node
            label = str(node.normalized_value or node.raw_value or '').strip()
            if not label or label in seen:
                continue
            seen.add(label)
            lines.append(f'- {label} (seed)')
            if len(lines) >= 6:
                return '\n'.join(lines)
        for node in thought_view.nodes:
            label = str(node.normalized_value or node.raw_value or '').strip()
            if not label or label in seen:
                continue
            seen.add(label)
            lines.append(f'- {label}')
            if len(lines) >= 6:
                break
        return '\n'.join(lines) if lines else '- 없음'

    def _normalize_queries(self, raw_queries: list[Any]) -> list[str]:
        queries: list[str] = []
        for item in raw_queries:
            token = ' '.join(str(item or '').split()).strip()
            if not token:
                continue
            if token in queries:
                continue
            queries.append(token)
        return queries

    def _parse_json(self, text: str) -> dict[str, Any]:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise SearchQueryPlannerError('search planner returned invalid JSON') from exc
        if not isinstance(payload, dict):
            raise SearchQueryPlannerError('search planner returned non-object JSON')
        return payload
