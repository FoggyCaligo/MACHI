from __future__ import annotations

from core.entities.conclusion import CoreConclusion, DerivedActionLayer
from core.verbalization.ollama_verbalizer import OllamaVerbalizer
from tools.ollama_client import OllamaClient

from tests.unit.test_ollama_client import OllamaMockServer


def test_ollama_verbalizer_uses_client_transport() -> None:
    server = OllamaMockServer(
        {
            '/api/tags': (200, {'models': []}),
            '/api/chat': (
                200,
                {
                    'model': 'gemma4:e2b',
                    'message': {'content': 'The structure is visible, but the system is still in an early stage.'},
                },
            ),
        }
    )
    server.start()
    try:
        verbalizer = OllamaVerbalizer(client=OllamaClient(base_url=server.base_url, timeout_seconds=2.0))
        response = verbalizer.verbalize(
            model_name='gemma4:e2b',
            conclusion=CoreConclusion(
                session_id='s1',
                message_id=1,
                user_input_summary='Explain MK5 status.',
                inferred_intent='graph_grounded_reasoning',
                activated_concepts=[1, 2],
                key_relations=[10],
                explanation_summary='The graph-based flow exists, but the overall pipeline is still early.',
            ),
            action_layer=DerivedActionLayer(
                response_mode='direct_answer',
                answer_goal='Explain the current status.',
            ),
        )
        assert 'early stage' in response
    finally:
        server.stop()


def test_ollama_verbalizer_compacts_search_context_in_prompt() -> None:
    verbalizer = OllamaVerbalizer()
    prompt = verbalizer._build_user_prompt(
        CoreConclusion(
            session_id='s1',
            message_id=1,
            user_input_summary='Compare armor types.',
            inferred_intent='structure_review',
            explanation_summary='Stay grounded.',
            metadata={
                'search_context': {
                    'need_search': True,
                    'attempted': True,
                    'result_count': 3,
                    'grounded_terms': ['plate armor', 'mail armor', 'lamellar', 'scale armor'],
                    'missing_terms': ['brigandine', 'gambeson', 'leather armor', 'mirror armor'],
                    'missing_aspects': ['mobility', 'protection', 'weight', 'cost'],
                    'provider_errors': [
                        {'provider': 'duckduckgo-web', 'error': 'temporary gateway timeout while fetching a long page'},
                        {'provider': 'wikipedia-en', 'error': 'upstream timeout'},
                        {'provider': 'extra-provider', 'error': 'should not appear'},
                    ],
                    'summaries': [
                        {
                            'title': 'Plate armor overview',
                            'provider': 'wikipedia-en',
                            'snippet': 'Plate armor consists of large metal plates shaped to cover the body and distribute force across rigid surfaces.',
                        },
                        {
                            'title': 'Mail armor overview',
                            'provider': 'wikipedia-en',
                            'snippet': 'Mail armor is built from interlinked metal rings and usually trades piercing resistance for flexibility.',
                        },
                        {
                            'title': 'Lamellar overview',
                            'provider': 'duckduckgo-web',
                            'snippet': 'This third evidence line should be omitted to keep the prompt compact.',
                        },
                    ],
                }
            },
        ),
        DerivedActionLayer(response_mode='structured_explanation', answer_goal='Answer with grounded comparison.'),
    )

    assert '- grounded_terms: plate armor | mail armor | lamellar' in prompt
    assert 'scale armor' not in prompt
    assert '- missing_terms: brigandine | gambeson | leather armor' in prompt
    assert 'mirror armor' not in prompt
    assert '- missing_aspects: mobility | protection | weight' in prompt
    assert 'cost' not in prompt
    assert prompt.count('- provider_error:') == 2
    assert prompt.count('- evidence:') == 2
