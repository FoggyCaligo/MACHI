from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.chat_pipeline import ChatPipeline, ChatPipelineRequest


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
        assert response['used_model'] == 'mk5-graph-core'
        assert response['ingest']['message_id'] > 0
        assert response['thinking']['core_conclusion']['activated_concepts']
        assert response['activation']['seed_blocks']
        assert '해석된 의도' in response['reply']
        assert '활성 개념 노드 수' in response['reply']

        print('PASS: end-to-end chat pipeline')


if __name__ == '__main__':
    main()
