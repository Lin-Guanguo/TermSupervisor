"""StateManager - 状态管理器

协调 PaneStateMachine 与 Pane：
- 创建/管理实例
- 绑定回调
- 处理事件（通过 actor 队列串行化）
- 轮询 LONG_RUNNING
- 清理过期 pane
"""

from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING, Any

from ..config import LONG_RUNNING_THRESHOLD_SECONDS
from ..core.ids import normalize_id
from ..telemetry import get_logger, metrics
from .pane import Pane
from .queue import EventQueue
from .state_machine import PaneStateMachine
from .types import DisplayState, HookEvent, TaskStatus

if TYPE_CHECKING:
    from ..timer import Timer

logger = get_logger(__name__)

# 回调类型
OnDisplayChangeCallback = Callable[[str, DisplayState, bool, str], Any]
OnDebugEventCallback = Callable[[dict], Any]
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
        self._on_debug_event: OnDebugEventCallback | None = None
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

    def set_on_debug_event(self, callback: OnDebugEventCallback) -> None:
        """设置调试事件回调

        Args:
            callback: 回调函数 (event_dict) -> None
                event_dict 包含: pane_id, signal, result, reason, state_id,
                以及队列统计: queue_depth, queue_low_priority_drops, queue_overflow_drops
        """
        self._on_debug_event = callback
        # 同步到已有的队列
        for queue in self._queues.values():
            queue.set_on_debug_event(callback)

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
        normalized_id = normalize_id(pane_id)

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
        pane.set_on_display_change(lambda state: self._on_pane_display_change(pane_id, state))

        # 创建队列
        queue = EventQueue(pane_id)
        queue.set_current_generation(self._pane_generations[pane_id])
        queue.set_current_state_id(machine.state_id)
        # 绑定队列调试回调
        if self._on_debug_event:
            queue.set_on_debug_event(self._on_debug_event)

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

    def _emit_debug_event(
        self,
        pane_id: str,
        signal: str,
        result: str,
        reason: str = "",
        state_id: int = 0,
    ) -> None:
        """发送调试事件

        Args:
            pane_id: pane 标识
            signal: 事件信号
            result: 结果 ("ok" or "fail")
            reason: 失败原因（可选）
            state_id: 当前 state_id
        """
        if not self._on_debug_event:
            return

        # 获取队列统计
        queue = self._queues.get(pane_id)
        queue_depth = 0
        queue_low_priority_drops = 0
        queue_overflow_drops = 0
        if queue:
            queue_depth = queue.depth
            queue_low_priority_drops = queue.low_priority_drops
            queue_overflow_drops = queue.overflow_drops

        self._on_debug_event(
            {
                "pane_id": pane_id,
                "signal": signal,
                "result": result,
                "reason": reason,
                "state_id": state_id,
                "queue_depth": queue_depth,
                "queue_low_priority_drops": queue_low_priority_drops,
                "queue_overflow_drops": queue_overflow_drops,
            }
        )

    # === 事件处理 ===

    def enqueue(self, event: HookEvent) -> bool:
        """入队事件

        Args:
            event: Hook 事件

        Returns:
            是否入队成功
        """
        pane_id = normalize_id(event.pane_id)

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
            pane_ids = [normalize_id(pane_id)]
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

        # content.changed / content.update: 仅更新 Pane 内容，不触发状态转换
        # 这是 Render Pipeline 的一部分，与 Event System 独立
        if event.signal in ("content.changed", "content.update"):
            content = event.data.get("content", "")
            content_hash = event.data.get("content_hash", "")
            pane.update_content(content, content_hash)
            # 内容事件不触发调试事件（太频繁）
            return True

        # 其他事件转发给状态机（Event System）
        change = machine.process(event)

        if change:
            pane.handle_state_change(change)

            # 更新队列的 state_id
            queue = self._queues.get(pane_id)
            if queue:
                queue.set_current_state_id(machine.state_id)

            # 发送调试事件
            self._emit_debug_event(pane_id, event.signal, "ok", state_id=machine.state_id)
        else:
            # 获取失败原因
            reason = self._get_last_fail_reason(machine)
            self._emit_debug_event(
                pane_id, event.signal, "fail", reason=reason, state_id=machine.state_id
            )

        return change is not None

    def _get_last_fail_reason(self, machine: PaneStateMachine) -> str:
        """从状态机历史获取最后一次失败原因"""
        history = machine.history
        if history:
            last_entry = history[-1]
            if not last_entry.success:
                return last_entry.description
        return ""

    # === LONG_RUNNING 检查 ===

    def tick_all(self) -> list[str]:
        """检查所有 pane 的 LONG_RUNNING 和 WAITING fallback

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
                    # 更新队列的 state_id
                    queue = self._queues.get(pane_id)
                    if queue:
                        queue.set_current_state_id(machine.state_id)
                    # 发送调试事件
                    self._emit_debug_event(pane_id, event.signal, "ok", state_id=machine.state_id)

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
        pane_id = normalize_id(pane_id)
        machine = self._machines.get(pane_id)
        return machine.status if machine else TaskStatus.IDLE

    def get_machine(self, pane_id: str) -> PaneStateMachine | None:
        """获取状态机"""
        return self._machines.get(normalize_id(pane_id))

    def get_pane(self, pane_id: str) -> Pane | None:
        """获取 Pane"""
        return self._panes.get(normalize_id(pane_id))

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
        return self._pane_generations.get(normalize_id(pane_id), 1)

    def increment_generation(self, pane_id: str) -> int:
        """递增 pane generation"""
        pane_id = normalize_id(pane_id)
        self._pane_generations[pane_id] = self._pane_generations.get(pane_id, 0) + 1

        machine = self._machines.get(pane_id)
        if machine is not None:
            machine.increment_generation()

        queue = self._queues.get(pane_id)
        if queue is not None:
            queue.set_current_generation(self._pane_generations[pane_id])

        return self._pane_generations[pane_id]

    def get_debug_snapshot(
        self,
        pane_id: str,
        *,
        max_history: int | None = None,
        max_pending_events: int = 10,
    ) -> dict | None:
        """获取指定 pane 的调试快照"""
        pane_id = normalize_id(pane_id)
        machine = self._machines.get(pane_id)
        pane = self._panes.get(pane_id)
        queue = self._queues.get(pane_id)

        # 注意：用 is None 而不是 not，因为 EventQueue.__bool__ 在队列为空时返回 False
        if machine is None or pane is None or queue is None:
            return None

        history_entries = machine.history
        if max_history is not None:
            history_entries = history_entries[-max_history:]

        return {
            "pane_id": pane_id,
            "machine": {
                "status": machine.status.value,
                "source": machine.source,
                "started_at": machine.started_at,
                "state_id": machine.state_id,
                "pane_generation": machine.pane_generation,
                "description": machine.description,
            },
            "display": pane.get_display_dict(),
            "queue": queue.debug_snapshot(max_pending=max_pending_events),
            "history": [entry.to_dict() for entry in history_entries],
            "content_hash": pane.content_hash,
        }

    def get_all_debug_snapshots(
        self,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        """获取所有 pane 的调试快照列表

        Args:
            limit: 最大返回数量
            offset: 起始偏移量

        Returns:
            (snapshots, total) 元组：
            - snapshots: 调试快照列表，每个包含 pane_id, status, source, state_id,
              description, running_duration, queue stats, latest_history
            - total: 总 pane 数（分页前）
        """
        snapshots = []
        all_pane_ids = sorted(self._panes.keys())
        total = len(all_pane_ids)

        # 应用分页
        pane_ids = all_pane_ids
        if offset > 0:
            pane_ids = pane_ids[offset:]
        if limit is not None and limit > 0:
            pane_ids = pane_ids[:limit]

        for pane_id in pane_ids:
            machine = self._machines.get(pane_id)
            pane = self._panes.get(pane_id)
            queue = self._queues.get(pane_id)

            # 注意：用 is None 而不是 not，因为 EventQueue.__bool__ 在队列为空时返回 False
            if machine is None or pane is None or queue is None:
                continue

            display = pane.get_display_dict()
            queue_info = queue.debug_snapshot(max_pending=0)
            history = machine.history

            # 获取最近一条历史
            latest_history = None
            if history:
                entry = history[-1]
                latest_history = entry.to_dict()

            snapshots.append(
                {
                    "pane_id": pane_id,
                    "status": machine.status.value,
                    "source": machine.source,
                    "state_id": machine.state_id,
                    "description": machine.description,
                    "running_duration": display.get("running_duration", 0.0),
                    "queue_depth": queue_info.get("depth", 0),
                    "queue_low_priority_drops": queue_info.get("low_priority_drops", 0),
                    "queue_overflow_drops": queue_info.get("overflow_drops", 0),
                    "latest_history": latest_history,
                }
            )

        return snapshots, total

    # === 清理 ===

    def remove_pane(self, pane_id: str) -> None:
        """移除 pane"""
        pane_id = normalize_id(pane_id)

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
        normalized_active = {normalize_id(pid) for pid in active_pane_ids}
        current_panes = set(self._panes.keys())

        closed = current_panes - normalized_active
        for pane_id in closed:
            self.remove_pane(pane_id)

        return list(closed)
