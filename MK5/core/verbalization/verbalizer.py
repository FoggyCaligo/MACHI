from __future__ import annotations

from dataclasses import dataclass

from core.entities.conclusion import CoreConclusion, DerivedActionLayer
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


    def _should_force_boundary_response(self, conclusion: CoreConclusion) -> bool:
        metadata = conclusion.metadata if isinstance(conclusion.metadata, dict) else {}
        search_context = metadata.get('search_context', {}) if isinstance(metadata, dict) else {}
        if not isinstance(search_context, dict) or not search_context:
            return False
        grounded_terms = list(search_context.get('grounded_terms') or [])
        missing_terms = list(search_context.get('missing_terms') or [])
        result_count = int(search_context.get('result_count') or 0)
        error = str(search_context.get('error') or '').strip()
        no_evidence_found = bool(search_context.get('no_evidence_found'))
        attempted = bool(search_context.get('attempted'))
        need_search = bool(search_context.get('need_search'))
        if result_count > 0 or grounded_terms:
            return False
        if error or no_evidence_found:
            return True
        if need_search and missing_terms:
            return True
        if attempted and missing_terms:
            return True
        return False

    def _build_boundary_response(self, conclusion: CoreConclusion) -> str:
        metadata = conclusion.metadata if isinstance(conclusion.metadata, dict) else {}
        search_context = metadata.get('search_context', {}) if isinstance(metadata, dict) else {}
        missing_terms = list(search_context.get('missing_terms') or [])
        missing_aspects = list(search_context.get('missing_aspects') or [])
        error = str(search_context.get('error') or '').strip()
        parts = ['현재 확보된 근거만으로는 질문에 필요한 내용을 충분히 확인하지 못했습니다.']
        if missing_terms:
            parts.append('아직 확인되지 않은 대상: ' + ', '.join(missing_terms[:4]) + '.')
        if missing_aspects:
            parts.append('아직 확인되지 않은 측면: ' + ', '.join(missing_aspects[:4]) + '.')
        if error:
            parts.append('검색 또는 확인 과정에서 오류가 있어, 확인되지 않은 내용을 추정으로 메우지 않겠습니다.')
        else:
            parts.append('추정으로 빈칸을 메우지 않고, 확인된 정보만 기준으로 다시 답하겠습니다.')
        return ' '.join(parts)

    def verbalize(self, conclusion: CoreConclusion, *, model_name: str = DEFAULT_MODEL_NAME) -> VerbalizationResult:
        derived_action = self.action_layer_builder.build(conclusion)
        internal_explanation = self.template_verbalizer.build_internal_explanation(conclusion)

        if self._should_force_boundary_response(conclusion):
            return VerbalizationResult(
                user_response=self._build_boundary_response(conclusion),
                internal_explanation=internal_explanation,
                derived_action=derived_action,
                used_llm=False,
                llm_error=None,
                llm_error_code=None,
                preservation_reason='deterministic boundary response due to insufficient grounded evidence',
                preservation_action='replace',
                preservation_violations=['insufficient_grounded_evidence'],
            )

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
