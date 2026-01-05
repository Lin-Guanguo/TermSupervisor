"""StateManager - 状态管理器

职责：
- 创建/管理 PaneStateMachine 实例
- 处理事件（通过 actor 队列串行化）
- 管理显示状态（延迟显示、auto-dismiss、recently_finished）
- 轮询 LONG_RUNNING
- 清理过期 pane
"""

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from ..config import (
    AUTO_DISMISS_DWELL_SECONDS,
    LONG_RUNNING_THRESHOLD_SECONDS,
    QUIET_COMPLETION_THRESHOLD_SECONDS,
    RECENTLY_FINISHED_HINT_SECONDS,
)
from ..core.ids import normalize_id
from ..telemetry import get_logger, metrics
from .queue import EventQueue
from .state_machine import PaneStateMachine
from .types import DisplayState, DisplayUpdate, HookEvent, StateChange, TaskStatus

if TYPE_CHECKING:
    from ..timer import Timer

logger = get_logger(__name__)

# 回调类型
OnDisplayChangeCallback = Callable[[str, DisplayState], Any]
OnDebugEventCallback = Callable[[dict], Any]


class StateManager:
    """状态管理器

    统一管理状态机和显示逻辑。

    Attributes:
        timer: Timer 实例
        machines: 状态机字典 {pane_id: PaneStateMachine}
        queues: 事件队列字典 {pane_id: EventQueue}
    """

    def __init__(self, timer: "Timer | None" = None):
        """初始化

        Args:
            timer: Timer 实例
        """
        self._timer = timer
        self._machines: dict[str, PaneStateMachine] = {}
        self._queues: dict[str, EventQueue] = {}

        # 显示状态存储
        self._display_states: dict[str, DisplayState] = {}
        self._content: dict[str, str] = {}
        self._content_hash: dict[str, str] = {}

        # 回调
        self._on_display_change: OnDisplayChangeCallback | None = None
        self._on_debug_event: OnDebugEventCallback | None = None

        # pane generation 跟踪
        self._pane_generations: dict[str, int] = {}

    # === 配置 ===

    def set_timer(self, timer: "Timer") -> None:
        """设置 Timer"""
        self._timer = timer

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

    # === 实例管理 ===

    def get_or_create(self, pane_id: str) -> tuple[PaneStateMachine, DisplayState]:
        """获取或创建 pane 实例

        Args:
            pane_id: pane 标识

        Returns:
            (machine, display_state) 元组
        """
        normalized_id = normalize_id(pane_id)

        if normalized_id not in self._machines:
            self._create_pane(normalized_id)

        return self._machines[normalized_id], self._display_states[normalized_id]

    def _create_pane(self, pane_id: str) -> None:
        """创建新的 pane 实例"""
        # 初始化 generation
        self._pane_generations[pane_id] = 1

        # 创建状态机
        machine = PaneStateMachine(
            pane_id=pane_id,
            pane_generation=self._pane_generations[pane_id],
        )

        # 初始化显示状态
        self._display_states[pane_id] = DisplayState(
            status=TaskStatus.IDLE,
            source="shell",
            description="",
            state_id=0,
        )
        self._content[pane_id] = ""
        self._content_hash[pane_id] = ""

        # 创建队列
        queue = EventQueue(pane_id)
        queue.set_current_generation(self._pane_generations[pane_id])
        queue.set_current_state_id(machine.state_id)
        if self._on_debug_event:
            queue.set_on_debug_event(self._on_debug_event)

        self._machines[pane_id] = machine
        self._queues[pane_id] = queue

        logger.debug(f"[StateManager] Created pane: {pane_id[:8]}")

    def _notify_display_change(self, pane_id: str, state: DisplayState) -> None:
        """通知显示变化"""
        if not self._on_display_change:
            return

        self._on_display_change(pane_id, state)

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

    async def process_queued(
        self, pane_id: str | None = None
    ) -> tuple[int, list[DisplayUpdate]]:
        """处理队列中的事件

        Args:
            pane_id: 指定 pane_id 只处理该 pane，None 处理所有

        Returns:
            (count, updates) 元组：
            - count: 处理的事件数
            - updates: DisplayUpdate 列表（仅状态变化事件，不含 content 事件）
        """
        if pane_id:
            pane_ids = [normalize_id(pane_id)]
        else:
            pane_ids = list(self._queues.keys())

        total = 0
        updates: list[DisplayUpdate] = []

        for pid in pane_ids:
            queue = self._queues.get(pid)
            if not queue or queue.is_processing:
                continue

            queue.set_processing(True)
            try:
                while not queue.is_empty:
                    event = queue.dequeue()
                    if event:
                        update = await self._process_event(pid, event)
                        total += 1
                        if update:
                            updates.append(update)
            finally:
                queue.set_processing(False)

        return total, updates

    async def _process_event(self, pane_id: str, event: HookEvent) -> DisplayUpdate | None:
        """处理单个事件

        Args:
            pane_id: pane 标识
            event: Hook 事件

        Returns:
            DisplayUpdate 如果发生状态变化，None 如果无变化或是 content 事件
        """
        machine = self._machines.get(pane_id)
        if not machine:
            return None

        # content.changed / content.update: 仅更新内容，不触发状态转换
        # 这是 Render Pipeline 的一部分，与 Event System 独立
        if event.signal in ("content.changed", "content.update"):
            content = event.data.get("content", "")
            content_hash = event.data.get("content_hash", "")
            self._content[pane_id] = content
            self._content_hash[pane_id] = content_hash
            if pane_id in self._display_states:
                self._display_states[pane_id].content_hash = content_hash
            return None

        # 其他事件转发给状态机（Event System）
        change = machine.process(event)

        if change:
            # 更新显示状态
            display_state = self._update_display_state(pane_id, change)

            # 更新队列的 state_id
            queue = self._queues.get(pane_id)
            if queue:
                queue.set_current_state_id(machine.state_id)

            # 发送调试事件
            self._emit_debug_event(pane_id, event.signal, "ok", state_id=machine.state_id)

            # 注册 auto-dismiss 定时器（DONE/FAILED 自动消失）
            if change.new_status in {TaskStatus.DONE, TaskStatus.FAILED}:
                self._register_auto_dismiss(pane_id, change.state_id)

            return DisplayUpdate(
                pane_id=pane_id,
                display_state=display_state,
                reason="state_change",
            )
        else:
            # 获取失败原因
            reason = self._get_last_fail_reason(machine)
            self._emit_debug_event(
                pane_id, event.signal, "fail", reason=reason, state_id=machine.state_id
            )
            return None

    def _update_display_state(self, pane_id: str, change: StateChange) -> DisplayState:
        """更新显示状态 (Phase 3.4)

        Args:
            pane_id: pane 标识
            change: 状态变化

        Returns:
            更新后的 DisplayState
        """
        # 计算 quiet_completion（短任务不闪烁）
        quiet_completion = False
        if change.new_status in {TaskStatus.DONE, TaskStatus.FAILED}:
            if change.running_duration < QUIET_COMPLETION_THRESHOLD_SECONDS:
                quiet_completion = True

        display_state = DisplayState(
            status=change.new_status,
            source=change.new_source,
            description=change.description,
            state_id=change.state_id,
            started_at=change.started_at,
            running_duration=change.running_duration,
            content_hash=self._content_hash.get(pane_id, ""),
            recently_finished=False,
            quiet_completion=quiet_completion,
        )
        self._display_states[pane_id] = display_state
        return display_state

    def _get_last_fail_reason(self, machine: PaneStateMachine) -> str:
        """从状态机历史获取最后一次失败原因"""
        history = machine.history
        if history:
            last_entry = history[-1]
            if not last_entry.success:
                return last_entry.description
        return ""

    # === Timer 任务管理 ===

    def _get_timer_task_name(self, pane_id: str, task_type: str) -> str:
        """获取 Timer 任务名"""
        return f"pane_{task_type}_{pane_id[:8]}"

    def _register_auto_dismiss(self, pane_id: str, state_id: int) -> None:
        """注册 auto-dismiss 定时器

        DONE/FAILED 状态在 dwell 时间后自动消失。
        """
        if not self._timer:
            return

        pane_short = pane_id[:8]
        task_name = self._get_timer_task_name(pane_id, "auto_dismiss")

        # 取消旧的 auto-dismiss 任务
        if self._timer.has_delay(task_name):
            self._timer.cancel_delay(task_name)

        def auto_dismiss():
            display_state = self._display_states.get(pane_id)
            if not display_state:
                return

            # 检查 state_id 是否仍然匹配
            if display_state.state_id != state_id:
                logger.debug(
                    f"[StateManager:{pane_short}] Auto-dismiss skipped: "
                    f"state_id changed ({display_state.state_id} != {state_id})"
                )
                return

            # 检查状态是否仍为 DONE/FAILED
            if display_state.status not in {TaskStatus.DONE, TaskStatus.FAILED}:
                return

            old_status = display_state.status

            # 设置 recently_finished 提示并转到 IDLE
            display_state.recently_finished = True
            display_state.status = TaskStatus.IDLE

            logger.info(
                f"[StateManager:{pane_short}] Auto-dismiss: {old_status.value} → IDLE "
                f"(dwell={AUTO_DISMISS_DWELL_SECONDS}s)"
            )
            metrics.inc("pane.auto_dismiss", {"pane": pane_short})

            # 通知显示变化
            self._notify_display_change(pane_id, display_state)

            # 注册 recently_finished 提示清除
            self._register_recently_finished_clear(pane_id, state_id)

        self._timer.register_delay(task_name, AUTO_DISMISS_DWELL_SECONDS, auto_dismiss)
        logger.debug(f"[StateManager:{pane_short}] Auto-dismiss scheduled in {AUTO_DISMISS_DWELL_SECONDS}s")

    def _register_recently_finished_clear(self, pane_id: str, state_id: int) -> None:
        """注册 recently_finished 提示清除定时器"""
        if not self._timer:
            return

        pane_short = pane_id[:8]
        task_name = self._get_timer_task_name(pane_id, "recently_finished")

        def clear_hint():
            display_state = self._display_states.get(pane_id)
            if not display_state:
                return

            # 只在 state_id 未变化时清除
            if display_state.state_id != state_id:
                return
            if not display_state.recently_finished:
                return

            display_state.recently_finished = False
            logger.debug(f"[StateManager:{pane_short}] Cleared recently_finished hint")

            self._notify_display_change(pane_id, display_state)

        self._timer.register_delay(task_name, RECENTLY_FINISHED_HINT_SECONDS, clear_hint)

    def _cancel_pane_timer_tasks(self, pane_id: str) -> None:
        """取消 pane 的所有 Timer 任务"""
        if not self._timer:
            return

        for task_type in ("auto_dismiss", "recently_finished"):
            task_name = self._get_timer_task_name(pane_id, task_type)
            if self._timer.has_delay(task_name):
                self._timer.cancel_delay(task_name)

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
                    # 更新显示状态
                    self._update_display_state(pane_id, change)
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

    def get_content(self, pane_id: str) -> str:
        """获取 pane 内容"""
        return self._content.get(normalize_id(pane_id), "")

    def get_content_hash(self, pane_id: str) -> str:
        """获取 pane 内容 hash"""
        return self._content_hash.get(normalize_id(pane_id), "")

    def get_display_state(self, pane_id: str) -> DisplayState | None:
        """获取显示状态"""
        return self._display_states.get(normalize_id(pane_id))

    def get_all_panes(self) -> set[str]:
        """获取所有 pane_id"""
        return set(self._machines.keys())

    def get_all_states(self) -> dict[str, dict]:
        """获取所有状态（用于 WebSocket）"""
        result = {}
        for pane_id, display_state in self._display_states.items():
            result[pane_id] = display_state.to_dict()
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
        display_state = self._display_states.get(pane_id)
        queue = self._queues.get(pane_id)

        # 注意：用 is None 而不是 not，因为 EventQueue.__bool__ 在队列为空时返回 False
        if machine is None or display_state is None or queue is None:
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
            "display": display_state.to_dict(),
            "queue": queue.debug_snapshot(max_pending=max_pending_events),
            "history": [entry.to_dict() for entry in history_entries],
            "content_hash": self._content_hash.get(pane_id, ""),
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
        all_pane_ids = sorted(self._machines.keys())
        total = len(all_pane_ids)

        # 应用分页
        pane_ids = all_pane_ids
        if offset > 0:
            pane_ids = pane_ids[offset:]
        if limit is not None and limit > 0:
            pane_ids = pane_ids[:limit]

        for pane_id in pane_ids:
            machine = self._machines.get(pane_id)
            display_state = self._display_states.get(pane_id)
            queue = self._queues.get(pane_id)

            # 注意：用 is None 而不是 not，因为 EventQueue.__bool__ 在队列为空时返回 False
            if machine is None or display_state is None or queue is None:
                continue

            display = display_state.to_dict()
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

        # 取消 Timer 任务
        self._cancel_pane_timer_tasks(pane_id)

        self._machines.pop(pane_id, None)
        self._queues.pop(pane_id, None)
        self._pane_generations.pop(pane_id, None)
        self._display_states.pop(pane_id, None)
        self._content.pop(pane_id, None)
        self._content_hash.pop(pane_id, None)

        logger.debug(f"[StateManager] Removed pane: {pane_id[:8]}")

    def cleanup_closed_panes(self, active_pane_ids: set[str]) -> list[str]:
        """清理已关闭的 pane

        Args:
            active_pane_ids: 当前活跃的 pane_id 集合

        Returns:
            被清理的 pane_id 列表
        """
        normalized_active = {normalize_id(pid) for pid in active_pane_ids}
        current_panes = set(self._machines.keys())

        closed = current_panes - normalized_active
        for pane_id in closed:
            self.remove_pane(pane_id)

        return list(closed)
