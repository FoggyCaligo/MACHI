from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.entities.conclusion import CoreConclusion, DerivedActionLayer
from tools.ollama_client import (
    OllamaClient,
    OllamaClientError,
    OllamaModelNotFoundError,
    OllamaResponseError,
)
from tools.prompt_loader import load_prompt_text


class OllamaVerbalizerError(RuntimeError):
    pass


@dataclass(slots=True)
class OllamaVerbalizer:
    client: OllamaClient | None = None
    system_prompt_path: str = 'prompts/system/chat_system_prompt.txt'
    user_prompt_path: str = 'prompts/verbalization/verbalization_prompt.txt'

    def __post_init__(self) -> None:
        if self.client is None:
            self.client = OllamaClient()

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
                options={
                    'temperature': 0.2,
                },
            )
        except OllamaModelNotFoundError as exc:
            raise OllamaVerbalizerError(str(exc)) from exc
        except (OllamaClientError, OllamaResponseError) as exc:
            raise OllamaVerbalizerError(str(exc)) from exc
        return result.content

    def _build_system_prompt(self) -> str:
        return load_prompt_text(self.system_prompt_path)

    def _build_user_prompt(self, conclusion: CoreConclusion, action_layer: DerivedActionLayer) -> str:
        search_context = conclusion.metadata.get('search_context', {}) if isinstance(conclusion.metadata, dict) else {}
        template = load_prompt_text(self.user_prompt_path)
        return template.format(
            user_input_summary=conclusion.user_input_summary,
            answer_goal=action_layer.answer_goal,
            surface_summary=conclusion.explanation_summary or '- 없음',
            suggested_actions=self._format_lines(action_layer.suggested_actions),
            do_not_claim=self._format_lines(action_layer.do_not_claim),
            search_status=self._format_search_status(search_context),
        )

    def _format_lines(self, items: list[str]) -> str:
        if not items:
            return '- 없음'
        return '\n'.join(f'- {item}' for item in items)

    def _format_search_status(self, search_context: dict[str, Any]) -> str:
        if not search_context:
            return '- 외부 검색 정보 없음'
        lines: list[str] = []
        lines.append(f"- attempted: {'true' if search_context.get('attempted') else 'false'}")
        lines.append(f"- result_count: {search_context.get('result_count', 0)}")
        if search_context.get('grounded_terms'):
            lines.append(f"- grounded_terms: {' | '.join(search_context.get('grounded_terms', []))}")
        if search_context.get('missing_terms'):
            lines.append(f"- missing_terms: {' | '.join(search_context.get('missing_terms', []))}")
        if search_context.get('error'):
            lines.append(f"- error: {search_context.get('error')}")
        provider_errors = search_context.get('provider_errors') or []
        for item in provider_errors[:3]:
            lines.append(f"- provider_error: {item.get('provider', '-')} | {item.get('error', '-')}")
        return '\n'.join(lines) if lines else '- 외부 검색 정보 없음'
