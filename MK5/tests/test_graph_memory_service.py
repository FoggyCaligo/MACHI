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


def test_record_user_utterance_uses_sentence_breaker_segments() -> None:
    repo = GraphRepository(":memory:")
    service = GraphMemoryService(repo)

    service.record_user_utterance(
        user_id="alice",
        text="엄마",
        session_id="s1",
    )
    service.record_user_utterance(
        user_id="alice",
        text="엄마가 아이를 안는다.",
        session_id="s1",
    )

    concept_labels = {
        label
        for node in repo.all_nodes()
        if node.node_type == "concept"
        for label in node.labels
    }
    assert "엄마" in concept_labels
    repo.close()


def test_search_concept_nodes_come_from_recorded_utterance_graph() -> None:
    repo = GraphRepository(":memory:")
    service = GraphMemoryService(repo)

    utterance_id = service.record_user_utterance(
        user_id="alice",
        text="Glock features and market significance",
        session_id="s1",
    )

    search_nodes = service.search_concept_nodes_for_utterance(
        user_id="alice",
        utterance_id=utterance_id,
    )

    assert "glock" in search_nodes
    assert all(node.node_type == "concept" for node in repo.all_nodes() if node.labels and node.labels[0].lower() in search_nodes)
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


def test_repeated_relation_reinforces_one_semantic_edge() -> None:
    repo = GraphRepository(":memory:")
    service = GraphMemoryService(repo)

    service.record_user_utterance(user_id="alice", text="I enjoy TypeScript.", session_id="s1")
    service.record_user_utterance(user_id="alice", text="I enjoy TypeScript.", session_id="s2")

    asserted = [edge for edge in repo.all_edges() if edge.relation == "asserted_fact"]
    assert len(asserted) == 1
    assert asserted[0].support_count >= 2
    repo.close()


def test_memory_summary_ranks_current_query_context() -> None:
    repo = GraphRepository(":memory:")
    service = GraphMemoryService(repo)
    service.record_user_utterance(user_id="alice", text="I enjoy TypeScript.", session_id="s1")
    service.record_user_utterance(user_id="alice", text="I grow tomatoes.", session_id="s1")

    summary = service.user_memory_summary("alice", query="TypeScript project", limit=1)

    assert summary == ["I enjoy TypeScript."]
    repo.close()


def test_fact_correction_preserves_history_and_hides_superseded_fact() -> None:
    repo = GraphRepository(":memory:")
    service = GraphMemoryService(repo)
    service.record_user_utterance(user_id="alice", text="I use JavaScript.", session_id="s1")
    previous = next(node for node in repo.all_nodes() if node.node_type == "fact")

    replacement_id = service.record_fact_correction(
        user_id="alice",
        previous_fact_id=previous.node_id,
        replacement_text="I use TypeScript.",
        session_id="s2",
    )

    old = repo.get_node(previous.node_id)
    replacement = repo.get_node(replacement_id)
    assert old is not None and old.is_active is False
    assert old.payload["superseded_by"] == replacement_id
    assert replacement is not None and replacement.provenance == "user_correction"
    assert "I use JavaScript." not in service.user_memory_summary("alice")
    assert "I use TypeScript." in service.user_memory_summary("alice")
    assert any(edge.relation == "replaces" for edge in repo.all_edges())
    repo.close()


def test_user_scoped_search_does_not_return_other_users_fact() -> None:
    repo = GraphRepository(":memory:")
    service = GraphMemoryService(repo)
    service.record_user_utterance(user_id="alice", text="Alice secret preference.", session_id="s1")

    results = service.graph_search(user_id="bob", query="secret preference", limit=8)

    assert not any(item["node_type"] == "fact" for item in results)
    assert not any(item["node_type"] == "utterance" for item in results)
    repo.close()

