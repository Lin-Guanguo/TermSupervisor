"""事件处理器 - 连接 HookEvent 和 StateMachine"""

import logging
from dataclasses import dataclass, field
from datetime import datetime

from .state import PaneState
from .state_machine import StateMachine
from .state_store import StateStore

logger = logging.getLogger(__name__)


@dataclass
class HookEvent:
    """Hook 事件 - 统一事件格式

    所有 Signal Source 产生的事件都转换为此格式。

    Attributes:
        source: 来源标识 (shell, claude-code, render, iterm, frontend, timer)
        pane_id: iTerm2 session_id
        event_type: 事件类型 (command_start, Stop, content_updated, etc.)
        raw_data: 原始数据（各源个性化信息）
        timestamp: 事件时间
    """
    source: str
    pane_id: str
    event_type: str
    raw_data: dict = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def signal(self) -> str:
        """获取信号字符串"""
        return f"{self.source}.{self.event_type}"

    def format_log(self) -> str:
        """格式化为日志字符串"""
        ts = self.timestamp.strftime("%H:%M:%S.%f")[:-3]
        pane_short = self.pane_id.split(":")[-1][:8] if ":" in self.pane_id else self.pane_id[:8]
        return f"[HookEvent] {ts} | {self.source:12} | {pane_short:8} | {self.event_type}"


class EventProcessor:
    """事件处理器 - 连接 HookEvent 和 StateMachine

    职责：
    1. 接收 HookEvent
    2. 调用 StateMachine 计算状态转换
    3. 更新 StateStore
    4. 记录状态历史
    """

    def __init__(self, state_store: StateStore, state_machine: StateMachine):
        self.state_store = state_store
        self.state_machine = state_machine

    async def process(self, event: HookEvent) -> bool:
        """处理事件

        Args:
            event: Hook 事件

        Returns:
            是否有状态变化
        """
        pane_id = event.pane_id
        signal = event.signal

        # 记录事件日志（直接 print 确保可见）
        print(event.format_log())

        # 获取当前状态
        current = self.state_store.get(pane_id)

        # 状态机转换
        new_state = self.state_machine.transition(current, signal, event.raw_data)

        # 更新状态
        if new_state:
            # 成功转换，记录历史
            new_state.add_history(signal, success=True)
            return await self.state_store.set(pane_id, new_state)
        else:
            # 无匹配转换，记录到当前状态的历史
            current.add_history(signal, success=False)
            logger.debug(f"[EventProcessor] No transition for {signal} in state {current.status.value}")
            return False

    async def process_shell_command_start(self, pane_id: str, command: str) -> bool:
        """处理 shell 命令开始事件（便捷方法）"""
        return await self.process(HookEvent(
            source="shell",
            pane_id=pane_id,
            event_type="command_start",
            raw_data={"command": command}
        ))

    async def process_shell_command_end(self, pane_id: str, exit_code: int) -> bool:
        """处理 shell 命令结束事件（便捷方法）"""
        return await self.process(HookEvent(
            source="shell",
            pane_id=pane_id,
            event_type="command_end",
            raw_data={"exit_code": exit_code}
        ))

    async def process_claude_code_event(
        self,
        pane_id: str,
        event_type: str,
        data: dict | None = None
    ) -> bool:
        """处理 Claude Code 事件（便捷方法）"""
        return await self.process(HookEvent(
            source="claude-code",
            pane_id=pane_id,
            event_type=event_type,
            raw_data=data
        ))

    async def process_user_focus(self, pane_id: str) -> bool:
        """处理用户 focus 事件（便捷方法）"""
        return await self.process(HookEvent(
            source="iterm",
            pane_id=pane_id,
            event_type="focus"
        ))

    async def process_user_click(self, pane_id: str, click_type: str = "click_pane") -> bool:
        """处理用户点击事件（便捷方法）"""
        return await self.process(HookEvent(
            source="frontend",
            pane_id=pane_id,
            event_type=click_type
        ))

    async def process_timer_check(self, pane_id: str, elapsed: str) -> bool:
        """处理定时检查事件（便捷方法）"""
        return await self.process(HookEvent(
            source="timer",
            pane_id=pane_id,
            event_type="check",
            raw_data={"elapsed": elapsed}
        ))

    async def process_render_content_updated(self, pane_id: str, lines_changed: int) -> bool:
        """处理 render 内容更新事件（便捷方法）"""
        return await self.process(HookEvent(
            source="render",
            pane_id=pane_id,
            event_type="content_updated",
            raw_data={"lines_changed": lines_changed}
        ))
