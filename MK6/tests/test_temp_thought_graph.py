"""TempThoughtGraph 단위 테스트."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from MK6.core.entities.node import Node
from MK6.core.entities.edge import Edge
from MK6.core.entities.translated_graph import (
    TranslatedGraph, ConceptPointer, EmptySlot, LocalSubgraph,
)
from MK6.core.thinking.temp_thought_graph import TempThoughtGraph


def _node(address_hash: str | None = None) -> Node:
    now = datetime.now(timezone.utc)
    return Node(
        address_hash=address_hash or uuid.uuid4().hex[:32],
        node_kind="concept",
        formation_source="ingest",
        labels=["테스트"],
        trust_score=0.5,
        stability_score=0.5,
        is_active=True,
        created_at=now,
        updated_at=now,
    )


def _edge(src: str, tgt: str) -> Edge:
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


def test_add_and_get_node():
    tg = TempThoughtGraph()
    n = _node()
    tg.add_node(n)
    assert tg.get_node(n.address_hash) is n


def test_add_edge_and_get_edges_for_node():
    tg = TempThoughtGraph()
    a, b = _node(), _node()
    tg.add_node(a)
    tg.add_node(b)
    e = _edge(a.address_hash, b.address_hash)
    tg.add_edge(e)

    edges = tg.get_edges_for_node(a.address_hash)
    assert len(edges) == 1
    assert edges[0].edge_id == e.edge_id


def test_remove_edge():
    tg = TempThoughtGraph()
    a, b = _node(), _node()
    tg.add_node(a)
    tg.add_node(b)
    e = _edge(a.address_hash, b.address_hash)
    tg.add_edge(e)
    tg.remove_edge(e.edge_id)

    assert tg.get_edges_for_node(a.address_hash) == []


def test_delta_tracking():
    tg = TempThoughtGraph()
    n = _node()
    tg.add_node(n)

    delta = tg.current_delta()
    assert n.address_hash in delta.added_nodes
    assert not delta.is_empty()


def test_reset_delta():
    tg = TempThoughtGraph()
    tg.add_node(_node())
    tg.reset_delta()
    assert tg.current_delta().is_empty()


def test_empty_slot_tracking():
    tg = TempThoughtGraph()
    slot = EmptySlot(concept_hint="양자역학")
    tg._empty_slots.append(slot)
    assert tg.has_empty_slots()

    n = _node()
    tg.fill_slot(slot, n)
    assert not tg.has_empty_slots()
    assert tg.get_node(n.address_hash) is not None


def test_load_from_translated():
    a = _node()
    b = _node()
    e = _edge(a.address_hash, b.address_hash)

    subgraph = LocalSubgraph(
        center_hash=a.address_hash,
        nodes=[a, b],
        edges=[e],
    )
    pointer = ConceptPointer(address_hash=a.address_hash, local_subgraph=subgraph)
    slot = EmptySlot(concept_hint="모름")

    tg_entity = TranslatedGraph(
        nodes=[pointer, slot],
        edges=[],
        source="테스트 문장",
    )

    tg = TempThoughtGraph()
    tg.load_from_translated(tg_entity)

    assert tg.get_node(a.address_hash) is not None
    assert tg.get_node(b.address_hash) is not None
    assert tg.has_empty_slots()


def test_connect_to_goal():
    tg = TempThoughtGraph()
    goal = _node()
    concept = _node()
    tg.set_goal_node(goal)
    tg.add_node(concept)
    tg.connect_to_goal(concept.address_hash)

    edges = tg.get_edges_for_node(goal.address_hash)
    assert len(edges) == 1
    assert edges[0].is_temporary is True


def test_neighbor_hashes():
    tg = TempThoughtGraph()
    a, b, c = _node(), _node(), _node()
    for n in [a, b, c]:
        tg.add_node(n)
    tg.add_edge(_edge(a.address_hash, b.address_hash))
    tg.add_edge(_edge(a.address_hash, c.address_hash))

    neighbors = tg.neighbor_hashes(a.address_hash)
    assert neighbors == {b.address_hash, c.address_hash}
