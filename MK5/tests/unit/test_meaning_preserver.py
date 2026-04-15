from __future__ import annotations

from core.entities.conclusion import CoreConclusion, DerivedActionLayer
from core.verbalization.meaning_preserver import MeaningPreserver
from core.verbalization.verbalizer import Verbalizer


class StubOllamaVerbalizer:
    def __init__(self, response: str) -> None:
        self.response = response

    def verbalize(self, *, model_name: str, conclusion: CoreConclusion, action_layer: DerivedActionLayer) -> str:
        return self.response


def _conclusion() -> CoreConclusion:
    return CoreConclusion(
        session_id='s1',
        message_id=1,
        user_input_summary='compare armor',
        inferred_intent='structure_review',
        explanation_summary='need grounded comparison',
    )


def test_meaning_preserver_replaces_response_when_no_evidence_found() -> None:
    conclusion = _conclusion()
    conclusion.metadata['search_context'] = {
        'need_search': True,
        'attempted': True,
        'result_count': 0,
        'missing_terms': ['plate armor', 'mail armor'],
        'missing_aspects': ['construction'],
        'no_evidence_found': True,
    }
    action = DerivedActionLayer(response_mode='structured_explanation', answer_goal='stay grounded')

    result = MeaningPreserver().evaluate(
        conclusion=conclusion,
        action_layer=action,
        user_response='Plate armor is stronger and mail armor is lighter.',
    )

    assert result.preserved is False
    assert result.recommended_action == 'replace'
    assert 'no_evidence_found' in result.violations
    assert '외부 검색을 시도했지만' in result.safe_response


def test_verbalizer_routes_llm_response_through_meaning_preserver() -> None:
    conclusion = _conclusion()
    conclusion.metadata['search_context'] = {
        'need_search': True,
        'attempted': True,
        'result_count': 0,
        'missing_terms': ['plate armor', 'mail armor'],
        'missing_aspects': ['construction'],
        'no_evidence_found': True,
    }
    verbalizer = Verbalizer(ollama_verbalizer=StubOllamaVerbalizer('Confident unsupported answer.'))

    result = verbalizer.verbalize(conclusion, model_name='gemma3:4b')

    assert result.used_llm is True
    assert result.llm_error is None
    assert result.preservation_action == 'replace'
    assert 'no_evidence_found' in (result.preservation_violations or [])
    assert '외부 검색을 시도했지만' in result.user_response
