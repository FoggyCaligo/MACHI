from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.chat_pipeline import ChatPipeline, ChatPipelineRequest
from core.entities.conclusion import CoreConclusion, DerivedActionLayer
from core.search.search_sidecar import SearchEvidence, SearchSidecar
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
    def search(self, message: str, conclusion: CoreConclusion) -> list[SearchEvidence]:
        if '하데스' not in message:
            return []
        return [
            SearchEvidence(
                title='하데스',
                snippet='고대 그리스 신화에서 저승 세계를 가리키는 이름으로도 쓰인다.',
                url='https://example.test/hades',
                provider='fake-search',
            )
        ]


def main() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / 'memory.db'
        schema_path = ROOT / 'storage' / 'schema.sql'
        pipeline = ChatPipeline(db_path=db_path, schema_path=schema_path)

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
        assert '해석된 의도' not in response['reply']
        assert '지금' in response['reply']
        assert '해석된 의도' in response['internal_explanation']
        assert 'debug' in response and 'activation' in response['debug']
        assert response['thinking']['derived_action']['answer_goal']
        assert response['verbalization']['used_llm'] is False
        assert response['assistant_ingest']['message_id'] > 0

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
        assert response_with_model['assistant_ingest']['message_id'] > 0

        print('PASS: end-to-end chat pipeline')


if __name__ == '__main__':
    main()
