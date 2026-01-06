"""State 模块

提供状态管理的核心组件：
- types: 数据类型定义（HookEvent, StateChange, TaskStatus 等）
- predicates: 流转规则谓词库
- transitions: 状态流转规则表
- state_machine: PaneStateMachine
- manager: StateManager（统一状态管理）
"""

from .manager import StateManager
from .predicates import (
    require_exit_code,
    require_exit_code_nonzero,
)
from .queue import ActorQueue, EventQueue
from .state_machine import PaneStateMachine
from .types import (
    DisplayState,
    DisplayUpdate,
    HookEvent,
    StateChange,
    StateHistoryEntry,
    StateSnapshot,
    TaskStatus,
    TransitionRule,
)

__all__ = [
    # Types
    "TaskStatus",
    "HookEvent",
    "StateChange",
    "StateHistoryEntry",
    "DisplayState",
    "DisplayUpdate",
    "StateSnapshot",
    "TransitionRule",
    # Predicates
    "require_exit_code",
    "require_exit_code_nonzero",
    # State Machine
    "PaneStateMachine",
    # Queue
    "ActorQueue",
    "EventQueue",
    # Manager
    "StateManager",
]
