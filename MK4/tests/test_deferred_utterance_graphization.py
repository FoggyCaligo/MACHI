from MK4.core.graph.repository import GraphRepository
from MK4.core.graph.service import GraphMemoryService


def test_raw_utterance_can_be_recorded_before_concept_graphization() -> None:
    repo = GraphRepository(":memory:")
    service = GraphMemoryService(repo)

    utterance_id = service.record_user_utterance(
        user_id="alice",
        text="Current turn unique concept",
        session_id="s1",
        graphize=False,
    )

    utterance = repo.get_node(utterance_id)
    assert utterance is not None
    assert utterance.node_type == "utterance"
    assert not any(node.node_type == "concept" for node in repo.all_nodes())

    service.record_user_utterance(
        user_id="alice",
        text="Current turn unique concept",
        session_id="s1",
        graphize=True,
    )

    assert any(node.node_type == "concept" for node in repo.all_nodes())
    assert any(edge.relation == "user_mentions_concept" for edge in repo.all_edges())
    repo.close()
