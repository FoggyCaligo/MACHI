from __future__ import annotations

from core.entities.conclusion import CoreConclusion
from core.verbalization.action_layer_builder import ActionLayerBuilder
from core.verbalization.meaning_preserver import MeaningPreserver
from core.verbalization.ollama_verbalizer import OllamaVerbalizer
from core.verbalization.template_verbalizer import (
    TemplateVerbalizer,
    TemplateVerbalizerDisabledError,
)
from core.verbalization.verbalizer import Verbalizer


def _sample_conclusion() -> CoreConclusion:
    return CoreConclusion(
        session_id='s1',
        message_id=1,
        user_input_summary='Explain the difference between lamellar and chain mail.',
        inferred_intent='open_information_request',
        explanation_summary='Explain the key structural difference directly and stay within grounded scope.',
    )


def test_template_verbalizer_raises_for_user_response() -> None:
    template = TemplateVerbalizer()
    verbalizer = Verbalizer()
    derived_action = verbalizer.action_layer_builder.build(_sample_conclusion())
    try:
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
    assert result.preservation_action == 'block'


def test_meaning_preserver_accepts_non_search_response() -> None:
    conclusion = _sample_conclusion()
    action = ActionLayerBuilder().build(conclusion)
    result = MeaningPreserver().evaluate(
        conclusion=conclusion,
        action_layer=action,
        user_response='I will answer only within the grounded scope.',
    )
    assert result.preserved is True
    assert result.recommended_action == 'accept'


def test_action_layer_builder_marks_search_as_already_attempted() -> None:
    conclusion = _sample_conclusion()
    conclusion.metadata['search_context'] = {
        'attempted': True,
        'result_count': 2,
        'summaries': [{'title': 'A', 'snippet': 'B', 'provider': 'wikipedia-ko'}],
    }
    action = ActionLayerBuilder().build(conclusion)
    assert action.metadata['search_attempted'] is True
    assert action.metadata['search_result_count'] == 2
    assert 'possible range' not in action.answer_goal.lower()
    assert action.answer_goal


def test_ollama_verbalizer_prompt_includes_search_context() -> None:
    conclusion = _sample_conclusion()
    conclusion.metadata['search_context'] = {
        'attempted': True,
        'result_count': 1,
        'summaries': [
            {
                'title': 'Chain mail',
                'snippet': 'Armor made from interlinked metal rings.',
                'provider': 'wikipedia-ko',
                'url': 'https://example.com',
            }
        ],
    }
    action = ActionLayerBuilder().build(conclusion)
    verbalizer = OllamaVerbalizer()
    prompt = verbalizer._build_user_prompt(conclusion, action)
    assert '- attempted: true' in prompt
    assert '- result_count: 1' in prompt
    assert '- evidence: Chain mail (wikipedia-ko): Armor made from interlinked metal rings.' in prompt
