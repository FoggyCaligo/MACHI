from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from storage.unit_of_work import UnitOfWork


@dataclass(slots=True)
class PointerRewriteResult:
    rewired_pointer_ids: list[int] = field(default_factory=list)
    merged_pointer_ids: list[int] = field(default_factory=list)
    deactivated_pointer_ids: list[int] = field(default_factory=list)


@dataclass(slots=True)
class PointerRewriteService:
    """Mechanically rewrite pointers after a node merge decision.

    Important: this service does not decide *whether* two nodes should merge.
    It only preserves graph consistency once a merge decision has already been
    made elsewhere.
    """

    def rewrite_for_node_merge(
        self,
        *,
        uow: UnitOfWork,
        merged_node_id: int,
        canonical_node_id: int,
    ) -> PointerRewriteResult:
        result = PointerRewriteResult()
        processed: set[int] = set()

        for pointer in list(uow.node_pointers.list_by_owner(merged_node_id, active_only=True)):
            if pointer.id is None or pointer.id in processed:
                continue
            processed.add(pointer.id)
            new_owner = canonical_node_id
            new_referenced = pointer.referenced_node_id
            if new_referenced == canonical_node_id:
                uow.node_pointers.deactivate(pointer.id)
                result.deactivated_pointer_ids.append(pointer.id)
                continue
            duplicate = uow.node_pointers.find_active(
                new_owner,
                new_referenced,
                pointer.pointer_type,
                pointer_slot=pointer.pointer_slot,
            )
            if duplicate is not None and duplicate.id != pointer.id:
                detail = self._merge_pointer_detail(duplicate.detail, pointer.detail, merged_pointer_id=pointer.id)
                uow.node_pointers.update_detail(duplicate.id or 0, detail)
                uow.node_pointers.deactivate(pointer.id)
                result.merged_pointer_ids.append(pointer.id)
                continue
            detail = self._annotate_rewrite(pointer.detail, merged_node_id=merged_node_id, canonical_node_id=canonical_node_id)
            uow.node_pointers.update_owner(pointer.id, new_owner)
            uow.node_pointers.update_detail(pointer.id, detail)
            result.rewired_pointer_ids.append(pointer.id)

        for pointer in list(uow.node_pointers.list_referencing(merged_node_id, active_only=True)):
            if pointer.id is None or pointer.id in processed:
                continue
            processed.add(pointer.id)
            new_owner = pointer.owner_node_id
            new_referenced = canonical_node_id
            if new_owner == canonical_node_id:
                uow.node_pointers.deactivate(pointer.id)
                result.deactivated_pointer_ids.append(pointer.id)
                continue
            duplicate = uow.node_pointers.find_active(
                new_owner,
                new_referenced,
                pointer.pointer_type,
                pointer_slot=pointer.pointer_slot,
            )
            if duplicate is not None and duplicate.id != pointer.id:
                detail = self._merge_pointer_detail(duplicate.detail, pointer.detail, merged_pointer_id=pointer.id)
                uow.node_pointers.update_detail(duplicate.id or 0, detail)
                uow.node_pointers.deactivate(pointer.id)
                result.merged_pointer_ids.append(pointer.id)
                continue
            detail = self._annotate_rewrite(pointer.detail, merged_node_id=merged_node_id, canonical_node_id=canonical_node_id)
            uow.node_pointers.update_referenced(pointer.id, new_referenced)
            uow.node_pointers.update_detail(pointer.id, detail)
            result.rewired_pointer_ids.append(pointer.id)

        return result

    def _annotate_rewrite(
        self,
        detail: dict[str, Any],
        *,
        merged_node_id: int,
        canonical_node_id: int,
    ) -> dict[str, Any]:
        merged = dict(detail or {})
        history = list(merged.get('rewrite_history') or [])
        history.append({'from_node_id': merged_node_id, 'to_node_id': canonical_node_id})
        merged['rewrite_history'] = history
        return merged

    def _merge_pointer_detail(
        self,
        existing_detail: dict[str, Any],
        absorbed_detail: dict[str, Any],
        *,
        merged_pointer_id: int,
    ) -> dict[str, Any]:
        merged = dict(existing_detail or {})
        sources = list(merged.get('merged_pointer_ids') or [])
        if merged_pointer_id not in sources:
            sources.append(merged_pointer_id)
        merged['merged_pointer_ids'] = sources

        for key, value in (absorbed_detail or {}).items():
            if key not in merged:
                merged[key] = value
                continue
            if merged[key] == value:
                continue
            collisions = dict(merged.get('merged_values') or {})
            existing_values = list(collisions.get(key) or [])
            for candidate in (merged[key], value):
                if candidate not in existing_values:
                    existing_values.append(candidate)
            collisions[key] = existing_values
            merged['merged_values'] = collisions
        return merged
