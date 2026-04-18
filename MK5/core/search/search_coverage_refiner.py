from __future__ import annotations

import json
from dataclasses import dataclass, field
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
class SlotCoverageSupport:
    slot_label: str
    supported: bool
    evidence_indices: list[int] = field(default_factory=list)


@dataclass(slots=True)
class SearchCoverageAnalysis:
    slot_supports: list[SlotCoverageSupport]
    reason: str

    @property
    def covered_slot_labels(self) -> list[str]:
        return [item.slot_label for item in self.slot_supports if item.supported]

    @property
    def missing_slot_labels(self) -> list[str]:
        return [item.slot_label for item in self.slot_supports if not item.supported]


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
        slot_supports = self._normalize_slot_supports(
            payload=payload,
            requested_labels=requested_labels,
            evidence_count=len(evidences),
        )

        reason = ' '.join(str(payload.get('reason') or '').split()).strip() or 'search evidence passage based slot coverage refinement'
        return SearchCoverageAnalysis(
            slot_supports=slot_supports,
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
            evidence_payload=self._format_evidences(evidences),
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
            lines.append(f'{index}. [{item.provider or "-"}] {item.title or "-"}')
            lines.append(f'   - url: {item.url or "-"}')
            lines.append(f'   - snippet: {item.snippet or "-"}')
            passages = list(item.passages[:2]) if getattr(item, 'passages', None) else []
            if passages:
                for passage in passages:
                    lines.append(f'   - passage: {passage}')
            else:
                lines.append('   - passage: -')
        return '\n'.join(lines)

    def _normalize_slot_supports(
        self,
        *,
        payload: dict[str, Any],
        requested_labels: list[str],
        evidence_count: int,
    ) -> list[SlotCoverageSupport]:
        raw_supports = payload.get('slot_support') or payload.get('slot_supports') or []
        normalized: list[SlotCoverageSupport] = []
        seen: set[str] = set()
        if isinstance(raw_supports, list):
            for item in raw_supports:
                if not isinstance(item, dict):
                    continue
                label = self._normalize_label(item.get('slot_label') or item.get('label') or '', requested_labels)
                if not label or label in seen:
                    continue
                evidence_indices = self._normalize_evidence_indices(item.get('evidence_indices') or [], evidence_count=evidence_count)
                supported = bool(item.get('supported')) and bool(evidence_indices)
                normalized.append(
                    SlotCoverageSupport(
                        slot_label=label,
                        supported=supported,
                        evidence_indices=evidence_indices if supported else [],
                    )
                )
                seen.add(label)

        if not normalized:
            covered_labels = self._normalize_labels(payload.get('covered_slot_labels') or [], requested_labels)
            missing_labels = self._normalize_labels(payload.get('missing_slot_labels') or [], requested_labels)
            for label in requested_labels:
                if label in covered_labels:
                    normalized.append(SlotCoverageSupport(slot_label=label, supported=True, evidence_indices=[1] if evidence_count > 0 else []))
                elif label in missing_labels:
                    normalized.append(SlotCoverageSupport(slot_label=label, supported=False, evidence_indices=[]))

        support_by_label = {item.slot_label: item for item in normalized}
        finalized: list[SlotCoverageSupport] = []
        for label in requested_labels:
            existing = support_by_label.get(label)
            if existing is None:
                finalized.append(SlotCoverageSupport(slot_label=label, supported=False, evidence_indices=[]))
                continue
            if existing.supported and not existing.evidence_indices:
                finalized.append(SlotCoverageSupport(slot_label=label, supported=False, evidence_indices=[]))
                continue
            finalized.append(existing)
        return finalized

    def _normalize_labels(self, labels: list[Any], requested_labels: list[str]) -> list[str]:
        normalized: list[str] = []
        for item in labels:
            label = self._normalize_label(item, requested_labels)
            if not label or label in normalized:
                continue
            normalized.append(label)
        return normalized

    def _normalize_label(self, value: Any, requested_labels: list[str]) -> str:
        candidate = ' '.join(str(value or '').split()).strip()
        return candidate if candidate in requested_labels else ''

    def _normalize_evidence_indices(self, values: Any, *, evidence_count: int) -> list[int]:
        if not isinstance(values, list):
            return []
        indices: list[int] = []
        for value in values:
            try:
                index = int(value)
            except (TypeError, ValueError):
                continue
            if index < 1 or index > evidence_count or index in indices:
                continue
            indices.append(index)
        return indices

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
