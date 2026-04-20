from __future__ import annotations

from dataclasses import dataclass

from core.entities.conclusion import DerivedActionLayer
from core.entities.conclusion_view import ConclusionView
from core.verbalization.action_layer_builder import ActionLayerBuilder
from core.verbalization.meaning_preserver import MeaningPreserver
from core.verbalization.ollama_verbalizer import (
    OllamaVerbalizer,
    OllamaVerbalizerError,
    OllamaVerbalizerTimeoutError,
)
from core.verbalization.template_verbalizer import TemplateVerbalizer

DEFAULT_MODEL_NAME = 'mk5-graph-core'


@dataclass(slots=True)
class VerbalizationResult:
    user_response: str
    internal_explanation: str
    derived_action: DerivedActionLayer
    used_llm: bool = False
    llm_error: str | None = None
    llm_error_code: str | None = None
    preservation_reason: str = ''
    preservation_action: str = 'accept'
    preservation_violations: list[str] | None = None


@dataclass(slots=True)
class Verbalizer:
    template_verbalizer: TemplateVerbalizer | None = None
    action_layer_builder: ActionLayerBuilder | None = None
    ollama_verbalizer: OllamaVerbalizer | None = None
    meaning_preserver: MeaningPreserver | None = None

    def __post_init__(self) -> None:
        if self.template_verbalizer is None:
            self.template_verbalizer = TemplateVerbalizer()
        if self.action_layer_builder is None:
            self.action_layer_builder = ActionLayerBuilder()
        if self.ollama_verbalizer is None:
            self.ollama_verbalizer = OllamaVerbalizer()
        if self.meaning_preserver is None:
            self.meaning_preserver = MeaningPreserver()

    def verbalize(self, conclusion: ConclusionView, *, model_name: str = DEFAULT_MODEL_NAME) -> VerbalizationResult:
        derived_action = self.action_layer_builder.build(conclusion)
        internal_explanation = self.template_verbalizer.build_internal_explanation(conclusion)

        if not model_name or model_name == DEFAULT_MODEL_NAME:
            return VerbalizationResult(
                user_response='',
                internal_explanation=internal_explanation,
                derived_action=derived_action,
                used_llm=False,
                llm_error='template_verbalizer_disabled:model_not_selected',
                llm_error_code='model_not_selected',
                preservation_reason='verbalization not attempted because no selectable model was provided',
                preservation_action='block',
                preservation_violations=['model_not_selected'],
            )

        try:
            user_response = self.ollama_verbalizer.verbalize(
                model_name=model_name,
                conclusion=conclusion,
                action_layer=derived_action,
            )
            preservation = self.meaning_preserver.evaluate(
                conclusion=conclusion,
                action_layer=derived_action,
                user_response=user_response,
            )
            final_response = preservation.safe_response if preservation.recommended_action == 'replace' else user_response
            return VerbalizationResult(
                user_response=final_response,
                internal_explanation=internal_explanation,
                derived_action=derived_action,
                used_llm=True,
                llm_error=None,
                llm_error_code=None,
                preservation_reason=preservation.reason,
                preservation_action=preservation.recommended_action,
                preservation_violations=list(preservation.violations),
            )
        except OllamaVerbalizerTimeoutError as exc:
            return VerbalizationResult(
                user_response='',
                internal_explanation=internal_explanation,
                derived_action=derived_action,
                used_llm=False,
                llm_error=f'llm_verbalization_failed:{exc}',
                llm_error_code='timeout',
                preservation_reason='verbalizer timed out before preservation review',
                preservation_action='block',
                preservation_violations=['timeout'],
            )
        except OllamaVerbalizerError as exc:
            return VerbalizationResult(
                user_response='',
                internal_explanation=internal_explanation,
                derived_action=derived_action,
                used_llm=False,
                llm_error=f'llm_verbalization_failed:{exc}',
                llm_error_code='llm_error',
                preservation_reason='verbalizer failed before preservation review',
                preservation_action='block',
                preservation_violations=['llm_error'],
            )
