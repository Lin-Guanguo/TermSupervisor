"""HookManager - Hook 系统门面

统一入口：
- emit_event: 统一事件入口（规范化 + 日志 + 指标 + 入队）
- 组装 HookEvent（补全 generation/time/signal）
- 调用 StateManager 处理事件
- 提供便捷 API

Sources 通过 emit_event 发送事件，Manager 负责：
1. 规范化事件（补全 generation/timestamp/signal）
2. 可选日志记录
3. 指标计数（hooks.events_total）
4. 入队处理
"""

import logging
from datetime import datetime
from typing import Callable, Any, TYPE_CHECKING

from ..telemetry import get_logger, metrics
from ..pane import TaskStatus, HookEvent, StateManager, DisplayState
from ..config import METRICS_ENABLED

if TYPE_CHECKING:
    from ..timer import Timer

logger = get_logger(__name__)

# 日志级别常量
LOG_DEBUG = logging.DEBUG
LOG_INFO = logging.INFO
LOG_WARNING = logging.WARNING

# 回调类型
StatusChangeCallback = Callable[[str, TaskStatus, str, str, bool], Any]
FocusChecker = Callable[[str], bool]


class HookManager:
    """Hook 系统门面

    提供统一的事件处理入口，内部持有 Timer 和 StateManager。

    使用示例:
        timer = Timer()
        manager = HookManager(timer=timer)

        # 处理 shell 命令
        await manager.process_shell_command_start(pane_id, "ls -la")
        await manager.process_shell_command_end(pane_id, 0)

        # 处理 Claude 事件
        await manager.process_claude_code_event(pane_id, "PreToolUse", {"tool_name": "Read"})
    """

    def __init__(self, timer: "Timer | None" = None, state_manager: StateManager | None = None):
        """初始化

        Args:
            timer: Timer 实例
            state_manager: StateManager 实例（可选，默认创建新的）
        """
        self._timer = timer
        self._state_manager = state_manager or StateManager(timer=timer)
        self._on_change: StatusChangeCallback | None = None

        # 绑定内部回调
        self._state_manager.set_on_display_change(self._on_display_change)

    # === 配置 ===

    def set_timer(self, timer: "Timer") -> None:
        """设置 Timer"""
        self._timer = timer
        self._state_manager.set_timer(timer)

    def set_change_callback(self, callback: StatusChangeCallback) -> None:
        """设置状态变更回调

        Args:
            callback: 回调函数 (pane_id, status, description, source, suppressed) -> None
        """
        self._on_change = callback

    def set_focus_checker(self, checker: FocusChecker) -> None:
        """设置 focus 检查函数"""
        self._state_manager.set_focus_checker(checker)

    def _on_display_change(
        self,
        pane_id: str,
        display_state: DisplayState,
        suppressed: bool,
        reason: str
    ) -> None:
        """内部显示变化回调"""
        if self._on_change:
            self._on_change(
                pane_id,
                display_state.status,
                display_state.description,
                display_state.source,
                suppressed,
            )

    # === 事件处理 ===

    def _normalize_event(
        self,
        source: str,
        pane_id: str,
        event_type: str,
        data: dict | None = None,
    ) -> HookEvent:
        """构造并规范化 HookEvent

        补全 generation、timestamp、signal。

        Args:
            source: 事件源
            pane_id: pane 标识
            event_type: 事件类型
            data: 事件数据

        Returns:
            规范化的 HookEvent
        """
        generation = self._state_manager.get_generation(pane_id)
        return HookEvent(
            source=source,
            pane_id=pane_id,
            event_type=event_type,
            signal=f"{source}.{event_type}",
            data=data or {},
            timestamp=datetime.now().timestamp(),
            pane_generation=generation,
        )

    async def process_event(self, event: HookEvent) -> bool:
        """处理事件

        Args:
            event: Hook 事件

        Returns:
            是否成功入队
        """
        # 如果 generation 缺失，补全
        if event.pane_generation == 0:
            event.pane_generation = self._state_manager.get_generation(event.pane_id)

        # 入队并处理
        if self._state_manager.enqueue(event):
            await self._state_manager.process_queued(event.pane_id)
            return True
        return False

    async def emit_event(
        self,
        source: str,
        pane_id: str,
        event_type: str,
        data: dict | None = None,
        *,
        log: bool = True,
        log_level: int = LOG_INFO,
    ) -> bool:
        """统一事件入口

        Sources 通过此方法发送事件。Manager 负责：
        1. 规范化事件（补全 generation/timestamp/signal）
        2. 可选日志记录
        3. 指标计数
        4. 入队处理

        Args:
            source: 事件来源 (shell, claude-code, content, iterm, frontend, timer)
            pane_id: pane 标识
            event_type: 事件类型
            data: 事件数据（可选）
            log: 是否记录日志，默认 True
            log_level: 日志级别，默认 INFO

        Returns:
            是否成功入队
        """
        # 1. 规范化事件
        event = self._normalize_event(source, pane_id, event_type, data)

        # 2. 可选日志
        if log:
            logger.log(log_level, event.format_log())

        # 3. 指标计数（受 METRICS_ENABLED 控制）
        if METRICS_ENABLED:
            metrics.inc(
                "hooks.events_total",
                labels={"source": source, "event_type": event_type},
            )

        # 4. 入队处理
        return await self.process_event(event)

    # === Shell 事件 ===

    async def process_shell_command_start(self, pane_id: str, command: str) -> bool:
        """处理 shell 命令开始

        Note: 此方法为兼容层，内部委托给 emit_event。
        """
        return await self.emit_event(
            source="shell",
            pane_id=pane_id,
            event_type="command_start",
            data={"command": command},
        )

    async def process_shell_command_end(self, pane_id: str, exit_code: int) -> bool:
        """处理 shell 命令结束

        Note: 此方法为兼容层，内部委托给 emit_event。
        """
        return await self.emit_event(
            source="shell",
            pane_id=pane_id,
            event_type="command_end",
            data={"exit_code": exit_code},
        )

    # === Claude Code 事件 ===

    async def process_claude_code_event(
        self,
        pane_id: str,
        event_type: str,
        data: dict | None = None,
    ) -> bool:
        """处理 Claude Code 事件

        Note: 此方法为兼容层，内部委托给 emit_event。
        """
        # 规范化事件类型
        normalized_type = self._normalize_claude_event_type(event_type)
        return await self.emit_event(
            source="claude-code",
            pane_id=pane_id,
            event_type=normalized_type,
            data=data,
        )

    def _normalize_claude_event_type(self, event_type: str) -> str:
        """规范化 Claude 事件类型"""
        event_map = {
            "stop": "Stop",
            "pre_tool": "PreToolUse",
            "pre_tool_use": "PreToolUse",
            "post_tool": "PostToolUse",
            "post_tool_use": "PostToolUse",
            "session_start": "SessionStart",
            "session_end": "SessionEnd",
            "permission_prompt": "Notification:permission_prompt",
            "idle_prompt": "Notification:idle_prompt",
            "subagent_stop": "SubagentStop",
        }
        return event_map.get(event_type.lower(), event_type)

    # === 用户事件 ===

    async def process_user_focus(self, pane_id: str) -> bool:
        """处理用户 focus 事件

        Note: 此方法为兼容层，内部委托给 emit_event。
        """
        return await self.emit_event(
            source="iterm",
            pane_id=pane_id,
            event_type="focus",
        )

    async def process_user_click(self, pane_id: str, click_type: str = "click_pane") -> bool:
        """处理用户点击事件

        Note: 此方法为兼容层，内部委托给 emit_event。
        """
        return await self.emit_event(
            source="frontend",
            pane_id=pane_id,
            event_type=click_type,
        )

    # === 内容事件 ===

    async def process_content_changed(
        self,
        pane_id: str,
        content: str = "",
        content_hash: str = "",
    ) -> bool:
        """处理内容变化事件

        Note: 此方法为兼容层，内部委托给 emit_event。
        内容事件禁用日志（太频繁），但仍计数指标。
        """
        return await self.emit_event(
            source="content",
            pane_id=pane_id,
            event_type="changed",
            data={"content": content, "content_hash": content_hash},
            log=False,  # 不记录日志（太频繁）
        )

    # === Timer 事件 ===

    async def process_timer_check(self, pane_id: str, elapsed: str) -> bool:
        """处理定时检查事件（通常由 tick_all 内部调用）

        Note: 此方法为兼容层，内部委托给 emit_event。
        """
        return await self.emit_event(
            source="timer",
            pane_id=pane_id,
            event_type="check",
            data={"elapsed": elapsed},
            log=False,  # Timer 事件由 StateManager 内部触发，无需额外日志
        )

    def tick_all(self) -> list[str]:
        """检查所有 pane 的 LONG_RUNNING

        由 Timer 周期调用。

        Returns:
            触发了 LONG_RUNNING 的 pane_id 列表
        """
        return self._state_manager.tick_all()

    # === 状态查询 ===

    def get_status(self, pane_id: str) -> TaskStatus:
        """获取 pane 状态"""
        return self._state_manager.get_status(pane_id)

    def get_reason(self, pane_id: str) -> str:
        """获取状态描述"""
        pane = self._state_manager.get_pane(pane_id)
        return pane.display_state.description if pane else ""

    def get_active_source(self, pane_id: str) -> str:
        """获取当前状态来源"""
        pane = self._state_manager.get_pane(pane_id)
        return pane.display_state.source if pane else "shell"

    def get_state(self, pane_id: str) -> DisplayState | None:
        """获取完整的 DisplayState"""
        pane = self._state_manager.get_pane(pane_id)
        return pane.display_state if pane else None

    def get_all_panes(self) -> set[str]:
        """获取所有 pane_id"""
        return self._state_manager.get_all_panes()

    def get_all_states(self) -> dict[str, dict]:
        """获取所有状态"""
        return self._state_manager.get_all_states()

    # === 生命周期 ===

    def get_generation(self, pane_id: str) -> int:
        """获取 pane generation"""
        return self._state_manager.get_generation(pane_id)

    def increment_generation(self, pane_id: str) -> int:
        """递增 pane generation"""
        return self._state_manager.increment_generation(pane_id)

    # === 清理 ===

    def remove_pane(self, pane_id: str) -> None:
        """移除 pane"""
        self._state_manager.remove_pane(pane_id)

    def cleanup_closed_panes(self, active_pane_ids: set[str]) -> list[str]:
        """清理已关闭的 pane"""
        return self._state_manager.cleanup_closed_panes(active_pane_ids)

    def clear_pane(self, pane_id: str) -> None:
        """清除 pane 状态（兼容旧 API）"""
        self.remove_pane(pane_id)

    def clear_all(self) -> None:
        """清除所有状态"""
        for pane_id in list(self._state_manager.get_all_panes()):
            self.remove_pane(pane_id)

    # === 持久化 ===

    def save(self) -> bool:
        """保存状态"""
        return self._state_manager.save()

    def load(self) -> bool:
        """加载状态"""
        return self._state_manager.load()

    # === 调试 ===

    def print_all_states(self) -> None:
        """打印所有状态（调试用）"""
        print("\n" + "=" * 60)
        print("[HookManager] All States")
        print("=" * 60)
        for pane_id, state in self.get_all_states().items():
            print(f"  {pane_id[:8]} | {state['status']:15} | {state['source']:12}")
        print("=" * 60 + "\n")

    def print_history(self, pane_id: str) -> None:
        """打印 pane 的状态历史（调试用）"""
        machine = self._state_manager.get_machine(pane_id)
        if not machine:
            print(f"[HookManager] No state for {pane_id[:8]}")
            return

        print("\n" + "=" * 60)
        print(f"[HookManager] History for {pane_id[:8]}")
        print("=" * 60)
        print(machine.get_history_log())
        print("=" * 60 + "\n")

    def get_history(self, pane_id: str) -> list:
        """获取 pane 的状态历史"""
        machine = self._state_manager.get_machine(pane_id)
        return machine.history if machine else []

    # === 内部访问（用于集成）===

    @property
    def state_manager(self) -> StateManager:
        """获取 StateManager（用于高级集成）"""
        return self._state_manager

    @property
    def timer(self) -> "Timer | None":
        """获取 Timer"""
        return self._timer
