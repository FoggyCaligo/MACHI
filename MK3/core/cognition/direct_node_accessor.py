from __future__ import annotations

from dataclasses import dataclass

from core.cognition.hash_resolver import HashResolver
from core.cognition.meaning_block import MeaningBlock
from core.entities.node import Node
from storage.repositories.node_repository import NodeRepository


@dataclass(slots=True)
class NodeLookupResult:
    address_hash: str
    node: Node | None
    reused_via: str | None = None


class DirectNodeAccessor:
    """Resolve meaning blocks to existing durable nodes only by address hash."""

    def __init__(self, hash_resolver: HashResolver) -> None:
        self.hash_resolver = hash_resolver

    def resolve(self, nodes: NodeRepository, block: MeaningBlock) -> NodeLookupResult:
        address_hash = self.hash_resolver.address_for(block)
        direct = nodes.get_by_address_hash(address_hash)
        if direct is not None:
            return NodeLookupResult(address_hash=address_hash, node=direct, reused_via="address_hash")
        return NodeLookupResult(address_hash=address_hash, node=None, reused_via=None)
