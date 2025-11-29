"""Hook 状态管理器 - 基于状态机的单一状态管理"""

import logging
from typing import Callable, Awaitable

from ..analysis.base import TaskStatus
from .state import PaneState
from .state_machine import StateMachine
from .state_store import StateStore
from .event_processor import EventProcessor, HookEvent

logger = logging.getLogger(__name__)


# 状态变更回调类型: (pane_id, status, description, source) -> None
StatusChangeCallback = Callable[[str, TaskStatus, str, str], Awaitable[None]]


class HookManager:
    """Hook 状态管理器 - 基于状态机

    使用单一状态模型，通过 StateMachine 处理状态转换。
    支持多种信号源：shell, claude-code, gemini, codex, render, timer, user

    优先级机制：
    - claude-code/gemini/codex: 高优先级 (10)
    - shell/render: 低优先级 (1)
    - timer: 最低优先级 (0)
    - 用户操作 (iterm/frontend): 总是可以覆盖
    """

    def __init__(self):
        self._state_store = StateStore()
        self._state_machine = StateMachine()
        self._event_processor = EventProcessor(self._state_store, self._state_machine)
        self._on_change: StatusChangeCallback | None = None

        # 设置状态变更回调
        self._state_store.set_change_callback(self._on_state_change)

    async def _on_state_change(self, pane_id: str, state: PaneState) -> None:
        """状态变更内部回调 - 转发给外部回调"""
        if self._on_change:
            await self._on_change(
                pane_id,
                state.status,
                state.description,
                state.source
            )

    def set_change_callback(self, callback: StatusChangeCallback) -> None:
        """设置状态变更回调

        Args:
            callback: 回调函数 (pane_id, status, description, source) -> None
        """
        self._on_change = callback

    # ==================== 事件处理 API ====================

    async def update_status(
        self,
        pane_id: str,
        source: str,
        status: TaskStatus,
        reason: str = "",
        event_type: str = "",
        raw_data: dict | None = None
    ) -> None:
        """更新状态（兼容旧 API）

        将旧格式的状态更新转换为新的 Signal 格式。

        Args:
            pane_id: iTerm2 session_id
            source: 来源标识 (shell, claude-code, etc.)
            status: 任务状态（用于映射到事件类型）
            reason: 状态原因（作为 description）
            event_type: 原始事件类型
            raw_data: 原始数据
        """
        # 构造 Signal
        signal_event = self._map_to_signal_event(source, status, event_type)

        # 构造 HookEvent
        event = HookEvent(
            source=source,
            pane_id=pane_id,
            event_type=signal_event,
            raw_data=raw_data or {}
        )

        # 添加 description 信息到 raw_data
        if reason and "description" not in event.raw_data:
            event.raw_data["description"] = reason

        # 记录事件日志
        logger.info(event.format_log())

        # 处理事件
        await self._event_processor.process(event)

    def _map_to_signal_event(
        self,
        source: str,
        status: TaskStatus,
        event_type: str
    ) -> str:
        """将旧格式映射到新的 Signal event_type

        Args:
            source: 来源
            status: 状态
            event_type: 原始事件类型

        Returns:
            Signal 中的 event_type
        """
        # 如果已有 event_type，直接使用
        if event_type:
            # 转换为 PascalCase 格式（如果需要）
            return self._normalize_event_type(source, event_type)

        # 根据 status 映射默认事件
        if source == "shell":
            if status == TaskStatus.RUNNING:
                return "command_start"
            elif status in (TaskStatus.DONE, TaskStatus.FAILED):
                return "command_end"
            return "unknown"

        if source == "claude-code":
            status_to_event = {
                TaskStatus.RUNNING: "PreToolUse",
                TaskStatus.DONE: "Stop",
                TaskStatus.FAILED: "Stop",
                TaskStatus.IDLE: "SessionEnd",
                TaskStatus.WAITING_APPROVAL: "Notification:permission_prompt",
            }
            return status_to_event.get(status, "unknown")

        return "unknown"

    def _normalize_event_type(self, source: str, event_type: str) -> str:
        """规范化事件类型名称

        Args:
            source: 来源
            event_type: 原始事件类型

        Returns:
            规范化后的事件类型
        """
        if source == "claude-code":
            # Claude Code 事件映射
            event_map = {
                "stop": "Stop",
                "pre_tool": "PreToolUse",
                "post_tool": "PostToolUse",
                "session_start": "SessionStart",
                "session_end": "SessionEnd",
                "permission_prompt": "Notification:permission_prompt",
                "idle_prompt": "Notification:idle_prompt",
                "subagent_stop": "SubagentStop",
            }
            return event_map.get(event_type.lower(), event_type)

        # shell 事件保持不变
        return event_type

    # ==================== 状态查询 API ====================

    def get_status(self, pane_id: str) -> TaskStatus:
        """获取 pane 的当前状态"""
        return self._state_store.get_status(pane_id)

    def get_reason(self, pane_id: str) -> str:
        """获取 pane 的状态描述"""
        return self._state_store.get_description(pane_id)

    def get_active_source(self, pane_id: str) -> str:
        """获取当前状态的来源"""
        return self._state_store.get(pane_id).source

    def get_state(self, pane_id: str) -> PaneState:
        """获取完整的 PaneState"""
        return self._state_store.get(pane_id)

    def get_all_panes(self) -> set[str]:
        """获取所有有状态的 pane_id"""
        return self._state_store.get_all_panes()

    def get_all_states(self) -> dict[str, PaneState]:
        """获取所有状态"""
        return self._state_store.get_all_states()

    # ==================== 便捷方法 ====================

    async def process_shell_command_start(self, pane_id: str, command: str) -> bool:
        """处理 shell 命令开始"""
        return await self._event_processor.process_shell_command_start(pane_id, command)

    async def process_shell_command_end(self, pane_id: str, exit_code: int) -> bool:
        """处理 shell 命令结束"""
        return await self._event_processor.process_shell_command_end(pane_id, exit_code)

    async def process_claude_code_event(
        self,
        pane_id: str,
        event_type: str,
        data: dict | None = None
    ) -> bool:
        """处理 Claude Code 事件"""
        # 规范化事件类型
        normalized_event = self._normalize_event_type("claude-code", event_type)
        return await self._event_processor.process_claude_code_event(
            pane_id, normalized_event, data
        )

    async def process_user_focus(self, pane_id: str) -> bool:
        """处理用户 focus 事件"""
        return await self._event_processor.process_user_focus(pane_id)

    async def process_user_click(self, pane_id: str, click_type: str = "click_pane") -> bool:
        """处理用户点击事件"""
        return await self._event_processor.process_user_click(pane_id, click_type)

    async def process_timer_check(self, pane_id: str, elapsed: str) -> bool:
        """处理定时检查事件"""
        return await self._event_processor.process_timer_check(pane_id, elapsed)

    async def process_render_content_updated(self, pane_id: str, lines_changed: int) -> bool:
        """处理 render 内容更新事件"""
        return await self._event_processor.process_render_content_updated(pane_id, lines_changed)

    # ==================== 状态管理 ====================

    def clear_pane(self, pane_id: str) -> None:
        """清除 pane 的状态"""
        self._state_store.clear(pane_id)

    def clear_all(self) -> None:
        """清除所有状态"""
        self._state_store.clear_all()

    # ==================== 调试工具 ====================

    def print_all_states(self) -> None:
        """打印所有状态（调试用）"""
        self._state_store.print_all_states()

    def print_history(self, pane_id: str) -> None:
        """打印 pane 的状态历史（调试用）"""
        self._state_store.print_history(pane_id)

    def get_history(self, pane_id: str) -> list:
        """获取 pane 的状态历史"""
        state = self._state_store.get(pane_id)
        return state.history
