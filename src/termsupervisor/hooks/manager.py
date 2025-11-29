"""Hook 状态管理器 - 多层叠加状态管理"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Awaitable

from ..analysis.base import TaskStatus


@dataclass
class HookEvent:
    """Hook 事件"""
    source: str          # 来源: shell, claude-code, gemini, codex
    pane_id: str         # iTerm2 session_id
    status: TaskStatus   # 状态
    reason: str = ""     # 原因描述
    timestamp: datetime = field(default_factory=datetime.now)
    data: dict = field(default_factory=dict)  # 额外数据


# 状态变更回调类型
StatusChangeCallback = Callable[[str, TaskStatus, str, str], Awaitable[None]]
# (pane_id, status, reason, source) -> None


class HookManager:
    """Hook 状态管理器 - 多层叠加

    优先级机制：
    - shell: 基础层，PromptMonitor 提供
    - claude-code/gemini/codex: 高优先级覆盖层

    当新命令开始时（shell RUNNING），清除所有高优先级覆盖。
    """

    # 优先级：数字越大优先级越高
    HOOK_PRIORITY = {
        "shell": 1,         # PromptMonitor，基础层
        "claude-code": 10,  # Claude Code Hook
        "gemini": 10,       # Gemini (预留)
        "codex": 10,        # Codex (预留)
    }

    def __init__(self):
        # {(pane_id, source): HookEvent}
        self._statuses: dict[tuple[str, str], HookEvent] = {}
        # 状态变更回调
        self._on_change: StatusChangeCallback | None = None

    def set_change_callback(self, callback: StatusChangeCallback) -> None:
        """设置状态变更回调"""
        self._on_change = callback

    async def update_status(
        self,
        pane_id: str,
        source: str,
        status: TaskStatus,
        reason: str = "",
        data: dict | None = None
    ) -> None:
        """更新状态

        Args:
            pane_id: iTerm2 session_id
            source: 来源标识
            status: 新状态
            reason: 状态原因
            data: 额外数据
        """
        event = HookEvent(
            source=source,
            pane_id=pane_id,
            status=status,
            reason=reason,
            data=data or {}
        )

        # 记录状态
        self._statuses[(pane_id, source)] = event

        # Shell RUNNING 时清除高优先级覆盖
        if source == "shell" and status == TaskStatus.RUNNING:
            self._clear_overlays(pane_id)

        # 触发回调
        if self._on_change:
            effective_status = self.get_status(pane_id)
            effective_reason = self.get_reason(pane_id)
            effective_source = self.get_active_source(pane_id)
            await self._on_change(pane_id, effective_status, effective_reason, effective_source)

    def get_status(self, pane_id: str) -> TaskStatus:
        """获取 pane 的有效状态（按优先级）"""
        # 按优先级从高到低查找
        for source in sorted(self.HOOK_PRIORITY, key=lambda s: -self.HOOK_PRIORITY[s]):
            if event := self._statuses.get((pane_id, source)):
                return event.status
        return TaskStatus.UNKNOWN

    def get_reason(self, pane_id: str) -> str:
        """获取 pane 的状态原因"""
        for source in sorted(self.HOOK_PRIORITY, key=lambda s: -self.HOOK_PRIORITY[s]):
            if event := self._statuses.get((pane_id, source)):
                return event.reason
        return ""

    def get_active_source(self, pane_id: str) -> str:
        """获取当前生效的 source"""
        for source in sorted(self.HOOK_PRIORITY, key=lambda s: -self.HOOK_PRIORITY[s]):
            if (pane_id, source) in self._statuses:
                return source
        return "unknown"

    def get_event(self, pane_id: str, source: str) -> HookEvent | None:
        """获取特定来源的事件"""
        return self._statuses.get((pane_id, source))

    def _clear_overlays(self, pane_id: str) -> None:
        """清除高优先级覆盖（新命令开始时）"""
        for source, priority in self.HOOK_PRIORITY.items():
            if source != "shell":  # 保留 shell 层
                self._statuses.pop((pane_id, source), None)

    def clear_pane(self, pane_id: str) -> None:
        """清除 pane 的所有状态"""
        keys_to_remove = [k for k in self._statuses if k[0] == pane_id]
        for key in keys_to_remove:
            del self._statuses[key]

    def get_all_panes(self) -> set[str]:
        """获取所有有状态的 pane_id"""
        return {k[0] for k in self._statuses}
