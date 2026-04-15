from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from core.entities.conclusion import CoreConclusion
from core.entities.thought_view import ThoughtView
from tools.ollama_client import (
    OllamaClient,
    OllamaClientError,
    OllamaModelNotFoundError,
    OllamaResponseError,
)
from tools.prompt_loader import load_prompt_text


class QuestionSlotPlannerError(RuntimeError):
    pass


PLANNER_OLLAMA_TIMEOUT_SECONDS = 30.0


@dataclass(frozen=True, slots=True)
class RequestedSlot:
    kind: str
    entity: str
    aspect: str = ''

    @property
    def label(self) -> str:
        return f'{self.entity}:{self.aspect}' if self.aspect else self.entity


@dataclass(slots=True)
class QuestionSlotPlan:
    entities: list[str]
    aspects: list[str]
    comparison_axes: list[str] = field(default_factory=list)
    requested_slots: list[RequestedSlot] = field(default_factory=list)
    reason: str = ''
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class QuestionSlotPlanner:
    client: OllamaClient | None = None
    system_prompt_path: str = 'prompts/system/question_slot_planner_system_prompt.txt'
    user_prompt_path: str = 'prompts/search/question_slot_planner_prompt.txt'

    def __post_init__(self) -> None:
        if self.client is None:
            self.client = OllamaClient(timeout_seconds=PLANNER_OLLAMA_TIMEOUT_SECONDS)

    def plan(
        self,
        *,
        model_name: str,
        message: str,
        thought_view: ThoughtView,
        conclusion: CoreConclusion,
        target_terms: list[str],
    ) -> QuestionSlotPlan:
        if not model_name.strip() or model_name == 'mk5-graph-core':
            raise QuestionSlotPlannerError('question slot planner requires a selectable LLM model')
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
                            target_terms=target_terms,
                        ),
                    },
                ],
                stream=False,
                options={'temperature': 0.1},
                response_format='json',
            )
        except OllamaModelNotFoundError as exc:
            raise QuestionSlotPlannerError(str(exc)) from exc
        except (OllamaClientError, OllamaResponseError) as exc:
            raise QuestionSlotPlannerError(str(exc)) from exc

        payload = self._parse_json(result.content)
        entities = self._dedupe_items(payload.get('entities') or [], limit=6)
        search_aspects = self._dedupe_items(
            payload.get('search_aspects') or payload.get('aspects') or [],
            limit=6,
        )
        comparison_axes = self._dedupe_items(payload.get('comparison_axes') or [], limit=6)
        if not entities:
            raise QuestionSlotPlannerError('question slot planner returned no usable entities')

        requested_slots: list[RequestedSlot] = []
        seen_labels: set[str] = set()
        for entity in entities:
            self._append_slot(requested_slots, seen_labels, RequestedSlot(kind='entity', entity=entity))
            for aspect in search_aspects:
                self._append_slot(requested_slots, seen_labels, RequestedSlot(kind='aspect', entity=entity, aspect=aspect))

        reason = ' '.join(str(payload.get('reason') or '').split()).strip() or '질문의 대상 개념과 검색용 사실 축을 분리했다.'
        return QuestionSlotPlan(
            entities=entities,
            aspects=search_aspects,
            comparison_axes=comparison_axes,
            requested_slots=requested_slots,
            reason=reason,
            metadata={'raw': payload},
        )

    def _build_system_prompt(self) -> str:
        return load_prompt_text(self.system_prompt_path)

    def _build_user_prompt(self, *, message: str, thought_view: ThoughtView, conclusion: CoreConclusion, target_terms: list[str]) -> str:
        template = load_prompt_text(self.user_prompt_path)
        return template.format(
            user_input=message,
            inferred_intent=conclusion.inferred_intent,
            target_terms=self._format_lines(target_terms),
            active_nodes=self._format_active_nodes(thought_view),
            current_summary=conclusion.explanation_summary or '- 없음',
        )

    def _format_lines(self, items: list[str]) -> str:
        if not items:
            return '- 없음'
        return '\n'.join(f'- {item}' for item in items[:8])

    def _format_active_nodes(self, thought_view: ThoughtView) -> str:
        lines: list[str] = []
        seen: set[str] = set()
        for activated in thought_view.seed_nodes:
            node = activated.node
            label = str(getattr(node, 'normalized_value', '') or getattr(node, 'raw_value', '') or '').strip()
            if not label or label in seen:
                continue
            seen.add(label)
            lines.append(f'- {label} (seed)')
            if len(lines) >= 8:
                return '\n'.join(lines)
        for node in thought_view.nodes:
            label = str(getattr(node, 'normalized_value', '') or getattr(node, 'raw_value', '') or '').strip()
            if not label or label in seen:
                continue
            seen.add(label)
            lines.append(f'- {label}')
            if len(lines) >= 8:
                break
        return '\n'.join(lines) if lines else '- 없음'

    def _parse_json(self, text: str) -> dict[str, Any]:
        raw = str(text or '').strip()
        candidates = [raw]
        fenced = self._extract_fenced_json(raw)
        if fenced:
            candidates.append(fenced)
        bracketed = self._extract_braced_json(raw)
        if bracketed and bracketed not in candidates:
            candidates.append(bracketed)

        for candidate in candidates:
            if not candidate:
                continue
            try:
                payload = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                return payload
        raise QuestionSlotPlannerError('question slot planner returned invalid JSON')

    def _extract_fenced_json(self, text: str) -> str:
        marker = '```'
        if marker not in text:
            return ''
        parts = text.split(marker)
        for chunk in parts[1:]:
            normalized = chunk.strip()
            if normalized.startswith('json'):
                normalized = normalized[4:].strip()
            if normalized.startswith('{') and normalized.endswith('}'):
                return normalized
        return ''

    def _extract_braced_json(self, text: str) -> str:
        start = text.find('{')
        end = text.rfind('}')
        if start == -1 or end == -1 or end <= start:
            return ''
        return text[start:end + 1]

    def _dedupe_items(self, items: list[Any], *, limit: int) -> list[str]:
        tokens: list[str] = []
        for item in items:
            token = ' '.join(str(item or '').split()).strip()
            if not token or token in tokens:
                continue
            tokens.append(token)
            if len(tokens) >= limit:
                break
        return tokens

    def _append_slot(self, slots: list[RequestedSlot], seen_labels: set[str], slot: RequestedSlot) -> None:
        if slot.label in seen_labels:
            return
        seen_labels.add(slot.label)
        slots.append(slot)
