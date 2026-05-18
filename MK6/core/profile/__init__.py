"""User profile reference support for MK6.

UserProfile은 사용자에 대한 사실 저장소가 아니라, 현재 사용자와의 대화에서
등장한 WorldGraph concept들을 참조하는 개인화된 context index다.
"""

from .user_profile import (
    USER_PROFILE_EDGE_TYPE,
    UserProfileView,
    attach_profile_references,
    ensure_user_profile,
    is_profile_reference_edge,
    is_user_profile_node,
)

__all__ = [
    "USER_PROFILE_EDGE_TYPE",
    "UserProfileView",
    "attach_profile_references",
    "ensure_user_profile",
    "is_profile_reference_edge",
    "is_user_profile_node",
]
