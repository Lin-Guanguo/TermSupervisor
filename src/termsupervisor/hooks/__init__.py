"""Hook 系统 - 接收外部工具状态事件

模块结构：
- state: PaneState, StateHistoryEntry 数据结构
- state_machine: StateMachine 状态转换逻辑
- state_store: StateStore 状态存储
- event_processor: EventProcessor, HookEvent 事件处理
- manager: HookManager 原有管理器（待重构）
- receiver: HookReceiver HTTP 接收器
- sources/: 各类 Hook 源
"""

from .manager import HookManager
from .receiver import HookReceiver
from .sources.base import HookSource
from .state import PaneState, StateHistoryEntry
from .state_machine import StateMachine
from .state_store import StateStore
from .event_processor import EventProcessor, HookEvent

__all__ = [
    # 新状态机模块
    "PaneState",
    "StateHistoryEntry",
    "StateMachine",
    "StateStore",
    "EventProcessor",
    "HookEvent",
    # 原有模块
    "HookManager",
    "HookReceiver",
    "HookSource",
]
