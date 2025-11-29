"""Hook 状态管理器 - 多层叠加状态管理"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Awaitable

from ..analysis.base import TaskStatus

logger = logging.getLogger(__name__)


@dataclass
class HookEvent:
    """Hook 事件 - 统一结构体

    通用字段:
    - source: 来源标识
    - pane_id: iTerm2 session_id
    - event_type: 原始事件类型
    - status: 解析后的状态
    - reason: 状态原因描述
    - timestamp: 事件时间

    原始数据:
    - raw_data: 各数据源的原始数据（保留完整信息）

    Shell 原始数据示例:
        {"command": "sleep 10", "exit_code": 0}

    Claude Code 原始数据示例:
        {"hook_event": "stop", "tool_name": "Bash", "session_id": "xxx"}
    """
    source: str              # 来源: shell, claude-code, gemini, codex
    pane_id: str             # iTerm2 session_id
    event_type: str          # 原始事件类型: command_start, command_end, stop, pre_tool...
    status: TaskStatus       # 解析后的状态
    reason: str = ""         # 状态原因描述
    timestamp: datetime = field(default_factory=datetime.now)
    raw_data: dict = field(default_factory=dict)  # 原始数据（各源个性化信息）

    def format_log(self) -> str:
        """格式化为统一日志格式

        格式: [HookEvent] {timestamp} | {source:12} | {pane_short} | {event_type:16} | {status:18} | {reason}
        """
        ts = self.timestamp.strftime("%H:%M:%S.%f")[:-3]  # HH:MM:SS.mmm
        pane_short = self.pane_id.split(":")[-1][:8] if ":" in self.pane_id else self.pane_id[:8]
        status_str = self.status.value
        return f"[HookEvent] {ts} | {self.source:12} | {pane_short:8} | {self.event_type:16} | {status_str:18} | {self.reason}"

    def to_dict(self) -> dict:
        """转换为字典（用于序列化）"""
        return {
            "source": self.source,
            "pane_id": self.pane_id,
            "event_type": self.event_type,
            "status": self.status.value,
            "reason": self.reason,
            "timestamp": self.timestamp.isoformat(),
            "raw_data": self.raw_data,
        }


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
        # {(pane_id, source): HookEvent} - 当前状态
        self._statuses: dict[tuple[str, str], HookEvent] = {}
        # 状态变更回调
        self._on_change: StatusChangeCallback | None = None
        # 事件历史记录（用于调试和状态分析）
        self._event_history: list[HookEvent] = []
        self._max_history = 100  # 最多保留 100 条

    def set_change_callback(self, callback: StatusChangeCallback) -> None:
        """设置状态变更回调"""
        self._on_change = callback

    async def update_status(
        self,
        pane_id: str,
        source: str,
        status: TaskStatus,
        reason: str = "",
        event_type: str = "",
        raw_data: dict | None = None
    ) -> None:
        """更新状态

        Args:
            pane_id: iTerm2 session_id
            source: 来源标识
            status: 新状态
            reason: 状态原因
            event_type: 原始事件类型
            raw_data: 原始数据（各源个性化信息）
        """
        event = HookEvent(
            source=source,
            pane_id=pane_id,
            event_type=event_type or status.value,  # 默认用 status 值
            status=status,
            reason=reason,
            raw_data=raw_data or {}
        )

        # 记录到历史
        self._add_to_history(event)

        # 打印统一格式日志
        print(event.format_log())

        # 记录状态
        old_event = self._statuses.get((pane_id, source))
        self._statuses[(pane_id, source)] = event

        # Shell RUNNING 时清除高优先级覆盖
        if source == "shell" and status == TaskStatus.RUNNING:
            cleared = self._clear_overlays(pane_id)
            if cleared:
                print(f"[HookEvent] {event.timestamp.strftime('%H:%M:%S.%f')[:-3]} | {'<clear>':12} | {pane_id.split(':')[-1][:8]:8} | 清除覆盖层: {cleared}")

        # 触发回调
        if self._on_change:
            effective_status = self.get_status(pane_id)
            effective_reason = self.get_reason(pane_id)
            effective_source = self.get_active_source(pane_id)
            await self._on_change(pane_id, effective_status, effective_reason, effective_source)

    def _add_to_history(self, event: HookEvent) -> None:
        """添加到事件历史"""
        self._event_history.append(event)
        # 限制历史长度
        if len(self._event_history) > self._max_history:
            self._event_history = self._event_history[-self._max_history:]

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

    def _clear_overlays(self, pane_id: str) -> list[str]:
        """清除高优先级覆盖（新命令开始时）

        Returns:
            被清除的 source 列表
        """
        cleared = []
        for source, priority in self.HOOK_PRIORITY.items():
            if source != "shell":  # 保留 shell 层
                if self._statuses.pop((pane_id, source), None):
                    cleared.append(source)
        return cleared

    def clear_pane(self, pane_id: str) -> None:
        """清除 pane 的所有状态"""
        keys_to_remove = [k for k in self._statuses if k[0] == pane_id]
        for key in keys_to_remove:
            del self._statuses[key]

    def get_all_panes(self) -> set[str]:
        """获取所有有状态的 pane_id"""
        return {k[0] for k in self._statuses}

    def get_history(self, pane_id: str | None = None, limit: int = 20) -> list[HookEvent]:
        """获取事件历史

        Args:
            pane_id: 过滤特定 pane，None 表示全部
            limit: 返回条数限制

        Returns:
            事件列表（最新的在前）
        """
        events = self._event_history
        if pane_id:
            events = [e for e in events if e.pane_id == pane_id]
        return list(reversed(events[-limit:]))

    def print_history(self, pane_id: str | None = None, limit: int = 20) -> None:
        """打印事件历史"""
        events = self.get_history(pane_id, limit)
        print(f"\n{'=' * 80}")
        print(f"[HookEvent History] 最近 {len(events)} 条记录" + (f" (pane: {pane_id[:8]})" if pane_id else ""))
        print(f"{'=' * 80}")
        for event in reversed(events):  # 按时间正序打印
            print(event.format_log())
        print(f"{'=' * 80}\n")
