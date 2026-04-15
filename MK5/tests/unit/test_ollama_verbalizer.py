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
                    'message': {'content': '구조는 괜찮아 보여. 다만 아직은 초기형이야.'},
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
                user_input_summary='MK5 상태를 설명해줘',
                inferred_intent='graph_grounded_reasoning',
                activated_concepts=[1, 2],
                key_relations=[10],
                explanation_summary='현재 그래프 기반 사고 흐름의 초기형이다.',
            ),
            action_layer=DerivedActionLayer(
                response_mode='direct_answer',
                answer_goal='현재 상태를 설명한다',
            ),
        )
        assert '초기형' in response
    finally:
        server.stop()
