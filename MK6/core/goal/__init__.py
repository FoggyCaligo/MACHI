"""Goal graph support for MK6.

Goal의 본체는 문자열 label이나 node_kind가 아니라 WorldGraph의 node/edge 구조다.
이 패키지는 그 구조를 초기화하고 조회하는 얇은 레이어만 제공한다.
"""

from .goal_graph import (
    GLOBAL_GOAL_AXIS_SEEDS,
    GOAL_ROOT_HASH,
    GoalAxisSeed,
    initialize_global_goal_graph,
    load_goal_view,
)
from .goal_view import GoalAxisRef, GoalView
from .turn_goal import TurnGoalView, build_turn_goal_view

__all__ = [
    "GLOBAL_GOAL_AXIS_SEEDS",
    "GOAL_ROOT_HASH",
    "GoalAxisSeed",
    "GoalAxisRef",
    "GoalView",
    "TurnGoalView",
    "build_turn_goal_view",
    "initialize_global_goal_graph",
    "load_goal_view",
]
