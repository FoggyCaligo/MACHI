"""Storage(WorldGraph) 단위 테스트 — in-memory SQLite 사용."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from MK6.core.storage.db import open_db
from MK6.core.storage.world_graph import (
    insert_node, get_node, update_node, deactivate_node, get_active_nodes,
    insert_edge, get_edge, get_edges_for_node,
    insert_word, get_word, get_words_for_node, remap_words_to_node,
)
from MK6.core.entities.node import Node
from MK6.core.entities.edge import Edge
from MK6.core.entities.word_entry import WordEntry


def _make_node(address_hash: str | None = None, labels: list[str] | None = None) -> Node:
    now = datetime.now(timezone.utc)
    return Node(
        address_hash=address_hash or uuid.uuid4().hex[:32],
        node_kind="concept",
        formation_source="ingest",
        labels=labels or ["테스트"],
        trust_score=0.5,
        stability_score=0.5,
        is_active=True,
        created_at=now,
        updated_at=now,
    )


def _make_edge(src: str, tgt: str) -> Edge:
    now = datetime.now(timezone.utc)
    return Edge(
        edge_id=str(uuid.uuid4()),
        source_hash=src,
        target_hash=tgt,
        edge_family="concept",
        connect_type="neutral",
        provenance_source="lang_to_graph",
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
def conn():
    c = open_db(":memory:")
    yield c
    c.close()


# ── 노드 ──────────────────────────────────────────────────────────────────────

def test_insert_and_get_node(conn):
    node = _make_node()
    insert_node(conn, node)
    conn.commit()

    fetched = get_node(conn, node.address_hash)
    assert fetched is not None
    assert fetched.address_hash == node.address_hash
    assert fetched.labels == node.labels


def test_get_node_not_found(conn):
    assert get_node(conn, "doesnotexist") is None


def test_update_node(conn):
    node = _make_node()
    insert_node(conn, node)
    conn.commit()

    node.trust_score = 0.9
    node.labels = ["수정됨"]
    update_node(conn, node)
    conn.commit()

    fetched = get_node(conn, node.address_hash)
    assert fetched.trust_score == pytest.approx(0.9)
    assert fetched.labels == ["수정됨"]


def test_deactivate_node(conn):
    node = _make_node()
    insert_node(conn, node)
    conn.commit()

    deactivate_node(conn, node.address_hash)
    conn.commit()

    fetched = get_node(conn, node.address_hash)
    assert fetched.is_active is False


def test_get_active_nodes(conn):
    n1 = _make_node()
    n2 = _make_node()
    insert_node(conn, n1)
    insert_node(conn, n2)
    deactivate_node(conn, n2.address_hash)
    conn.commit()

    active = get_active_nodes(conn)
    hashes = [n.address_hash for n in active]
    assert n1.address_hash in hashes
    assert n2.address_hash not in hashes


def test_node_embedding_roundtrip(conn):
    node = _make_node()
    node.embedding = [0.1, 0.2, 0.3]
    insert_node(conn, node)
    conn.commit()

    fetched = get_node(conn, node.address_hash)
    assert fetched.embedding is not None
    assert len(fetched.embedding) == 3
    assert fetched.embedding[0] == pytest.approx(0.1, abs=1e-5)


# ── 엣지 ──────────────────────────────────────────────────────────────────────

def test_insert_and_get_edge(conn):
    src = _make_node()
    tgt = _make_node()
    insert_node(conn, src)
    insert_node(conn, tgt)
    edge = _make_edge(src.address_hash, tgt.address_hash)
    insert_edge(conn, edge)
    conn.commit()

    fetched = get_edge(conn, edge.edge_id)
    assert fetched is not None
    assert fetched.source_hash == src.address_hash


def test_get_edges_for_node(conn):
    src = _make_node()
    tgt = _make_node()
    insert_node(conn, src)
    insert_node(conn, tgt)
    edge = _make_edge(src.address_hash, tgt.address_hash)
    insert_edge(conn, edge)
    conn.commit()

    edges = get_edges_for_node(conn, src.address_hash)
    assert len(edges) == 1
    assert edges[0].edge_id == edge.edge_id

    # 도착 노드 기준으로도 조회됨
    edges_tgt = get_edges_for_node(conn, tgt.address_hash)
    assert len(edges_tgt) == 1


# ── 단어 ──────────────────────────────────────────────────────────────────────

def test_insert_and_get_word(conn):
    node = _make_node()
    insert_node(conn, node)
    now = datetime.now(timezone.utc)
    word = WordEntry(
        word_id=str(uuid.uuid4()),
        surface_form="사과",
        address_hash=node.address_hash,
        language="ko",
        created_at=now,
    )
    insert_word(conn, word)
    conn.commit()

    fetched = get_word(conn, "사과")
    assert fetched is not None
    assert fetched.address_hash == node.address_hash


def test_get_words_for_node(conn):
    node = _make_node()
    insert_node(conn, node)
    now = datetime.now(timezone.utc)
    for surface in ["사과", "apple", "apfel"]:
        insert_word(conn, WordEntry(
            word_id=str(uuid.uuid4()),
            surface_form=surface,
            address_hash=node.address_hash,
            language=None,
            created_at=now,
        ))
    conn.commit()

    words = get_words_for_node(conn, node.address_hash)
    surfaces = {w.surface_form for w in words}
    assert surfaces == {"사과", "apple", "apfel"}


def test_remap_words_to_node(conn):
    n_a = _make_node()
    n_b = _make_node()
    n_merged = _make_node()
    for n in [n_a, n_b, n_merged]:
        insert_node(conn, n)
    now = datetime.now(timezone.utc)
    insert_word(conn, WordEntry(str(uuid.uuid4()), "사과", n_a.address_hash, "ko", now))
    insert_word(conn, WordEntry(str(uuid.uuid4()), "apple", n_b.address_hash, "en", now))
    conn.commit()

    remap_words_to_node(conn, [n_a.address_hash, n_b.address_hash], n_merged.address_hash)
    conn.commit()

    assert get_word(conn, "사과").address_hash == n_merged.address_hash
    assert get_word(conn, "apple").address_hash == n_merged.address_hash
