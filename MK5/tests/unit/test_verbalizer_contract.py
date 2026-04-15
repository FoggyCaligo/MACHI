from __future__ import annotations

from core.entities.conclusion import CoreConclusion
from core.verbalization.template_verbalizer import (
    TemplateVerbalizer,
    TemplateVerbalizerDisabledError,
)
from core.verbalization.verbalizer import Verbalizer


def _sample_conclusion() -> CoreConclusion:
    return CoreConclusion(
        session_id='s1',
        message_id=1,
        user_input_summary='찰갑과 체인메일의 차이를 알려줘',
        inferred_intent='open_information_request',
        explanation_summary='질문과 관련된 확보된 맥락이 아직 충분하지 않아 가능한 범위만 신중하게 말하는 편이 맞다.',
    )


def test_template_verbalizer_raises_for_user_response() -> None:
    template = TemplateVerbalizer()
    try:
        verbalizer = Verbalizer()
        derived_action = verbalizer.action_layer_builder.build(_sample_conclusion())
        template.build_user_response(_sample_conclusion(), derived_action)
        raise AssertionError('Expected TemplateVerbalizerDisabledError')
    except TemplateVerbalizerDisabledError:
        pass


def test_verbalizer_without_selected_model_returns_explicit_error() -> None:
    verbalizer = Verbalizer()
    result = verbalizer.verbalize(_sample_conclusion(), model_name='mk5-graph-core')
    assert result.user_response == ''
    assert result.used_llm is False
    assert result.llm_error == 'template_verbalizer_disabled:model_not_selected'
