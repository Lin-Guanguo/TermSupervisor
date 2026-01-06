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
    METRICS_ENABLED,
    PROTECTED_SIGNALS,
    QUEUE_HIGH_WATERMARK,
    QUEUE_MAX_SIZE,
)
from ..core.ids import short_id
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
        pane_short = short_id(self.pane_id)

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
            pane_short = short_id(self.pane_id)
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
            pane_short = short_id(self.pane_id)
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
    - 受保护事件（command_end, Stop）永不丢弃
    - 超出容量时丢弃最旧的非保护事件
    """

    def __init__(self, pane_id: str, max_size: int = QUEUE_MAX_SIZE):
        super().__init__(pane_id, max_size)
        self._current_generation: int = 1
        self._current_state_id: int = 0
        # 丢弃计数器
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
    def overflow_drops(self) -> int:
        """溢出丢弃计数"""
        return self._overflow_drops

    def enqueue_event(self, event: HookEvent) -> bool:
        """入队事件（带过期检查）

        Args:
            event: Hook 事件

        Returns:
            是否入队成功（过期或被丢弃的事件返回 False）
        """
        pane_short = short_id(self.pane_id)

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
        - 丢弃最旧的非保护事件
        - 永不丢弃保护事件

        Returns:
            被丢弃的事件，如果全是保护事件则返回 None
        """
        pane_short = short_id(self.pane_id)

        # 找最旧的非保护事件
        for i, evt in enumerate(self._queue):
            if evt.signal not in PROTECTED_SIGNALS:
                dropped = self._queue[i]
                del self._queue[i]
                self._overflow_drops += 1
                logger.debug(f"[Queue:{pane_short}] Overflow: dropped {dropped.signal}")
                if METRICS_ENABLED:
                    metrics.inc("queue.overflow_dropped", {"pane": pane_short})
                # 发送调试事件
                self._emit_debug_event(dropped.signal, "drop_overflow")
                return dropped

        # 全是保护事件，无法丢弃
        return None

    def debug_snapshot(self, max_pending: int = 10) -> dict:
        """获取调试快照"""
        pending_events = list(self._queue)[:max_pending]
        return {
            "depth": len(self._queue),
            "max_size": self._max_size,
            "is_processing": self._processing,
            "current_generation": self._current_generation,
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
