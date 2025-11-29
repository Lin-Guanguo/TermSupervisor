"""状态存储 - 管理所有 pane 的状态"""

from __future__ import annotations

import logging
from typing import Callable, Awaitable

from ..analysis.base import TaskStatus
from ..iterm.utils import normalize_session_id
from .state import PaneState

logger = logging.getLogger(__name__)

# 状态变更回调类型: (pane_id, new_state) -> None
StateChangeCallback = Callable[[str, PaneState], Awaitable[None]]


class StateStore:
    """状态存储 - 简化版，单一状态

    每个 pane 只维护一个状态实例。
    状态变更时触发回调通知外部。
    """

    def __init__(self):
        self._states: dict[str, PaneState] = {}  # {pane_id: state}
        self._on_change: StateChangeCallback | None = None

    def get(self, pane_id: str) -> PaneState:
        """获取状态，默认返回 IDLE

        Args:
            pane_id: pane 标识（支持带前缀或纯 UUID 格式）

        Returns:
            PaneState 实例
        """
        normalized_id = normalize_session_id(pane_id)
        if normalized_id not in self._states:
            self._states[normalized_id] = PaneState.idle()
        return self._states[normalized_id]

    async def set(self, pane_id: str, state: PaneState) -> bool:
        """设置状态

        Args:
            pane_id: pane 标识（支持带前缀或纯 UUID 格式）
            state: 新状态

        Returns:
            是否有变化
        """
        normalized_id = normalize_session_id(pane_id)
        old = self._states.get(normalized_id)

        # 检查是否有实际变化
        if old and old.status == state.status and old.description == state.description:
            return False

        self._states[normalized_id] = state

        # 记录日志
        old_status = old.status.value if old else "none"
        logger.info(
            f"[StateStore] {normalized_id[:8]} | {old_status} → {state.status.value} | {state.description}"
        )

        # 触发回调（保持原始 pane_id，以便 WebSocket 广播使用）
        if self._on_change:
            await self._on_change(pane_id, state)

        return True

    def set_change_callback(self, callback: StateChangeCallback) -> None:
        """设置状态变更回调

        Args:
            callback: 回调函数 (pane_id, new_state) -> None
        """
        self._on_change = callback

    def get_all_panes(self) -> set[str]:
        """获取所有有状态的 pane_id

        Returns:
            pane_id 集合
        """
        return set(self._states.keys())

    def get_all_states(self) -> dict[str, PaneState]:
        """获取所有状态

        Returns:
            {pane_id: PaneState} 字典
        """
        return dict(self._states)

    def clear(self, pane_id: str) -> None:
        """清除 pane 状态

        Args:
            pane_id: pane 标识（支持带前缀或纯 UUID 格式）
        """
        normalized_id = normalize_session_id(pane_id)
        self._states.pop(normalized_id, None)

    def clear_all(self) -> None:
        """清除所有状态"""
        self._states.clear()

    def get_status(self, pane_id: str) -> TaskStatus:
        """获取 pane 的状态（便捷方法）

        Args:
            pane_id: pane 标识（支持带前缀或纯 UUID 格式）

        Returns:
            TaskStatus 枚举
        """
        return self.get(pane_id).status  # get() 已处理规范化

    def get_description(self, pane_id: str) -> str:
        """获取 pane 的状态描述（便捷方法）

        Args:
            pane_id: pane 标识（支持带前缀或纯 UUID 格式）

        Returns:
            描述字符串
        """
        return self.get(pane_id).description  # get() 已处理规范化

    def print_all_states(self) -> None:
        """打印所有状态（调试用）"""
        print("\n" + "=" * 60)
        print("[StateStore] All States")
        print("=" * 60)
        for pane_id, state in self._states.items():
            print(f"  {pane_id[:8]} | {state.status.value:15} | {state.source:12} | {state.description}")
        print("=" * 60 + "\n")

    def print_history(self, pane_id: str) -> None:
        """打印 pane 的状态历史（调试用）

        Args:
            pane_id: pane 标识（支持带前缀或纯 UUID 格式）
        """
        normalized_id = normalize_session_id(pane_id)
        state = self._states.get(normalized_id)
        if not state:
            print(f"[StateStore] No state for {pane_id[:8]}")
            return

        print("\n" + "=" * 60)
        print(f"[StateStore] History for {pane_id[:8]}")
        print("=" * 60)
        print(state.get_history_log())
        print("=" * 60 + "\n")
