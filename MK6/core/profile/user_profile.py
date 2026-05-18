from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from ..entities.edge import Edge
from ..entities.node import Node
from ..storage.world_graph import (
    get_edge_by_endpoints,
    get_node,
    insert_edge,
    insert_node,
    update_edge,
    update_node,
)
from ..utils.hash_resolver import ANCHOR_USER


USER_PROFILE_EDGE_TYPE = "profile_reference"
USER_PROFILE_HASH_PREFIX = "user-profile::"


@dataclass(frozen=True, slots=True)
class UserProfileView:
    """현재 사용자 프로필 조회 결과.

    UserProfile은 사용자에 대한 사실 저장소가 아니다. 이 사용자의 대화에서 등장한
    WorldGraph concept들을 참조하는 개인화된 context index다.
    """

    profile_node: Node

    @property
    def profile_hash(self) -> str:
        return self.profile_node.address_hash


def ensure_user_profile(conn, *, user_anchor_hash: str = ANCHOR_USER) -> UserProfileView:
    """현재 사용자 앵커에 대응하는 UserProfile 노드를 보장한다."""
    now = datetime.now(timezone.utc)
    profile_hash = _profile_hash(user_anchor_hash)
    profile = get_node(conn, profile_hash)
    if profile is None:
        profile = Node(
            address_hash=profile_hash,
            node_kind="concept",
            formation_source="system_policy",
            labels=["UserProfile", "사용자 프로필"],
            is_abstract=False,
            trust_score=1.0,
            stability_score=1.0,
            is_active=True,
            payload={
                "profile_for": user_anchor_hash,
                "profile_role": "conversation_context_index",
                "note": "사용자에 대한 사실 저장소가 아니라, 이 사용자 대화에서 등장한 concept node에 대한 참조 허브다.",
            },
            created_at=now,
            updated_at=now,
        )
        insert_node(conn, profile)
    elif not profile.is_active:
        profile.is_active = True
        profile.touch()
        update_node(conn, profile)

    _ensure_user_to_profile_edge(conn, user_anchor_hash, profile_hash, now)
    conn.commit()
    return UserProfileView(profile_node=profile)


def attach_profile_references(
    conn,
    concept_hashes: set[str],
    *,
    user_anchor_hash: str = ANCHOR_USER,
    edge_weight: float = 0.25,
) -> UserProfileView:
    """현재 사용자 프로필에 concept 참조 edge를 추가/강화한다.

    이 edge는 claim/fact가 아니다. 단지 이 사용자와의 대화에서 해당 concept이
    등장했다는 개인화된 접근 인덱스다.
    """
    profile_view = ensure_user_profile(conn, user_anchor_hash=user_anchor_hash)
    profile_hash = profile_view.profile_hash
    now = datetime.now(timezone.utc)

    for concept_hash in sorted(concept_hashes):
        if concept_hash == profile_hash or concept_hash == user_anchor_hash:
            continue
        node = get_node(conn, concept_hash)
        if node is None or not node.is_active:
            continue

        existing = get_edge_by_endpoints(conn, profile_hash, concept_hash)
        if existing is None:
            edge = Edge(
                edge_id=str(uuid.uuid4()),
                source_hash=profile_hash,
                target_hash=concept_hash,
                edge_family="relation",
                connect_type="neutral",
                provenance_source="user_policy",
                proposed_connect_type=USER_PROFILE_EDGE_TYPE,
                proposal_reason="현재 사용자 대화에서 등장한 concept을 UserProfile 참조 인덱스에 연결",
                support_count=1,
                trust_score=0.8,
                edge_weight=edge_weight,
                is_active=True,
                is_temporary=False,
                payload={
                    "profile_reference": True,
                    "profile_for": user_anchor_hash,
                    "reference_role": USER_PROFILE_EDGE_TYPE,
                    "last_seen_at": now.isoformat(),
                },
                created_at=now,
                updated_at=now,
            )
            insert_edge(conn, edge)
            continue

        if is_profile_reference_edge(existing):
            existing.support_count += 1
            existing.edge_weight = min(1.0, max(existing.edge_weight, edge_weight) + 0.05)
            existing.payload["last_seen_at"] = now.isoformat()
            existing.touch()
            update_edge(conn, existing)

    conn.commit()
    return profile_view


def is_user_profile_hash(address_hash: str) -> bool:
    return address_hash.startswith(_stable_hash_prefix(USER_PROFILE_HASH_PREFIX))


def is_profile_reference_edge(edge: Edge) -> bool:
    return bool(edge.payload.get("profile_reference")) or edge.proposed_connect_type == USER_PROFILE_EDGE_TYPE


def _ensure_user_to_profile_edge(conn, user_hash: str, profile_hash: str, now: datetime) -> None:
    existing = get_edge_by_endpoints(conn, user_hash, profile_hash)
    if existing is not None:
        if existing.payload.get("profile_edge"):
            existing.support_count += 1
            existing.payload["last_seen_at"] = now.isoformat()
            existing.touch()
            update_edge(conn, existing)
        return

    edge = Edge(
        edge_id=str(uuid.uuid4()),
        source_hash=user_hash,
        target_hash=profile_hash,
        edge_family="relation",
        connect_type="flow",
        provenance_source="system_policy",
        proposed_connect_type="current_profile",
        proposal_reason="현재 사용자 앵커와 UserProfile 참조 허브 연결",
        support_count=1,
        trust_score=1.0,
        edge_weight=1.0,
        is_active=True,
        is_temporary=False,
        payload={
            "profile_edge": True,
            "profile_for": user_hash,
            "last_seen_at": now.isoformat(),
        },
        created_at=now,
        updated_at=now,
    )
    insert_edge(conn, edge)


def _profile_hash(user_anchor_hash: str) -> str:
    return _stable_hash(f"{USER_PROFILE_HASH_PREFIX}{user_anchor_hash}")


def _stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


def _stable_hash_prefix(value: str) -> str:
    # 현재 address_hash가 32자 sha prefix이므로 prefix 문자열 자체를 직접 확인할 수 없다.
    # 향후 hash namespace registry가 생기면 이 함수는 registry lookup으로 대체한다.
    return ""
