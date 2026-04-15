from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

from config import (
    SEARCH_COVERAGE_REFINER_NUM_PREDICT,
    SEARCH_COVERAGE_REFINER_TEMPERATURE,
    SEARCH_COVERAGE_REFINER_TIMEOUT_SECONDS,
    build_ollama_options,
)
from core.entities.conclusion import CoreConclusion
from core.search.question_slot_planner import QuestionSlotPlan, RequestedSlot
from tools.ollama_client import (
    OllamaClient,
    OllamaClientError,
    OllamaModelNotFoundError,
    OllamaResponseError,
)
from tools.prompt_loader import load_prompt_text

if TYPE_CHECKING:
    from core.search.search_sidecar import SearchEvidence


class SearchCoverageRefinerError(RuntimeError):
    pass


@dataclass(slots=True)
class SearchCoverageAnalysis:
    covered_slot_labels: list[str]
    missing_slot_labels: list[str]
    reason: str


@dataclass(slots=True)
class SearchCoverageRefiner:
    client: OllamaClient | None = None
    system_prompt_path: str = 'prompts/system/search_coverage_refiner_system_prompt.txt'
    user_prompt_path: str = 'prompts/search/search_coverage_refiner_prompt.txt'

    def __post_init__(self) -> None:
        if self.client is None:
            self.client = OllamaClient(timeout_seconds=SEARCH_COVERAGE_REFINER_TIMEOUT_SECONDS)

    def refine(
        self,
        *,
        model_name: str,
        message: str,
        conclusion: CoreConclusion,
        slot_plan: QuestionSlotPlan,
        evidences: list['SearchEvidence'],
    ) -> SearchCoverageAnalysis:
        if not model_name.strip() or model_name == 'mk5-graph-core':
            raise SearchCoverageRefinerError('search coverage refiner requires a selectable LLM model')
        try:
            result = self.client.chat(
                model_name=model_name,
                messages=[
                    {'role': 'system', 'content': self._build_system_prompt()},
                    {
                        'role': 'user',
                        'content': self._build_user_prompt(
                            message=message,
                            conclusion=conclusion,
                            slot_plan=slot_plan,
                            evidences=evidences,
                        ),
                    },
                ],
                stream=False,
                options=build_ollama_options(
                    temperature=SEARCH_COVERAGE_REFINER_TEMPERATURE,
                    num_predict=SEARCH_COVERAGE_REFINER_NUM_PREDICT,
                ),
                response_format='json',
            )
        except OllamaModelNotFoundError as exc:
            raise SearchCoverageRefinerError(str(exc)) from exc
        except (OllamaClientError, OllamaResponseError) as exc:
            raise SearchCoverageRefinerError(str(exc)) from exc

        payload = self._parse_json(result.content)
        requested_labels = [slot.label for slot in slot_plan.requested_slots]
        covered_labels = self._normalize_labels(payload.get('covered_slot_labels') or [], requested_labels)
        missing_labels = self._normalize_labels(payload.get('missing_slot_labels') or [], requested_labels)

        if not missing_labels:
            missing_labels = [label for label in requested_labels if label not in covered_labels]
        if not covered_labels:
            covered_labels = [label for label in requested_labels if label not in missing_labels]

        reason = ' '.join(str(payload.get('reason') or '').split()).strip() or 'search evidence based slot coverage refinement'
        return SearchCoverageAnalysis(
            covered_slot_labels=covered_labels,
            missing_slot_labels=missing_labels,
            reason=reason,
        )

    def _build_system_prompt(self) -> str:
        return load_prompt_text(self.system_prompt_path)

    def _build_user_prompt(
        self,
        *,
        message: str,
        conclusion: CoreConclusion,
        slot_plan: QuestionSlotPlan,
        evidences: list['SearchEvidence'],
    ) -> str:
        template = load_prompt_text(self.user_prompt_path)
        return template.format(
            user_input=message,
            inferred_intent=conclusion.inferred_intent,
            requested_slots=self._format_requested_slots(slot_plan.requested_slots),
            comparison_axes=self._format_lines(slot_plan.comparison_axes),
            evidence_summaries=self._format_evidences(evidences),
            current_summary=conclusion.explanation_summary or '- 없음',
        )

    def _format_requested_slots(self, slots: list[RequestedSlot]) -> str:
        if not slots:
            return '- 없음'
        return '\n'.join(f'- {slot.label}' for slot in slots)

    def _format_lines(self, items: list[str]) -> str:
        if not items:
            return '- 없음'
        return '\n'.join(f'- {item}' for item in items[:8])

    def _format_evidences(self, evidences: list['SearchEvidence']) -> str:
        if not evidences:
            return '- 없음'
        lines: list[str] = []
        for index, item in enumerate(evidences[:6], start=1):
            lines.append(
                f'{index}. [{item.provider or "-"}] {item.title or "-"} | {item.snippet or "-"}'
            )
        return '\n'.join(lines)

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
        raise SearchCoverageRefinerError('search coverage refiner returned invalid JSON')

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

    def _normalize_labels(self, values: list[Any], requested_labels: list[str]) -> list[str]:
        normalized: list[str] = []
        allowed = set(requested_labels)
        for item in values:
            label = ' '.join(str(item or '').split()).strip()
            if not label or label not in allowed or label in normalized:
                continue
            normalized.append(label)
        return normalized
