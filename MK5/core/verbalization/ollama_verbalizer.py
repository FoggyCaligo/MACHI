from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from config import (
    VERBALIZER_NUM_PREDICT,
    VERBALIZER_OLLAMA_TIMEOUT_SECONDS,
    VERBALIZER_TEMPERATURE,
    build_ollama_options,
)
from core.entities.conclusion import CoreConclusion, DerivedActionLayer
from tools.ollama_client import (
    OllamaClient,
    OllamaClientError,
    OllamaModelNotFoundError,
    OllamaResponseError,
    OllamaTimeoutError,
)
from tools.prompt_loader import load_prompt_text


class OllamaVerbalizerError(RuntimeError):
    pass


class OllamaVerbalizerTimeoutError(OllamaVerbalizerError):
    pass


@dataclass(slots=True)
class OllamaVerbalizer:
    client: OllamaClient | None = None
    system_prompt_path: str = 'prompts/system/chat_system_prompt.txt'
    user_prompt_path: str = 'prompts/verbalization/verbalization_prompt.txt'

    def __post_init__(self) -> None:
        if self.client is None:
            self.client = OllamaClient(timeout_seconds=VERBALIZER_OLLAMA_TIMEOUT_SECONDS)

    def verbalize(
        self,
        *,
        model_name: str,
        conclusion: CoreConclusion,
        action_layer: DerivedActionLayer,
    ) -> str:
        try:
            result = self.client.chat(
                model_name=model_name,
                messages=[
                    {
                        'role': 'system',
                        'content': self._build_system_prompt(),
                    },
                    {
                        'role': 'user',
                        'content': self._build_user_prompt(conclusion, action_layer),
                    },
                ],
                stream=False,
                options=build_ollama_options(
                    temperature=VERBALIZER_TEMPERATURE,
                    num_predict=VERBALIZER_NUM_PREDICT,
                ),
            )
        except OllamaModelNotFoundError as exc:
            raise OllamaVerbalizerError(str(exc)) from exc
        except OllamaTimeoutError as exc:
            raise OllamaVerbalizerTimeoutError(str(exc)) from exc
        except (OllamaClientError, OllamaResponseError) as exc:
            raise OllamaVerbalizerError(str(exc)) from exc
        return result.content

    def _build_system_prompt(self) -> str:
        return load_prompt_text(self.system_prompt_path)

    def _build_user_prompt(self, conclusion: CoreConclusion, action_layer: DerivedActionLayer) -> str:
        metadata = conclusion.metadata if isinstance(conclusion.metadata, dict) else {}
        search_context = metadata.get('search_context', {}) if isinstance(metadata, dict) else {}
        template = load_prompt_text(self.user_prompt_path)
        return template.format(
            user_input_summary=conclusion.user_input_summary,
            answer_goal=action_layer.answer_goal,
            surface_summary=conclusion.explanation_summary or '- none',
            memory_status=self._format_memory_status(metadata),
            suggested_actions=self._format_lines(action_layer.suggested_actions),
            do_not_claim=self._format_lines(action_layer.do_not_claim),
            search_status=self._format_search_status(search_context),
        )

    def _format_lines(self, items: list[str]) -> str:
        if not items:
            return '- none'
        return '\n'.join(f'- {self._truncate(item, 120)}' for item in items[:6])

    def _format_memory_status(self, metadata: dict[str, Any]) -> str:
        recent_memory_messages = list(metadata.get('recent_memory_messages') or [])
        recent_memory_count = int(metadata.get('recent_memory_count') or len(recent_memory_messages))
        topic_terms = [self._truncate(item, 40) for item in (metadata.get('topic_terms') or [])[:3]]
        previous_topic_terms = [self._truncate(item, 40) for item in (metadata.get('previous_topic_terms') or [])[:3]]
        lines: list[str] = [f'- recent_memory_count: {recent_memory_count}']
        if metadata.get('topic_continuity'):
            lines.append(f"- topic_continuity: {self._truncate(metadata.get('topic_continuity'), 40)}")
        if topic_terms:
            lines.append(f"- topic_terms: {' | '.join(topic_terms)}")
        if previous_topic_terms:
            lines.append(f"- previous_topic_terms: {' | '.join(previous_topic_terms)}")

        for item in recent_memory_messages[-6:]:
            role_token = ' '.join(str(item.get('role') or '').split()).strip().lower()
            if role_token != 'user':
                continue
            role = self._truncate(item.get('role', '-'), 16)
            turn_index = item.get('turn_index', '-')
            content = self._truncate(item.get('content', ''), 140)
            lines.append(f'- memory: turn={turn_index} role={role} content={content}')
            snapshot = item.get('intent_snapshot') or {}
            if isinstance(snapshot, dict) and snapshot.get('snapshot_intent'):
                topic_snapshot_terms = [self._truncate(term, 28) for term in (snapshot.get('topic_terms') or [])[:2]]
                snapshot_line = f"- memory_snapshot: {self._truncate(snapshot.get('snapshot_intent'), 32)}"
                if topic_snapshot_terms:
                    snapshot_line += f" | {' | '.join(topic_snapshot_terms)}"
                lines.append(snapshot_line)
        return '\n'.join(lines) if lines else '- no memory context'

    def _format_search_status(self, search_context: dict[str, Any]) -> str:
        if not search_context:
            return '- search_context: none'

        grounded_terms = [self._truncate(item, 40) for item in (search_context.get('grounded_terms') or [])[:3]]
        missing_terms = [self._truncate(item, 40) for item in (search_context.get('missing_terms') or [])[:3]]
        missing_aspects = [self._truncate(item, 40) for item in (search_context.get('missing_aspects') or [])[:3]]
        evidence_available = bool(search_context.get('evidence_available'))
        coverage_unconfirmed = bool(search_context.get('coverage_unconfirmed'))
        lines: list[str] = [
            f"- need_search: {'true' if search_context.get('need_search') else 'false'}",
            f"- attempted: {'true' if search_context.get('attempted') else 'false'}",
            f"- result_count: {search_context.get('result_count', 0)}",
        ]
        if search_context.get('no_evidence_found'):
            lines.append('- no_evidence_found: true')
        if evidence_available:
            lines.append('- evidence_available: true')
        if coverage_unconfirmed:
            lines.append('- coverage_unconfirmed: true')
        if grounded_terms:
            lines.append(f"- grounded_terms: {' | '.join(grounded_terms)}")
        if missing_terms:
            lines.append(f"- missing_terms: {' | '.join(missing_terms)}")
        if missing_aspects:
            lines.append(f"- missing_aspects: {' | '.join(missing_aspects)}")
        if search_context.get('error'):
            lines.append(f"- error: {self._truncate(search_context.get('error'), 160)}")

        provider_errors = search_context.get('provider_errors') or []
        for item in provider_errors[:2]:
            lines.append(
                f"- provider_error: {self._truncate(item.get('provider', '-'), 40)} | {self._truncate(item.get('error', '-'), 100)}"
            )

        summaries = search_context.get('summaries') or []
        for item in summaries[:2]:
            passages = item.get('passages') or []
            evidence_text = ''
            if isinstance(passages, list) and passages:
                evidence_text = str(passages[0] or '')
            if not evidence_text:
                evidence_text = str(item.get('snippet') or '')
            lines.append(
                f"- evidence: {self._truncate(item.get('title', '-'), 60)} ({self._truncate(item.get('provider', '-'), 24)}): {self._truncate(evidence_text, 180)}"
            )

        return '\n'.join(lines) if lines else '- search_context: none'

    def _truncate(self, value: Any, limit: int) -> str:
        text = ' '.join(str(value or '').split()).strip()
        if len(text) <= limit:
            return text
        return f'{text[: max(0, limit - 3)]}...'
