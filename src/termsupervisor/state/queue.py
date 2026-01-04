"""ActorQueue - 每 pane 的事件队列

实现 Actor 模式，保证事件串行处理。

特性：
- 最大容量 256
- 高水位 75% 打印日志
- 溢出时丢弃最旧事件
- 丢弃时记录 queue.dropped 指标
"""

from collections import deque
from collections.abc import Callable
from typing import Any

from ..config import (
    LOW_PRIORITY_SIGNALS,
    METRICS_ENABLED,
    PROTECTED_SIGNALS,
    QUEUE_HIGH_WATERMARK,
    QUEUE_LOW_PRIORITY_DROP_WATERMARK,
    QUEUE_MAX_SIZE,
)
from ..telemetry import get_logger, metrics
from .types import HookEvent

logger = get_logger(__name__)

# 调试事件回调类型
OnQueueDebugEventCallback = Callable[[dict], Any]


class ActorQueue[T]:
    """Actor 队列

    每个 pane 一个队列，保证事件按顺序串行处理。

    Attributes:
        pane_id: pane 标识
        max_size: 最大容量
        high_watermark: 高水位阈值（0-1）
    """

    def __init__(
        self,
        pane_id: str,
        max_size: int = QUEUE_MAX_SIZE,
        high_watermark: float = QUEUE_HIGH_WATERMARK,
    ):
        self.pane_id = pane_id
        self._max_size = max_size
        self._high_watermark = high_watermark
        self._queue: deque[T] = deque(maxlen=max_size)
        self._processing = False

    def enqueue(self, item: T) -> bool:
        """入队

        如果队列满，丢弃最旧的事件。

        Args:
            item: 要入队的项

        Returns:
            是否成功入队（总是 True，但可能丢弃了旧事件）
        """
        pane_short = self.pane_id[:8]

        # 检查是否需要丢弃
        if len(self._queue) >= self._max_size:
            self._queue.popleft()
            logger.warning(f"[Queue:{pane_short}] Dropped oldest event (queue full)")
            if METRICS_ENABLED:
                metrics.inc("queue.dropped", {"pane": pane_short})

        self._queue.append(item)

        # 更新 depth 指标
        depth = len(self._queue)
        if METRICS_ENABLED:
            metrics.gauge("queue.depth", depth, {"pane": pane_short})

        # 高水位告警
        if depth >= self._max_size * self._high_watermark:
            logger.debug(
                f"[Queue:{pane_short}] High watermark: {depth}/{self._max_size} "
                f"({depth / self._max_size * 100:.0f}%)"
            )

        return True

    def dequeue(self) -> T | None:
        """出队

        Returns:
            队首项，队列空时返回 None
        """
        if not self._queue:
            return None

        item = self._queue.popleft()

        # 更新 depth 指标
        if METRICS_ENABLED:
            pane_short = self.pane_id[:8]
            metrics.gauge("queue.depth", len(self._queue), {"pane": pane_short})

        return item

    def peek(self) -> T | None:
        """查看队首（不移除）

        Returns:
            队首项，队列空时返回 None
        """
        if not self._queue:
            return None
        return self._queue[0]

    def clear(self) -> int:
        """清空队列

        Returns:
            清除的项数
        """
        count = len(self._queue)
        self._queue.clear()

        if METRICS_ENABLED:
            pane_short = self.pane_id[:8]
            metrics.gauge("queue.depth", 0, {"pane": pane_short})

        return count

    # === 状态 ===

    def __len__(self) -> int:
        return len(self._queue)

    def __bool__(self) -> bool:
        return len(self._queue) > 0

    @property
    def is_empty(self) -> bool:
        return len(self._queue) == 0

    @property
    def is_full(self) -> bool:
        return len(self._queue) >= self._max_size

    @property
    def depth(self) -> int:
        return len(self._queue)

    @property
    def is_processing(self) -> bool:
        """是否正在处理"""
        return self._processing

    def set_processing(self, value: bool) -> None:
        """设置处理状态"""
        self._processing = value


