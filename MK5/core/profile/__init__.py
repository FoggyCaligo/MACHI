"""User profile reference support for MK4.

UserProfile은 사용자에 대한 사실 저장소가 아니라, 현재 사용자와의 대화에서
등장한 WorldGraph concept들을 참조하는 개인화된 context index다.
"""

from .profile_activation import (
    ProfileActivationView,
    build_profile_activation_view,
    profile_context_labels,
)
from .user_profile import (
    USER_PROFILE_EDGE_TYPE,
    USER_PROFILE_IDENTITY_EDGE_TYPE,
    UserProfileView,
    attach_identity_surface_candidates,
    attach_profile_references,
    ensure_user_profile,
    is_identity_surface_edge,
    is_profile_reference_edge,
    is_user_profile_node,
)

__all__ = [
    "USER_PROFILE_EDGE_TYPE",
    "USER_PROFILE_IDENTITY_EDGE_TYPE",
    "ProfileActivationView",
    "UserProfileView",
    "attach_identity_surface_candidates",
    "attach_profile_references",
    "build_profile_activation_view",
    "ensure_user_profile",
    "is_identity_surface_edge",
    "is_profile_reference_edge",
    "is_user_profile_node",
    "profile_context_labels",
]

