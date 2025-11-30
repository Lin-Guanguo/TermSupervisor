"""Timer - 统一定时器服务

提供 interval（周期）和 delay（延迟）两种任务类型。
支持同步/异步回调，异常隔离，绑定 Supervisor 生命周期。

使用示例:
    timer = Timer()

    # 注册周期任务（每秒检查 LONG_RUNNING）
    timer.register_interval("long_running_check", 1.0, check_long_running)

    # 注册延迟任务（5秒后清除状态）
    timer.register_delay("clear_pane_123", 5.0, lambda: clear_pane("123"))

    # 取消延迟任务
    timer.cancel_delay("clear_pane_123")

    # 启动/停止
    await timer.run()
    timer.stop()
"""

import asyncio
import inspect
from dataclasses import dataclass, field
from typing import Callable, Any, Coroutine

from .telemetry import get_logger, metrics
from .config import METRICS_ENABLED

logger = get_logger(__name__)


@dataclass
class IntervalTask:
    """周期任务"""
    name: str
    interval: float  # 秒
    callback: Callable[[], Any | Coroutine[Any, Any, Any]]
    last_run: float = 0.0  # 上次运行时间（event loop time）


@dataclass
class DelayTask:
    """延迟任务"""
    name: str
    delay: float  # 秒
    callback: Callable[[], Any | Coroutine[Any, Any, Any]]
    scheduled_at: float = 0.0  # 调度时间（event loop time）
    trigger_at: float = 0.0  # 触发时间
    cancelled: bool = False


class Timer:
    """统一定时器服务

    设计原则:
    1. 单个 Timer 实例负责所有定时任务
    2. 支持同步/异步回调（内部 create_task 包裹）
    3. 异常隔离：单个回调失败不影响其他任务
    4. 生命周期由 Supervisor 管理
    """

    def __init__(self, tick_interval: float | None = None):
        """初始化 Timer

        Args:
            tick_interval: tick 间隔（秒），None 使用配置默认值
        """
        from . import config
        self._tick_interval = tick_interval or config.TIMER_TICK_INTERVAL
        self._interval_tasks: dict[str, IntervalTask] = {}
        self._delay_tasks: dict[str, DelayTask] = {}
        self._running = False
        self._task: asyncio.Task | None = None

    def register_interval(
        self,
        name: str,
        interval: float,
        callback: Callable[[], Any | Coroutine[Any, Any, Any]]
    ) -> None:
        """注册周期任务

        Args:
            name: 任务名（用于日志和取消）
            interval: 执行间隔（秒）
            callback: 回调函数（同步或异步）
        """
        self._interval_tasks[name] = IntervalTask(
            name=name,
            interval=interval,
            callback=callback,
        )
        logger.debug(f"[Timer] Registered interval task: {name} ({interval}s)")

    def unregister_interval(self, name: str) -> bool:
        """取消注册周期任务

        Args:
            name: 任务名

        Returns:
            是否成功取消
        """
        if name in self._interval_tasks:
            del self._interval_tasks[name]
            logger.debug(f"[Timer] Unregistered interval task: {name}")
            return True
        return False

    def register_delay(
        self,
        name: str,
        delay: float,
        callback: Callable[[], Any | Coroutine[Any, Any, Any]]
    ) -> None:
        """注册延迟任务

        如果已存在同名任务，会被覆盖（取消旧任务）。

        Args:
            name: 任务名（用于日志和取消）
            delay: 延迟时间（秒）
            callback: 回调函数（同步或异步）
        """
        loop = asyncio.get_event_loop()
        now = loop.time()

        # 覆盖旧任务
        if name in self._delay_tasks:
            logger.debug(f"[Timer] Overwriting delay task: {name}")

        self._delay_tasks[name] = DelayTask(
            name=name,
            delay=delay,
            callback=callback,
            scheduled_at=now,
            trigger_at=now + delay,
        )
        logger.debug(f"[Timer] Registered delay task: {name} ({delay}s)")

    def cancel_delay(self, name: str) -> bool:
        """取消延迟任务

        Args:
            name: 任务名

        Returns:
            是否成功取消
        """
        if name in self._delay_tasks:
            task = self._delay_tasks[name]
            task.cancelled = True
            del self._delay_tasks[name]
            logger.debug(f"[Timer] Cancelled delay task: {name}")
            return True
        return False

    def has_delay(self, name: str) -> bool:
        """检查是否存在延迟任务

        Args:
            name: 任务名

        Returns:
            是否存在
        """
        return name in self._delay_tasks

    async def run(self) -> None:
        """启动 Timer 主循环

        持续运行直到调用 stop()。
        """
        if self._running:
            logger.warning("[Timer] Already running")
            return

        self._running = True
        logger.info(f"[Timer] Started (tick={self._tick_interval}s)")

        try:
            while self._running:
                await self._tick()
                await asyncio.sleep(self._tick_interval)
        except asyncio.CancelledError:
            logger.info("[Timer] Cancelled")
        finally:
            self._cleanup()

    def stop(self) -> None:
        """停止 Timer

        取消所有未触发的延迟任务。
        """
        if not self._running:
            return

        self._running = False
        logger.info("[Timer] Stopping...")

        # 取消所有未触发的延迟任务
        for name in list(self._delay_tasks.keys()):
            self.cancel_delay(name)

        # 取消主任务
        if self._task and not self._task.done():
            self._task.cancel()

    def _cleanup(self) -> None:
        """清理资源"""
        self._delay_tasks.clear()
        logger.debug("[Timer] Cleaned up")

    async def _tick(self) -> None:
        """执行一次 tick

        检查并执行到期的任务。
        """
        loop = asyncio.get_event_loop()
        now = loop.time()

        # 执行周期任务
        for task in list(self._interval_tasks.values()):
            if now - task.last_run >= task.interval:
                task.last_run = now
                await self._execute_callback(task.name, task.callback)

        # 执行到期的延迟任务
        triggered_names = []
        for name, task in list(self._delay_tasks.items()):
            if task.cancelled:
                triggered_names.append(name)
                continue
            if now >= task.trigger_at:
                triggered_names.append(name)
                await self._execute_callback(task.name, task.callback)

        # 清理已触发的延迟任务
        for name in triggered_names:
            self._delay_tasks.pop(name, None)

    async def _execute_callback(
        self,
        name: str,
        callback: Callable[[], Any | Coroutine[Any, Any, Any]]
    ) -> None:
        """执行回调（带异常隔离）

        Args:
            name: 任务名
            callback: 回调函数
        """
        try:
            result = callback()
            # 如果是协程，await 它
            if inspect.iscoroutine(result):
                await result
        except Exception as e:
            logger.error(f"[Timer] Task '{name}' failed: {e}")
            if METRICS_ENABLED:
                metrics.inc("timer.errors", {"task": name})

    # === 状态查询（用于测试）===

    @property
    def is_running(self) -> bool:
        """是否正在运行"""
        return self._running

    @property
    def interval_task_count(self) -> int:
        """周期任务数量"""
        return len(self._interval_tasks)

    @property
    def delay_task_count(self) -> int:
        """延迟任务数量"""
        return len(self._delay_tasks)

    def get_interval_tasks(self) -> list[str]:
        """获取所有周期任务名"""
        return list(self._interval_tasks.keys())

    def get_delay_tasks(self) -> list[str]:
        """获取所有延迟任务名"""
        return list(self._delay_tasks.keys())
