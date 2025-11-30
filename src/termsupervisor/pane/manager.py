"""StateManager - 状态管理器

协调 PaneStateMachine 与 Pane：
- 创建/管理实例
- 绑定回调
- 处理事件（通过 actor 队列串行化）
- 轮询 LONG_RUNNING
- 持久化
- 清理过期 pane
"""

import asyncio
from datetime import datetime
from typing import Callable, Any, TYPE_CHECKING

from ..telemetry import get_logger, metrics
from ..config import LONG_RUNNING_THRESHOLD_SECONDS
from ..iterm.utils import normalize_session_id
from .types import TaskStatus, HookEvent, StateChange, DisplayState
from .state_machine import PaneStateMachine
from .pane import Pane
from .queue import EventQueue
from . import persistence

if TYPE_CHECKING:
    from ..timer import Timer

logger = get_logger(__name__)

# 回调类型
OnDisplayChangeCallback = Callable[[str, DisplayState, bool, str], Any]
FocusChecker = Callable[[str], bool]


class StateManager:
    """状态管理器

    协调 StateMachine 和 Pane，提供统一的事件处理入口。

    Attributes:
        timer: Timer 实例
        machines: 状态机字典 {pane_id: PaneStateMachine}
        panes: Pane 字典 {pane_id: Pane}
        queues: 事件队列字典 {pane_id: EventQueue}
    """

    def __init__(self, timer: "Timer | None" = None):
        """初始化

        Args:
            timer: Timer 实例
        """
        self._timer = timer
        self._machines: dict[str, PaneStateMachine] = {}
        self._panes: dict[str, Pane] = {}
        self._queues: dict[str, EventQueue] = {}

        # 回调
        self._on_display_change: OnDisplayChangeCallback | None = None
        self._focus_checker: FocusChecker | None = None

        # pane generation 跟踪
        self._pane_generations: dict[str, int] = {}

    # === 配置 ===

    def set_timer(self, timer: "Timer") -> None:
        """设置 Timer"""
        self._timer = timer
        for pane in self._panes.values():
            pane.set_timer(timer)

    def set_on_display_change(self, callback: OnDisplayChangeCallback) -> None:
        """设置显示变化回调"""
        self._on_display_change = callback

    def set_focus_checker(self, checker: FocusChecker) -> None:
        """设置 focus 检查函数"""
        self._focus_checker = checker
        for pane in self._panes.values():
            pane.set_focus_checker(checker)

    # === 实例管理 ===

    def get_or_create(self, pane_id: str) -> tuple[PaneStateMachine, Pane]:
        """获取或创建 pane 实例

        Args:
            pane_id: pane 标识

        Returns:
            (machine, pane) 元组
        """
        normalized_id = normalize_session_id(pane_id)

        if normalized_id not in self._machines:
            self._create_pane(normalized_id)

        return self._machines[normalized_id], self._panes[normalized_id]

    def _create_pane(self, pane_id: str) -> None:
        """创建新的 pane 实例"""
        # 初始化 generation
        self._pane_generations[pane_id] = 1

        # 创建状态机（不再设置回调，StateManager 直接调用）
        machine = PaneStateMachine(
            pane_id=pane_id,
            pane_generation=self._pane_generations[pane_id],
        )

        # 创建显示层
        pane = Pane(
            pane_id=pane_id,
            timer=self._timer,
            focus_checker=self._focus_checker,
        )

        # 绑定回调：Pane → 外部（保留，用于通知 HookManager/Web）
        pane.set_on_display_change(
            lambda state: self._on_pane_display_change(pane_id, state)
        )

        # 创建队列
        queue = EventQueue(pane_id)
        queue.set_current_generation(self._pane_generations[pane_id])

        self._machines[pane_id] = machine
        self._panes[pane_id] = pane
        self._queues[pane_id] = queue

        logger.debug(f"[StateManager] Created pane: {pane_id[:8]}")

    def _on_pane_display_change(self, pane_id: str, state: DisplayState) -> None:
        """Pane 显示变化回调"""
        if not self._on_display_change:
            return

        pane = self._panes.get(pane_id)
        if pane:
            suppressed, reason = pane.should_suppress_notification()
            self._on_display_change(pane_id, state, suppressed, reason)

    # === 事件处理 ===

    def enqueue(self, event: HookEvent) -> bool:
        """入队事件

        Args:
            event: Hook 事件

        Returns:
            是否入队成功
        """
        pane_id = normalize_session_id(event.pane_id)

        # 确保 pane 存在
        self.get_or_create(pane_id)

        # 补全 generation（如果缺失）
        if event.pane_generation == 0:
            event.pane_generation = self._pane_generations.get(pane_id, 1)

        # 入队
        queue = self._queues[pane_id]
        return queue.enqueue_event(event)

    async def process_queued(self, pane_id: str | None = None) -> int:
        """处理队列中的事件

        Args:
            pane_id: 指定 pane_id 只处理该 pane，None 处理所有

        Returns:
            处理的事件数
        """
        if pane_id:
            pane_ids = [normalize_session_id(pane_id)]
        else:
            pane_ids = list(self._queues.keys())

        total = 0
        for pid in pane_ids:
            queue = self._queues.get(pid)
            if not queue or queue.is_processing:
                continue

            queue.set_processing(True)
            try:
                while not queue.is_empty:
                    event = queue.dequeue()
                    if event:
                        await self._process_event(pid, event)
                        total += 1
            finally:
                queue.set_processing(False)

        return total

    async def _process_event(self, pane_id: str, event: HookEvent) -> bool:
        """处理单个事件

        Args:
            pane_id: pane 标识
            event: Hook 事件

        Returns:
            是否成功处理（发生了状态变化）
        """
        machine = self._machines.get(pane_id)
        pane = self._panes.get(pane_id)

        if not machine or not pane:
            return False

        pane_short = pane_id[:8]

        # content.changed 特殊处理
        if event.signal == "content.changed":
            # 1. 先更新 Pane 内容
            content = event.data.get("content", "")
            content_hash = event.data.get("content_hash", "")
            pane.update_content(content, content_hash)

            # 2. 如果是 WAITING_APPROVAL，尝试兜底恢复
            if machine.status == TaskStatus.WAITING_APPROVAL:
                logger.debug(f"[StateManager:{pane_short}] Content fallback: WAITING → RUNNING")
                change = machine.process(event)
                if change:
                    # 直接调用 Pane（不再依赖回调）
                    pane.handle_state_change(change)
                return change is not None

            return True

        # 其他事件转发给状态机
        change = machine.process(event)
        if change:
            # 直接调用 Pane（不再依赖回调）
            pane.handle_state_change(change)
        return change is not None

    # === LONG_RUNNING 检查 ===

    def tick_all(self) -> list[str]:
        """检查所有 pane 的 LONG_RUNNING

        由 Timer 周期调用。

        Returns:
            触发了 LONG_RUNNING 的 pane_id 列表
        """
        triggered = []

        for pane_id, machine in self._machines.items():
            if machine.should_check_long_running(LONG_RUNNING_THRESHOLD_SECONDS):
                # 构造 timer.check 事件
                duration = machine.get_running_duration()
                elapsed = self._format_duration(duration)

                event = HookEvent(
                    source="timer",
                    pane_id=pane_id,
                    event_type="check",
                    data={"elapsed": elapsed, "duration": duration},
                    pane_generation=machine.pane_generation,
                )

                change = machine.process(event)
                if change:
                    # 直接调用 Pane
                    pane = self._panes.get(pane_id)
                    if pane:
                        pane.handle_state_change(change)
                    triggered.append(pane_id)

        return triggered

    def _format_duration(self, seconds: float) -> str:
        """格式化时长"""
        if seconds < 60:
            return f"{int(seconds)}s"
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}m {secs}s"

    # === 状态查询 ===

    def get_status(self, pane_id: str) -> TaskStatus:
        """获取 pane 状态"""
        pane_id = normalize_session_id(pane_id)
        machine = self._machines.get(pane_id)
        return machine.status if machine else TaskStatus.IDLE

    def get_machine(self, pane_id: str) -> PaneStateMachine | None:
        """获取状态机"""
        return self._machines.get(normalize_session_id(pane_id))

    def get_pane(self, pane_id: str) -> Pane | None:
        """获取 Pane"""
        return self._panes.get(normalize_session_id(pane_id))

    def get_all_panes(self) -> set[str]:
        """获取所有 pane_id"""
        return set(self._panes.keys())

    def get_all_states(self) -> dict[str, dict]:
        """获取所有状态（用于 WebSocket）"""
        result = {}
        for pane_id, pane in self._panes.items():
            result[pane_id] = pane.get_display_dict()
        return result

    def get_generation(self, pane_id: str) -> int:
        """获取 pane generation"""
        return self._pane_generations.get(normalize_session_id(pane_id), 1)

    def increment_generation(self, pane_id: str) -> int:
        """递增 pane generation"""
        pane_id = normalize_session_id(pane_id)
        self._pane_generations[pane_id] = self._pane_generations.get(pane_id, 0) + 1

        machine = self._machines.get(pane_id)
        if machine is not None:
            machine.increment_generation()

        queue = self._queues.get(pane_id)
        if queue is not None:
            queue.set_current_generation(self._pane_generations[pane_id])

        return self._pane_generations[pane_id]

    # === 清理 ===

    def remove_pane(self, pane_id: str) -> None:
        """移除 pane"""
        pane_id = normalize_session_id(pane_id)

        self._machines.pop(pane_id, None)
        self._panes.pop(pane_id, None)
        self._queues.pop(pane_id, None)
        self._pane_generations.pop(pane_id, None)

        logger.debug(f"[StateManager] Removed pane: {pane_id[:8]}")

    def cleanup_closed_panes(self, active_pane_ids: set[str]) -> list[str]:
        """清理已关闭的 pane

        Args:
            active_pane_ids: 当前活跃的 pane_id 集合

        Returns:
            被清理的 pane_id 列表
        """
        normalized_active = {normalize_session_id(pid) for pid in active_pane_ids}
        current_panes = set(self._panes.keys())

        closed = current_panes - normalized_active
        for pane_id in closed:
            self.remove_pane(pane_id)

        return list(closed)

    # === 持久化 ===

    def save(self) -> bool:
        """保存状态"""
        machines = {pid: m.to_dict() for pid, m in self._machines.items()}
        panes = {pid: p.to_dict() for pid, p in self._panes.items()}
        return persistence.save(machines, panes)

    def load(self) -> bool:
        """加载状态"""
        result = persistence.load()
        if result is None:
            return False

        machines_data, panes_data = result

        # 恢复状态机（不再设置回调，StateManager 直接调用）
        for pane_id, data in machines_data.items():
            machine = PaneStateMachine.from_dict(data)
            self._machines[pane_id] = machine
            self._pane_generations[pane_id] = machine.pane_generation

        # 恢复 Pane
        for pane_id, data in panes_data.items():
            pane = Pane.from_dict(data, self._timer, self._focus_checker)
            self._panes[pane_id] = pane

            # 重新绑定回调
            pane.set_on_display_change(
                lambda state, pid=pane_id: self._on_pane_display_change(pid, state)
            )

        # 创建队列
        for pane_id in self._machines.keys():
            if pane_id not in self._queues:
                queue = EventQueue(pane_id)
                queue.set_current_generation(self._pane_generations.get(pane_id, 1))
                self._queues[pane_id] = queue

        logger.info(
            f"[StateManager] Loaded {len(self._machines)} machines, {len(self._panes)} panes"
        )
        return True
