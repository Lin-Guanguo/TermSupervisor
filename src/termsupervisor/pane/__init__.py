"""Pane 模块

提供状态管理的核心组件：
- types: 数据类型定义（HookEvent, StateChange, TaskStatus 等）
- predicates: 流转规则谓词库
- transitions: 状态流转规则表
- state_machine: PaneStateMachine
- pane: Pane 显示层
"""

from .types import (
    TaskStatus,
    HookEvent,
    StateChange,
    StateHistoryEntry,
    DisplayState,
    StateSnapshot,
    TransitionRule,
)
from .predicates import (
    require_exit_code,
    require_exit_code_nonzero,
    require_same_generation,
    require_status_in,
    require_running_duration_gt,
    require_state_id_at_least,
    require_source_match,
)
from .state_machine import PaneStateMachine
from .pane import Pane
from .queue import ActorQueue, EventQueue
from .manager import StateManager
from . import persistence

__all__ = [
    # Types
    "TaskStatus",
    "HookEvent",
    "StateChange",
    "StateHistoryEntry",
    "DisplayState",
    "StateSnapshot",
    "TransitionRule",
    # Predicates
    "require_exit_code",
    "require_exit_code_nonzero",
    "require_same_generation",
    "require_status_in",
    "require_running_duration_gt",
    "require_state_id_at_least",
    "require_source_match",
    # State Machine
    "PaneStateMachine",
    # Pane
    "Pane",
    # Queue
    "ActorQueue",
    "EventQueue",
    # Manager
    "StateManager",
    # Persistence
    "persistence",
]
