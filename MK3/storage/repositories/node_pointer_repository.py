from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from core.entities.node_pointer import NodePointer
from storage.repositories.base import Repository


class NodePointerRepository(Repository, ABC):
    @abstractmethod
    def add(self, pointer: NodePointer) -> NodePointer:
        """Persist one pointer/reference relation and return the stored row."""

    @abstractmethod
    def get_by_id(self, pointer_id: int) -> NodePointer | None:
        """Fetch one pointer row by primary key."""

    @abstractmethod
    def find_active(
        self,
        owner_node_id: int,
        referenced_node_id: int,
        pointer_type: str,
        *,
        pointer_slot: str | None = None,
    ) -> NodePointer | None:
        """Return an already active pointer when deduping reuse relations."""

    @abstractmethod
    def list_by_owner(self, owner_node_id: int, *, active_only: bool = True) -> Sequence[NodePointer]:
        """Return pointers stored by one owner node."""

    @abstractmethod
    def list_referencing(self, referenced_node_id: int, *, active_only: bool = True) -> Sequence[NodePointer]:
        """Return all owners that currently point at the given node."""

    @abstractmethod
    def update_owner(self, pointer_id: int, owner_node_id: int) -> None:
        """Rewrite the owner side of one pointer row."""

    @abstractmethod
    def update_referenced(self, pointer_id: int, referenced_node_id: int) -> None:
        """Rewrite the referenced side of one pointer row."""

    @abstractmethod
    def update_detail(self, pointer_id: int, detail: dict) -> None:
        """Replace pointer detail JSON after consolidation."""

    @abstractmethod
    def deactivate(self, pointer_id: int) -> None:
        """Deactivate one pointer without erasing the history row."""