class EventQueue(ActorQueue[HookEvent]):
    """HookEvent 专用队列

    继承 ActorQueue，添加事件过滤功能。

    队列策略：
    - 低优先级事件（content.changed/content.update）在高水位时被丢弃
    - 受保护事件（command_end, Stop）永不丢弃
    - 超出容量时丢弃最旧的非保护事件
    """

    def __init__(self, pane_id: str, max_size: int = QUEUE_MAX_SIZE):
        super().__init__(pane_id, max_size)
        self._current_generation: int = 1
        self._current_state_id: int = 0
        # 丢弃计数器
        self._low_priority_drops: int = 0
        self._overflow_drops: int = 0
        # 调试事件回调
        self._on_debug_event: OnQueueDebugEventCallback | None = None

    def set_on_debug_event(self, callback: OnQueueDebugEventCallback | None) -> None:
        """设置调试事件回调"""
        self._on_debug_event = callback

    def _emit_debug_event(
        self,
        signal: str,
        reason: str,
    ) -> None:
        """发送队列调试事件

        Args:
            signal: 被丢弃/合并的信号
            reason: 原因 (e.g., "drop_low_priority", "drop_overflow", "merge_content")
        """
        if not self._on_debug_event:
            return

        self._on_debug_event(
            {
                "pane_id": self.pane_id,
                "signal": signal,
                "result": "ok",  # Normalized to match contract
                "reason": reason,
                "state_id": self._current_state_id,
                "queue_depth": len(self._queue),
                "queue_low_priority_drops": self._low_priority_drops,
                "queue_overflow_drops": self._overflow_drops,
            }
        )

    def set_current_generation(self, generation: int) -> None:
        """设置当前 generation"""
        self._current_generation = generation

    def set_current_state_id(self, state_id: int) -> None:
        """设置当前 state_id"""
        self._current_state_id = state_id

    @property
    def low_priority_drops(self) -> int:
        """低优先级丢弃计数"""
        return self._low_priority_drops

    @property
    def overflow_drops(self) -> int:
        """溢出丢弃计数"""
        return self._overflow_drops

    def enqueue_event(self, event: HookEvent) -> bool:
        """入队事件（带过期检查 + 优先级策略）

        Args:
            event: Hook 事件

        Returns:
            是否入队成功（过期或被丢弃的事件返回 False）
        """
        pane_short = self.pane_id[:8]

        # 检查 generation
        if event.pane_generation < self._current_generation:
            logger.debug(
                f"[Queue:{pane_short}] Dropped stale event: "
                f"generation {event.pane_generation} < {self._current_generation}"
            )
            if METRICS_ENABLED:
                metrics.inc("queue.stale_dropped", {"pane": pane_short})
            # 发送调试事件
            self._emit_debug_event(event.signal, "drop_stale_generation")
            return False

        # 优先级策略：低优先级事件在高水位时被丢弃
        if self._should_drop_low_priority(event):
            logger.debug(
                f"[Queue:{pane_short}] Dropped low-priority event: {event.signal} "
                f"(depth={len(self._queue)}/{self._max_size})"
            )
            self._low_priority_drops += 1
            if METRICS_ENABLED:
                metrics.inc("queue.low_priority_dropped", {"pane": pane_short})
            # 发送调试事件
            self._emit_debug_event(event.signal, "drop_low_priority_watermark")
            return False

        # 队列满时，使用保护策略丢弃
        if len(self._queue) >= self._max_size:
            dropped = self._drop_for_overflow()
            if dropped is None:
                # 无法丢弃任何事件（全是保护事件），拒绝新事件
                logger.warning(
                    f"[Queue:{pane_short}] Queue full with protected events, "
                    f"rejecting new event: {event.signal}"
                )
                if METRICS_ENABLED:
                    metrics.inc("queue.overflow_rejected", {"pane": pane_short})
                return False

        # 直接添加到队列（绕过 ActorQueue.enqueue 的无保护丢弃）
        self._queue.append(event)

        # 更新 depth 指标
        depth = len(self._queue)
        if METRICS_ENABLED:
            metrics.gauge("queue.depth", depth, {"pane": pane_short})

        # 高水位告警
        if depth >= self._max_size * self._high_watermark:
            logger.debug(
                f"[Queue:{pane_short}] High watermark: {depth}/{self._max_size} "
                f"({depth / self._max_size * 100:.0f}%)"
            )

        return True

    def _drop_for_overflow(self) -> HookEvent | None:
        """溢出时丢弃事件（优先丢弃非保护事件）

        策略：
        1. 优先丢弃最旧的低优先级事件
        2. 其次丢弃最旧的普通事件
        3. 永不丢弃保护事件

        Returns:
            被丢弃的事件，如果全是保护事件则返回 None
        """
        pane_short = self.pane_id[:8]

        # 第一轮：找最旧的低优先级事件
        for i, evt in enumerate(self._queue):
            if evt.signal in LOW_PRIORITY_SIGNALS:
                dropped = self._queue[i]
                del self._queue[i]
                self._overflow_drops += 1
                logger.debug(
                    f"[Queue:{pane_short}] Overflow: dropped low-priority {dropped.signal}"
                )
                if METRICS_ENABLED:
                    metrics.inc("queue.overflow_low_priority", {"pane": pane_short})
                # 发送调试事件
                self._emit_debug_event(dropped.signal, "drop_overflow_low_priority")
                return dropped

        # 第二轮：找最旧的非保护事件
        for i, evt in enumerate(self._queue):
            if evt.signal not in PROTECTED_SIGNALS:
                dropped = self._queue[i]
                del self._queue[i]
                self._overflow_drops += 1
                logger.debug(f"[Queue:{pane_short}] Overflow: dropped normal {dropped.signal}")
                if METRICS_ENABLED:
                    metrics.inc("queue.overflow_normal", {"pane": pane_short})
                # 发送调试事件
                self._emit_debug_event(dropped.signal, "drop_overflow_normal")
                return dropped

        # 全是保护事件，无法丢弃
        return None

    def _should_drop_low_priority(self, event: HookEvent) -> bool:
        """判断是否应丢弃低优先级事件

        策略：
        - 受保护信号永不丢弃
        - 低优先级信号在超过水位时丢弃
        """
        # 受保护信号永不丢弃
        if event.signal in PROTECTED_SIGNALS:
            return False

        # 低优先级信号在高水位时丢弃
        if event.signal in LOW_PRIORITY_SIGNALS:
            watermark = self._max_size * QUEUE_LOW_PRIORITY_DROP_WATERMARK
            return len(self._queue) >= watermark

        return False

    def merge_content_events(self) -> int:
        """合并队列中的连续 content 事件（可选优化）

        保留最新的 content.changed/update 事件，丢弃旧的。

        Returns:
            合并的事件数
        """
        if len(self._queue) < 2:
            return 0

        merged = 0
        new_queue: deque[HookEvent] = deque(maxlen=self._max_size)
        last_content_event: HookEvent | None = None

        for event in self._queue:
            if event.signal in LOW_PRIORITY_SIGNALS:
                # 只保留最新的 content 事件
                if last_content_event is not None:
                    merged += 1
                last_content_event = event
            else:
                # 非 content 事件：先入队之前的 content，再入队当前
                if last_content_event is not None:
                    new_queue.append(last_content_event)
                    last_content_event = None
                new_queue.append(event)

        # 入队最后一个 content 事件
        if last_content_event is not None:
            new_queue.append(last_content_event)

        self._queue = new_queue

        if merged > 0:
            if METRICS_ENABLED:
                pane_short = self.pane_id[:8]
                metrics.inc("queue.content_merged", {"pane": pane_short}, merged)
                logger.debug(f"[Queue:{pane_short}] Merged {merged} content events")
            # 发送调试事件
            self._emit_debug_event("content.update", f"merge_content_{merged}_events")

        return merged

    def debug_snapshot(self, max_pending: int = 10) -> dict:
        """获取调试快照"""
        pending_events = list(self._queue)[:max_pending]
        return {
            "depth": len(self._queue),
            "max_size": self._max_size,
            "is_processing": self._processing,
            "current_generation": self._current_generation,
            "low_priority_drops": self._low_priority_drops,
            "overflow_drops": self._overflow_drops,
            "pending": [
                {
                    "signal": evt.signal,
                    "source": evt.source,
                    "generation": evt.pane_generation,
                    "timestamp": evt.timestamp,
                }
                for evt in pending_events
            ],
        }
