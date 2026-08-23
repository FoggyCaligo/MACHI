from __future__ import annotations

from MK4.core.graph.repository import GraphRepository
from MK4.core.graph.service import GraphMemoryService
from MK4.tools.graph_tools import GraphToolSuite


def test_recall_memory_description_excludes_refreshing_current_external_facts() -> None:
    repo = GraphRepository(":memory:")
    try:
        service = GraphMemoryService(repo)
        definition = next(
            item
            for item in GraphToolSuite(service).build_registry().definitions()
            if item.name == "graph_search"
        )

        description = definition.description.lower()
        assert "past conversation or personal context" in description
        assert "do not use persistent memory to refresh public or external facts" in description
        assert "current external facts require" in description
    finally:
        repo.close()


def test_automatic_memory_note_has_same_external_fact_boundary() -> None:
    repo = GraphRepository(":memory:")
    try:
        service = GraphMemoryService(repo)
        summary = GraphToolSuite(service).get_user_memory_summary(user_id="alice")

        note = summary[-1]["label"].lower()
        assert "requested source of truth" in note
        assert "persistent memory is not a way to refresh public or external facts" in note
        assert "current external facts must be checked" in note
    finally:
        repo.close()
