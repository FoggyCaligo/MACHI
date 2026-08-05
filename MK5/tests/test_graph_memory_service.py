from pathlib import Path

from MK5.core.graph.anchors import user_anchor_id
from MK5.core.graph.repository import GraphRepository
from MK5.core.graph.service import GraphMemoryService


def test_user_anchor_is_persistent_key() -> None:
    assert user_anchor_id("alice") == "user_anchor::alice"


def test_record_user_utterance_exposes_memory_summary() -> None:
    repo = GraphRepository(":memory:")
    service = GraphMemoryService(repo)

    service.record_user_utterance(
        user_id="alice",
        text="I build user interfaces. I enjoy TypeScript.",
        session_id="s1",
    )

    summary = service.user_memory_summary("alice")
    assert "I build user interfaces." in summary
    assert "I enjoy TypeScript." in summary
    repo.close()


def test_record_user_utterance_graphizes_tokens_into_concepts() -> None:
    repo = GraphRepository(":memory:")
    service = GraphMemoryService(repo)

    service.record_user_utterance(
        user_id="alice",
        text="Frontend developers build interfaces.",
        session_id="s1",
    )

    concept_results = service.graph_search(user_id="alice", query="frontend", limit=8)
    assert any(item["node_type"] == "concept" for item in concept_results)

    relations = {(edge.source_id, edge.target_id, edge.relation) for edge in repo.all_edges()}
    assert any(relation == "user_mentions_concept" for _, _, relation in relations)
    assert any(relation == "user_adjacent_concept" for _, _, relation in relations)
    repo.close()


def test_graph_search_expands_neighbors() -> None:
    repo = GraphRepository(":memory:")
    service = GraphMemoryService(repo)

    service.record_user_utterance(
        user_id="alice",
        text="Frontend developers build interfaces.",
        session_id="s1",
    )

    results = service.graph_search(user_id="alice", query="build", limit=8)
    assert results
    assert any(item.get("neighbors") for item in results)
    assert any(
        neighbor.get("relation") in {"user_mentions_concept", "user_adjacent_concept", "user_references_concept"}
        for item in results
        for neighbor in item.get("neighbors", [])
    )
    repo.close()


def test_graph_repository_persists_across_reopen(tmp_path: Path) -> None:
    db_path = tmp_path / "MK5-memory.db"
    repo_a = GraphRepository(db_path)
    service_a = GraphMemoryService(repo_a)
    service_a.record_user_utterance(user_id="alice", text="persist me", session_id="s1")
    repo_a.close()

    repo_b = GraphRepository(db_path)
    service_b = GraphMemoryService(repo_b)
    summary = service_b.user_memory_summary("alice")

    assert "persist me" in summary
    repo_b.close()


def test_search_results_are_persisted_under_search_anchor() -> None:
    repo = GraphRepository(":memory:")
    service = GraphMemoryService(repo)

    recorded = service.record_search_results(
        query="graph memory",
        results=[
            {
                "title": "Graph Memory",
                "url": "https://example.com/graph-memory",
                "snippet": "Graph memory stores durable context for agents.",
                "source": "stub",
            }
        ],
    )

    assert recorded
    search_results = service.graph_search(user_id="alice", query="Graph Memory", limit=8)
    assert any(item["node_type"] == "search_result" for item in search_results)
    durable_results = service.graph_search(user_id="alice", query="durable", limit=8)
    assert any(item["node_type"] == "search_fact" for item in durable_results)
    concept_results = service.graph_search(user_id="alice", query="agents", limit=8)
    assert any(item["node_type"] == "concept" for item in concept_results)
    repo.close()

