"""ActorQueue - 每 pane 的事件队列

实现 Actor 模式，保证事件串行处理。

特性：
- 最大容量 256
- 高水位 75% 打印日志
- 溢出时丢弃最旧事件
- 丢弃时记录 queue.dropped 指标
"""

from collections import deque
from typing import Generic, TypeVar, Callable, Any, Coroutine

from ..telemetry import get_logger, metrics
from ..config import QUEUE_MAX_SIZE, QUEUE_HIGH_WATERMARK, METRICS_ENABLED
from .types import HookEvent

logger = get_logger(__name__)

T = TypeVar("T")


class ActorQueue(Generic[T]):
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
            dropped = self._queue.popleft()
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
    """

    def __init__(self, pane_id: str, max_size: int = QUEUE_MAX_SIZE):
        super().__init__(pane_id, max_size)
        self._current_generation: int = 1
        self._current_state_id: int = 0

    def set_current_generation(self, generation: int) -> None:
        """设置当前 generation"""
        self._current_generation = generation

    def set_current_state_id(self, state_id: int) -> None:
        """设置当前 state_id"""
        self._current_state_id = state_id

    def enqueue_event(self, event: HookEvent) -> bool:
        """入队事件（带过期检查）

        Args:
            event: Hook 事件

        Returns:
            是否入队成功（过期事件返回 False）
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
            return False

        return self.enqueue(event)
