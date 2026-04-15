from __future__ import annotations

from core.entities.conclusion import CoreConclusion
from core.verbalization.action_layer_builder import ActionLayerBuilder
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
        user_input_summary='찰갑과 체인메일의 차이를 알려줘',
        inferred_intent='open_information_request',
        explanation_summary='질문의 핵심 차이, 사실, 이유 같은 내용을 바로 설명한다.',
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
    assert '검색하겠다고 예고하지 않는다.' in action.answer_goal


def test_ollama_verbalizer_prompt_includes_search_context() -> None:
    conclusion = _sample_conclusion()
    conclusion.metadata['search_context'] = {
        'attempted': True,
        'result_count': 1,
        'summaries': [
            {
                'title': '체인메일',
                'snippet': '고리들을 엮어 만든 갑옷이다.',
                'provider': 'wikipedia-ko',
                'url': 'https://example.com',
            }
        ],
    }
    action = ActionLayerBuilder().build(conclusion)
    verbalizer = OllamaVerbalizer()
    prompt = verbalizer._build_user_prompt(conclusion, action)
    assert '이번 턴의 검색 결과' in prompt
    assert '검색 결과 1건 확보' in prompt
    assert '체인메일 (wikipedia-ko): 고리들을 엮어 만든 갑옷이다.' in prompt
