from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.chat_pipeline import ChatPipeline, ChatPipelineRequest
from core.entities.conclusion import CoreConclusion, DerivedActionLayer
from core.search.search_need_evaluator import SearchNeedDecision
from core.search.search_query_planner import SearchPlan
from core.search.search_sidecar import SearchEvidence, SearchRunResult, SearchSidecar
from core.verbalization.verbalizer import VerbalizationResult, Verbalizer


class FakeVerbalizer(Verbalizer):
    def verbalize(self, conclusion: CoreConclusion, *, model_name: str = 'mk5-graph-core') -> VerbalizationResult:
        return VerbalizationResult(
            user_response=f'FAKE({model_name})',
            internal_explanation='INTERNAL',
            derived_action=DerivedActionLayer(
                response_mode='test',
                answer_goal='test goal',
                suggested_actions=['test action'],
                do_not_claim=['test claim'],
            ),
            used_llm=(model_name != 'mk5-graph-core'),
            llm_error=None,
        )


class FakeSearchSidecar(SearchSidecar):
    def run(self, *, message: str, meaning_blocks, resolved_nodes, current_root_event_id: int | None, model_name: str) -> SearchRunResult:
        decision = SearchNeedDecision(
            need_search=('하데스' in message),
            reason='test',
            gap_summary='test gap',
            target_terms=['하데스'],
        )
        if '하데스' not in message:
            return SearchRunResult(attempted=False, decision=decision)
        return SearchRunResult(
            attempted=True,
            decision=decision,
            plan=SearchPlan(queries=['하데스'], reason='test plan', focus_terms=['하데스']),
            results=[
                SearchEvidence(
                    title='하데스',
                    snippet='고대 그리스 신화에서 저승 세계를 가리키는 이름으로도 쓰인다.',
                    passages=['고대 그리스 신화에서 저승 세계를 가리키는 이름으로도 쓰인다.'],
                    url='https://example.test/hades',
                    provider='fake-search',
                    trust_hint='high',
                    source_provenance='trusted_search:fake',
                )
            ],
            provider_errors=[],
            error=None,
        )


def main() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / 'memory.db'
        schema_path = ROOT / 'storage' / 'schema.sql'
        pipeline = ChatPipeline(
            db_path=db_path,
            schema_path=schema_path,
            verbalizer=FakeVerbalizer(),
        )

        response = pipeline.process(
            ChatPipelineRequest(
                session_id='session-e2e',
                message='MK5에서는 project와 profile을 분리하지 말고 chat 흐름으로 통합하자.',
                turn_index=1,
            )
        )

        assert isinstance(response['reply'], str) and response['reply']
        assert isinstance(response['internal_explanation'], str) and response['internal_explanation']
        assert response['used_model'] == 'mk5-graph-core'
        assert response['ingest']['message_id'] > 0
        assert response['thinking']['core_conclusion']['activated_concepts']
        assert 'debug' in response and 'activation' in response['debug']
        assert response['thinking']['derived_action']['answer_goal']
        assert response['verbalization']['used_llm'] is False
        assert response['assistant_ingest']['enabled'] is False

        pipeline_with_fake_llm = ChatPipeline(
            db_path=db_path,
            schema_path=schema_path,
            verbalizer=FakeVerbalizer(),
            search_sidecar=FakeSearchSidecar(),
        )
        response_with_model = pipeline_with_fake_llm.process(
            ChatPipelineRequest(
                session_id='session-e2e-2',
                message='하데스를 장소의 의미로 설명해줄래?',
                turn_index=1,
                model_name='gemma4:e2b',
            )
        )
        assert response_with_model['reply'] == 'FAKE(gemma4:e2b)'
        assert response_with_model['used_model'] == 'gemma4:e2b'
        assert response_with_model['verbalization']['used_llm'] is True
        assert response_with_model['search']['query_triggered'] is True
        assert response_with_model['search']['results']
        assert response_with_model['assistant_ingest']['enabled'] is False

        print('PASS: end-to-end chat pipeline')


if __name__ == '__main__':
    main()
