## 실행 : Windows 기준
MK3에서: 
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


## 테스트 메시지
안녕? 난 신재용 이야. 성은 신, 이름은 재용.

난 예전에 하던 개인프로젝트를 최근에 다시 시작했는데, sllm에 그래프 구조의 장기 기억과, 그 그래프 위에서 사고과정을 진행하는 기능을 붙이는 개인 프로젝트인 Machi-MK3가 그 프로젝트야.

이 프로젝트는 세계를 그래프로 인지하고, 사용자의 입력을 의미 단위로 분해해서 Node를 만든 후, 각 노드들을 적절한 관계Edge로 연결하고, 각 노드들의 연결인 edge를 수정하는 방식으로 "AI가 현재 인지하는 세계"를 꾸준히 업데이트 한다는 개념을 구현한 거야. 그렇게 되면 단순히 기억을 쌓기만 하는 게 아니라,현재의 모습대로 기억할 수 있게 되지. 또 블랙박스로 가려진 llm과 달리, 그 그래프 자체를 데이터로서 직접 열어서 볼 수도 있고.
