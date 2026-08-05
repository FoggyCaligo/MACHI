from __future__ import annotations

from core.entities.conclusion import CoreConclusion
from core.verbalization.action_layer_builder import ActionLayerBuilder
from core.verbalization.meaning_preserver import MeaningPreserver, MeaningPreservationResult
from core.verbalization.ollama_verbalizer import OllamaVerbalizer
from core.verbalization.template_verbalizer import (
    TemplateVerbalizer,
    TemplateVerbalizerDisabledError,
)
from core.verbalization.verbalizer import Verbalizer


class StubMeaningPreserver(MeaningPreserver):
    def evaluate(self, *, conclusion, action_layer, user_response: str) -> MeaningPreservationResult:
        return MeaningPreservationResult(
            preserved=False,
            severity='warn',
            recommended_action='replace',
            violations=['internal_fallback_candidate'],
            safe_response='INTERNAL SAFE RESPONSE',
            reason='stubbed replacement request',
        )


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
    result = verbalizer.verbalize(_sample_conclusion(), model_name='MK3-graph-core')
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


def test_verbalizer_blocks_replacement_fallback_from_becoming_user_response() -> None:
    verbalizer = Verbalizer(
        ollama_verbalizer=type(
            'StubOllama',
            (),
            {
                'verbalize': lambda self, *, model_name, conclusion, action_layer: 'USER VISIBLE ANSWER',
            },
        )(),
        meaning_preserver=StubMeaningPreserver(),
    )

    result = verbalizer.verbalize(_sample_conclusion(), model_name='gemma3:4b')

    assert result.user_response == ''
    assert result.used_llm is False
    assert result.llm_error == 'meaning_preserver_blocked:replace'
    assert result.llm_error_code == 'preservation_replace_blocked'
    assert result.preservation_action == 'block'
    assert 'internal_fallback_candidate' in (result.preservation_violations or [])


def test_meaning_preserver_blocks_ungrounded_search_error_response() -> None:
    conclusion = _sample_conclusion()
    conclusion.metadata['search_context'] = {
        'need_search': True,
        'attempted': True,
        'result_count': 0,
        'error': 'question slot planner returned no usable entities',
    }
    action = ActionLayerBuilder().build(conclusion)

    result = MeaningPreserver().evaluate(
        conclusion=conclusion,
        action_layer=action,
        user_response='글록은 1960년대 독일에서 개발되었습니다.',
    )

    assert result.preserved is False
    assert result.recommended_action == 'block'
    assert result.violations == ['search_error_unresolved']


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


def test_action_layer_builder_prefers_recent_memory_for_memory_probe() -> None:
    conclusion = CoreConclusion(
        session_id='s1',
        message_id=2,
        user_input_summary='What do you remember about me?',
        inferred_intent='memory_probe',
        explanation_summary='Memory recall turn.',
        metadata={
            'recent_memory_count': 3,
            'recent_memory_messages': [
                {'role': 'user', 'turn_index': 1, 'content': 'My name is Jay.'},
                {'role': 'assistant', 'turn_index': 1, 'content': 'I will call you Jay.'},
            ],
        },
    )
    action = ActionLayerBuilder().build(conclusion)
    assert action.response_mode == 'structured_explanation'
    assert action.answer_goal == 'Answer naturally using recent conversation memory when it helps the user.'
    assert action.metadata['recent_memory_count'] == 3
