"""Tmux Hook 源 - 监控 Focus 事件

负责：
- 轮询 tmux 当前活跃 pane
- 防抖处理（稳定 N 秒后才发送）
- 通过 emit_event 发送事件（由 HookManager 处理日志/指标）

Composite 模式支持：
- 使用 namespaced pane_id（如 "tmux:%0"）
- 可配置是否启用命名空间（用于区分 iTerm2 和 tmux pane）
"""

import asyncio
from typing import TYPE_CHECKING

from termsupervisor.adapters.tmux import TmuxClient
from termsupervisor.core.ids import AdapterType, make_pane_id

from ...config import FOCUS_DEBOUNCE_SECONDS, POLL_INTERVAL
from ...telemetry import get_logger
from ..sources.base import HookSource

if TYPE_CHECKING:
    from ..manager import HookManager

logger = get_logger(__name__)


class TmuxHookSource(HookSource):
    """Tmux Hook 源

    轮询 tmux 活跃 pane，发送 tmux.focus 事件。
    用于清除 DONE/FAILED 状态。

    Signal 格式：
    - tmux.focus: 用户在 tmux 中稳定 focus 到某个 pane

    防抖设计：
    - 用户快速切换时不发送事件
    - 稳定 FOCUS_DEBOUNCE_SECONDS 秒后才发送
    """

    source_name = "tmux"

    def __init__(
        self,
        manager: "HookManager",
        client: TmuxClient | None = None,
        poll_interval: float | None = None,
        use_namespace: bool = False,
    ):
        """Initialize TmuxHookSource.

        Args:
            manager: HookManager instance
            client: TmuxClient instance (optional)
            poll_interval: Polling interval in seconds
            use_namespace: Whether to prefix pane IDs with "tmux:" namespace.
                          Enable this in composite mode.
        """
        super().__init__(manager)
        self._client = client or TmuxClient()
        self._poll_interval = poll_interval or POLL_INTERVAL
        self._poll_task: asyncio.Task | None = None
        self._use_namespace = use_namespace

        # 防抖状态
        self._last_focus_pane: str | None = None
        self._debounce_task: asyncio.Task | None = None

        # 当前 focus 的 pane（已通过防抖确认）
        self._current_focus_pane: str | None = None

    @property
    def current_focus_pane(self) -> str | None:
        """获取当前 focus 的 pane_id（用于通知抑制判断）"""
        return self._current_focus_pane

    async def start(self) -> None:
        """启动 Focus 监听"""
        self._poll_task = asyncio.create_task(self._poll_focus())
        logger.info("[TmuxHook] Focus 监听已启动")

    async def stop(self) -> None:
        """停止监听"""
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass

        if self._debounce_task:
            self._debounce_task.cancel()
            try:
                await self._debounce_task
            except asyncio.CancelledError:
                pass

        logger.info("[TmuxHook] Focus 监听已停止")

    async def _poll_focus(self) -> None:
        """轮询 tmux 活跃 pane

        使用 try/except 包裹每次轮询，避免单次错误终止整个轮询循环。
        """
        consecutive_errors = 0
        max_consecutive_errors = 5

        while True:
            try:
                pane_id = await self._client.get_active_pane()
                if pane_id and pane_id != self._last_focus_pane:
                    await self._on_focus_change(pane_id)

                consecutive_errors = 0  # 成功后重置错误计数

            except asyncio.CancelledError:
                raise
            except Exception as e:
                consecutive_errors += 1
                logger.error(f"[TmuxHook] Focus 轮询异常 ({consecutive_errors}/{max_consecutive_errors}): {e}")

                # 连续多次错误后增加等待时间（指数退避）
                if consecutive_errors >= max_consecutive_errors:
                    logger.warning("[TmuxHook] 连续错误过多，增加轮询间隔")
                    await asyncio.sleep(self._poll_interval * 5)
                    consecutive_errors = 0  # 重置后继续

            await asyncio.sleep(self._poll_interval)

    async def _on_focus_change(self, pane_id: str) -> None:
        """处理 focus 变化（带防抖）

        Args:
            pane_id: 新 focus 的 pane_id
        """
        # 取消之前的防抖任务
        if self._debounce_task and not self._debounce_task.done():
            self._debounce_task.cancel()
            try:
                await self._debounce_task
            except Exception:
                # 忽略所有异常（包括 CancelledError 和其他任务失败）
                pass

        self._last_focus_pane = pane_id

        # 启动新的防抖任务
        self._debounce_task = asyncio.create_task(self._debounced_focus_event(pane_id))

    def _get_namespaced_id(self, pane_id: str) -> str:
        """Get pane ID with optional namespace prefix.

        Args:
            pane_id: Native tmux pane ID (e.g., "%0")

        Returns:
            Namespaced ID if use_namespace is True (e.g., "tmux:%0"),
            otherwise returns the original pane_id.
        """
        if self._use_namespace:
            return make_pane_id(AdapterType.TMUX, pane_id)
        return pane_id

    async def _debounced_focus_event(self, pane_id: str) -> None:
        """防抖后发送 focus 事件

        Args:
            pane_id: focus 的 pane_id (native, without namespace)
        """
        try:
            # 等待防抖时间
            await asyncio.sleep(FOCUS_DEBOUNCE_SECONDS)

            # 确认仍然 focus 在同一个 pane
            if self._last_focus_pane == pane_id:
                # 更新当前 focus（用于通知抑制判断）
                # Store the namespaced version for external use
                namespaced_id = self._get_namespaced_id(pane_id)
                self._current_focus_pane = namespaced_id

                # 使用 emit_event 发送，Manager 负责日志/指标
                await self.manager.emit_event(
                    source="tmux",
                    pane_id=namespaced_id,
                    event_type="focus",
                )

        except asyncio.CancelledError:
            # 被新的 focus 取消，正常行为
            pass
