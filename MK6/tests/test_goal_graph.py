"""GlobalGoalGraph bootstrap 테스트."""
from __future__ import annotations

from MK6.core.goal import (
    GLOBAL_GOAL_AXIS_SEEDS,
    GOAL_ROOT_HASH,
    initialize_global_goal_graph,
    load_goal_view,
)
from MK6.core.storage.db import open_db
from MK6.core.storage.world_graph import get_edge_by_endpoints, get_node


def _counts(conn) -> tuple[int, int]:
    node_count = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
    edge_count = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
    return node_count, edge_count


def test_initialize_global_goal_graph_creates_root_axes_and_edges():
    conn = open_db(":memory:")
    try:
        goal_view = initialize_global_goal_graph(conn)

        assert goal_view.root_hash == GOAL_ROOT_HASH
        assert goal_view.root_node.node_kind == "goal"
        assert goal_view.root_node.formation_source == "system_policy"
        assert len(goal_view.axis_refs) == len(GLOBAL_GOAL_AXIS_SEEDS)

        root = get_node(conn, GOAL_ROOT_HASH)
        assert root is not None
        assert root.is_active is True

        for seed in GLOBAL_GOAL_AXIS_SEEDS:
            axis_node = get_node(conn, seed.node_hash)
            assert axis_node is not None
            assert axis_node.node_kind == "concept"
            assert axis_node.formation_source == "system_policy"
            assert axis_node.payload["goal_axis"] == seed.label_key
            assert axis_node.payload["priority_rank"] == seed.priority_rank

            edge = get_edge_by_endpoints(conn, GOAL_ROOT_HASH, seed.node_hash)
            assert edge is not None
            assert edge.edge_family == "relation"
            assert edge.connect_type == "flow"
            assert edge.provenance_source == "system_policy"
            assert edge.edge_weight == seed.edge_weight
            assert edge.payload["goal_axis"] == seed.label_key
    finally:
        conn.close()


def test_initialize_global_goal_graph_is_idempotent():
    conn = open_db(":memory:")
    try:
        first = initialize_global_goal_graph(conn)
        counts_after_first = _counts(conn)

        second = initialize_global_goal_graph(conn)
        counts_after_second = _counts(conn)

        assert counts_after_first == counts_after_second
        assert first.root_hash == second.root_hash
        assert first.global_goal_hashes == second.global_goal_hashes
    finally:
        conn.close()


def test_load_goal_view_reads_existing_bootstrap_graph():
    conn = open_db(":memory:")
    try:
        initialized = initialize_global_goal_graph(conn)
        loaded = load_goal_view(conn)

        assert loaded is not None
        assert loaded.root_hash == initialized.root_hash
        assert loaded.global_goal_hashes == initialized.global_goal_hashes
        assert loaded.axis_hash_by_key("honesty") is not None
        assert loaded.axis_hash_by_key("missing") is None
    finally:
        conn.close()
