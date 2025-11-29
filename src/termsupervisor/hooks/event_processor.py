"""事件处理器 - 连接 HookEvent 和 StateMachine

层级职责：
- HookEvent: 统一事件格式
- EventProcessor: 事件处理流程（调用状态机、更新存储、触发定时器）
- AutoClearTimer: DONE/FAILED 状态的延迟清除逻辑
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, TYPE_CHECKING

from ..analysis.base import TaskStatus
from ..config import DONE_FAILED_AUTO_CLEAR_SECONDS
from .state import PaneState
from .state_machine import StateMachine
from .state_store import StateStore

if TYPE_CHECKING:
    from .event_processor import EventProcessor

logger = logging.getLogger(__name__)

# Focus 检查函数类型: (pane_id) -> bool
FocusChecker = Callable[[str], bool]


# =============================================================================
# HookEvent - 统一事件格式
# =============================================================================


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


# =============================================================================
# AutoClearTimer - DONE/FAILED 状态延迟清除
# =============================================================================


class AutoClearTimer:
    """DONE/FAILED 状态的延迟清除定时器

    设计目的：
    - 用户看到 DONE/FAILED 状态后，等待一段时间再清除
    - 如果中间状态变化了，不会误清除

    触发场景：
    1. 状态变为 DONE/FAILED 且 pane 被 focus
    2. focus 事件到达时状态已是 DONE/FAILED

    安全机制：
    - 使用 state_id（自增）判断是否同一状态实例
    - 避免 DONE→RUNNING→DONE 误清除
    """

    def __init__(self, state_store: StateStore):
        self._state_store = state_store
        self._focus_checker: FocusChecker | None = None
        self._tasks: dict[str, asyncio.Task] = {}  # {pane_id: Task}

    def set_focus_checker(self, checker: FocusChecker) -> None:
        """设置 focus 检查函数"""
        self._focus_checker = checker

    async def on_state_changed(self, pane_id: str, state: PaneState) -> None:
        """状态变化时调用

        - DONE/FAILED + focus → 启动定时器
        - 其他状态 → 取消定时器
        """
        if state.status in (TaskStatus.DONE, TaskStatus.FAILED):
            is_focused = self._focus_checker(pane_id) if self._focus_checker else False
            if is_focused:
                self._start_timer(pane_id, state.state_id)
        else:
            self._cancel_timer(pane_id)

    async def on_focus_event(self, pane_id: str, state: PaneState) -> None:
        """focus 事件到达时调用（状态机未转换的情况）

        如果当前是 DONE/FAILED，启动延迟清除。
        """
        if state.status in (TaskStatus.DONE, TaskStatus.FAILED):
            self._start_timer(pane_id, state.state_id)

    def _start_timer(self, pane_id: str, state_id: int) -> None:
        """启动延迟清除定时器"""
        self._cancel_timer(pane_id)
        self._tasks[pane_id] = asyncio.create_task(
            self._clear_after_delay(pane_id, state_id)
        )
        logger.debug(f"[AutoClear] 启动: {pane_id[:8]}, state_id={state_id}")

    def _cancel_timer(self, pane_id: str) -> None:
        """取消定时器"""
        task = self._tasks.pop(pane_id, None)
        if task and not task.done():
            task.cancel()
            logger.debug(f"[AutoClear] 取消: {pane_id[:8]}")

    async def _clear_after_delay(self, pane_id: str, original_state_id: int) -> None:
        """延迟后清除状态"""
        try:
            await asyncio.sleep(DONE_FAILED_AUTO_CLEAR_SECONDS)
            self._tasks.pop(pane_id, None)

            # 检查 state_id 是否变化
            current = self._state_store.get(pane_id)
            if current.state_id > original_state_id:
                logger.debug(
                    f"[AutoClear] 跳过: {pane_id[:8]} "
                    f"state_id 变化 ({original_state_id} → {current.state_id})"
                )
                return

            # 清除为 IDLE
            logger.info(f"[AutoClear] 清除 {current.status.value}: {pane_id[:8]}")
            idle_state = PaneState.idle()
            idle_state.add_history("auto_clear.timer", success=True)
            await self._state_store.set(pane_id, idle_state)

        except asyncio.CancelledError:
            pass


# =============================================================================
# EventProcessor - 事件处理流程
# =============================================================================


class EventProcessor:
    """事件处理器 - 连接 HookEvent 和 StateMachine

    职责：
    1. 接收 HookEvent
    2. 调用 StateMachine 计算状态转换
    3. 更新 StateStore
    4. 记录状态历史
    5. 委托 AutoClearTimer 处理延迟清除
    """

    def __init__(self, state_store: StateStore, state_machine: StateMachine):
        self.state_store = state_store
        self.state_machine = state_machine
        self._auto_clear = AutoClearTimer(state_store)

    def set_focus_checker(self, checker: FocusChecker) -> None:
        """设置 focus 检查函数"""
        self._auto_clear.set_focus_checker(checker)

    async def process(self, event: HookEvent) -> bool:
        """处理事件

        流程：
        1. 调用状态机计算转换
        2. 更新状态存储
        3. 通知 AutoClearTimer
        """
        pane_id = event.pane_id
        signal = event.signal

        print(event.format_log())

        current = self.state_store.get(pane_id)
        new_state = self.state_machine.transition(current, signal, event.raw_data)

        if new_state:
            # 状态转换成功
            new_state.add_history(signal, success=True)
            changed = await self.state_store.set(pane_id, new_state)
            if changed:
                await self._auto_clear.on_state_changed(pane_id, new_state)
            return changed
        else:
            # 状态机未转换
            current.add_history(signal, success=False)

            # focus 事件特殊处理：触发延迟清除
            if self._is_focus_event(signal):
                await self._auto_clear.on_focus_event(pane_id, current)

            logger.debug(f"[EventProcessor] No transition: {signal} in {current.status.value}")
            return False

    def _is_focus_event(self, signal: str) -> bool:
        """判断是否为 focus 事件"""
        source = signal.split(".", 1)[0] if "." in signal else signal
        return source in ("iterm", "frontend")

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
