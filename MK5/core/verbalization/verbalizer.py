from __future__ import annotations

from dataclasses import dataclass

from core.entities.conclusion import CoreConclusion, DerivedActionLayer
from core.verbalization.action_layer_builder import ActionLayerBuilder
from core.verbalization.ollama_verbalizer import OllamaVerbalizer, OllamaVerbalizerError
from core.verbalization.template_verbalizer import TemplateVerbalizer

DEFAULT_MODEL_NAME = 'mk5-graph-core'


@dataclass(slots=True)
class VerbalizationResult:
    user_response: str
    internal_explanation: str
    derived_action: DerivedActionLayer
    used_llm: bool = False
    llm_error: str | None = None


@dataclass(slots=True)
class Verbalizer:
    template_verbalizer: TemplateVerbalizer | None = None
    action_layer_builder: ActionLayerBuilder | None = None
    ollama_verbalizer: OllamaVerbalizer | None = None

    def __post_init__(self) -> None:
        if self.template_verbalizer is None:
            self.template_verbalizer = TemplateVerbalizer()
        if self.action_layer_builder is None:
            self.action_layer_builder = ActionLayerBuilder()
        if self.ollama_verbalizer is None:
            self.ollama_verbalizer = OllamaVerbalizer()

    def verbalize(self, conclusion: CoreConclusion, *, model_name: str = DEFAULT_MODEL_NAME) -> VerbalizationResult:
        derived_action = self.action_layer_builder.build(conclusion)
        internal_explanation = self.template_verbalizer.build_internal_explanation(conclusion)

        if not model_name or model_name == DEFAULT_MODEL_NAME:
            return VerbalizationResult(
                user_response=self.template_verbalizer.build_user_response(conclusion, derived_action),
                internal_explanation=internal_explanation,
                derived_action=derived_action,
                used_llm=False,
                llm_error=None,
            )

        try:
            user_response = self.ollama_verbalizer.verbalize(
                model_name=model_name,
                conclusion=conclusion,
                action_layer=derived_action,
            )
            return VerbalizationResult(
                user_response=user_response,
                internal_explanation=internal_explanation,
                derived_action=derived_action,
                used_llm=True,
                llm_error=None,
            )
        except OllamaVerbalizerError as exc:
            return VerbalizationResult(
                user_response=self.template_verbalizer.build_user_response(conclusion, derived_action),
                internal_explanation=internal_explanation,
                derived_action=derived_action,
                used_llm=False,
                llm_error=str(exc),
            )
