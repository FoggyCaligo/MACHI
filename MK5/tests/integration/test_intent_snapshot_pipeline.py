from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.chat_pipeline import ChatPipeline, ChatPipelineRequest
from core.entities.conclusion import CoreConclusion, DerivedActionLayer
from core.verbalization.verbalizer import VerbalizationResult, Verbalizer
from storage.sqlite.unit_of_work import SqliteUnitOfWork


class FakeVerbalizer(Verbalizer):
    def verbalize(self, conclusion: CoreConclusion, *, model_name: str = 'mk5-graph-core') -> VerbalizationResult:
        return VerbalizationResult(
            user_response=f'FAKE({conclusion.inferred_intent})',
            internal_explanation='INTERNAL',
            derived_action=DerivedActionLayer(
                response_mode='test',
                answer_goal='test goal',
                suggested_actions=['test action'],
                do_not_claim=['test claim'],
            ),
            used_llm=False,
            llm_error=None,
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

        response1 = pipeline.process(
            ChatPipelineRequest(
                session_id='session-intent',
                message='고양이 -> 동물',
                turn_index=1,
            )
        )
        snapshot1 = response1['thinking']['metadata']['intent_snapshot']
        assert snapshot1['snapshot_intent']

        with SqliteUnitOfWork(db_path, schema_path=schema_path, initialize_schema=True) as uow:
            messages = list(uow.chat_messages.list_by_session('session-intent', limit=10))
            assistant_rows = [row for row in messages if row.role == 'assistant']
            assert assistant_rows
            assert assistant_rows[-1].metadata.get('intent_snapshot', {}).get('snapshot_intent') == snapshot1['snapshot_intent']

        response2 = pipeline.process(
            ChatPipelineRequest(
                session_id='session-intent',
                message='동물 -> 포유류',
                turn_index=2,
            )
        )
        snapshot2 = response2['thinking']['metadata']['intent_snapshot']
        assert snapshot2['previous_snapshot_intent'] == snapshot1['snapshot_intent']
        assert response2['assistant_ingest']['message_id'] > 0

        with SqliteUnitOfWork(db_path, schema_path=schema_path, initialize_schema=True) as uow:
            messages = list(uow.chat_messages.list_by_session('session-intent', limit=20))
            assistant_rows = [row for row in messages if row.role == 'assistant']
            assert len(assistant_rows) >= 2
            assert assistant_rows[-1].metadata.get('intent_snapshot', {}).get('previous_snapshot_intent') == snapshot1['snapshot_intent']

        print('PASS: intent snapshot pipeline')


if __name__ == '__main__':
    main()
