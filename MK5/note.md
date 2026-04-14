## 실행 : Windows 기준
MK5에서: 
py -m venv .venv
.venv\Scripts\activate
pip install flask
python run.py

http://127.0.0.1:5000 접속

## 테스트 명령어
python tests/unit/test_sqlite_repository_smoke.py
python tests/integration/test_chat_graph_pipeline.py
python tests/integration/test_activation_engine_pipeline.py
python tests/integration/test_thinking_revision_pipeline.py
python tests/integration/test_end_to_end_chat_pipeline.py