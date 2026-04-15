from __future__ import annotations

from dataclasses import dataclass

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
        template = load_prompt_text(self.user_prompt_path)
        return template.format(
            user_input_summary=conclusion.user_input_summary,
            answer_goal=action_layer.answer_goal,
            surface_summary=conclusion.explanation_summary,
            suggested_actions=self._format_lines(action_layer.suggested_actions),
            do_not_claim=self._format_lines(action_layer.do_not_claim),
        )

    def _format_lines(self, items: list[str]) -> str:
        if not items:
            return '- 없음'
        return '\n'.join(f'- {item}' for item in items)
