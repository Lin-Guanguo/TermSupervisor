"""iTerm2 Hook 源 - 监控 Focus 事件"""

import asyncio
import logging
from typing import TYPE_CHECKING

import iterm2

from ..sources.base import HookSource
from ...config import FOCUS_DEBOUNCE_SECONDS

if TYPE_CHECKING:
    from ..manager import HookManager

logger = logging.getLogger(__name__)


class ItermHookSource(HookSource):
    """iTerm2 Hook 源

    监控 iTerm2 focus 变化，发送 iterm.focus 事件。
    用于清除 DONE/FAILED 状态。

    Signal 格式：
    - iterm.focus: 用户在 iTerm2 中稳定 focus 到某个 session

    防抖设计：
    - 用户快速切换时不发送事件
    - 稳定 FOCUS_DEBOUNCE_SECONDS 秒后才发送
    """

    source_name = "iterm"

    def __init__(self, manager: "HookManager", connection: iterm2.Connection):
        super().__init__(manager)
        self.connection = connection
        self._focus_task: asyncio.Task | None = None

        # 防抖状态
        self._last_focus_session: str | None = None
        self._debounce_task: asyncio.Task | None = None

    async def start(self) -> None:
        """启动 Focus 监听"""
        self._focus_task = asyncio.create_task(self._monitor_focus())
        logger.info("[ItermHook] Focus 监听已启动")

    async def stop(self) -> None:
        """停止监听"""
        if self._focus_task:
            self._focus_task.cancel()
            try:
                await self._focus_task
            except asyncio.CancelledError:
                pass

        if self._debounce_task:
            self._debounce_task.cancel()
            try:
                await self._debounce_task
            except asyncio.CancelledError:
                pass

        logger.info("[ItermHook] Focus 监听已停止")

    async def _monitor_focus(self) -> None:
        """监控 iTerm2 focus 变化

        使用 iTerm2 FocusMonitor API 监听 focus 变化事件。
        """
        try:
            async with iterm2.FocusMonitor(self.connection) as monitor:
                while True:
                    update = await monitor.async_get_next_update()

                    # 检查是否有 session focus 变化
                    if update.active_session_changed:
                        # active_session_changed 是 FocusUpdateActiveSessionChanged 对象
                        # 需要获取其 session_id 属性
                        session_id = update.active_session_changed.session_id
                        if session_id:
                            await self._on_focus_change(session_id)

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"[ItermHook] Focus 监控异常: {e}")

    async def _on_focus_change(self, session_id: str) -> None:
        """处理 focus 变化（带防抖）

        Args:
            session_id: 新 focus 的 session_id
        """
        # 取消之前的防抖任务
        if self._debounce_task:
            self._debounce_task.cancel()
            try:
                await self._debounce_task
            except asyncio.CancelledError:
                pass

        self._last_focus_session = session_id

        # 启动新的防抖任务
        self._debounce_task = asyncio.create_task(
            self._debounced_focus_event(session_id)
        )

    async def _debounced_focus_event(self, session_id: str) -> None:
        """防抖后发送 focus 事件

        Args:
            session_id: focus 的 session_id
        """
        try:
            # 等待防抖时间
            await asyncio.sleep(FOCUS_DEBOUNCE_SECONDS)

            # 确认仍然 focus 在同一个 session
            if self._last_focus_session == session_id:
                logger.debug(f"[ItermHook] 发送 focus 事件: {session_id}")
                await self.manager.process_user_focus(session_id)

        except asyncio.CancelledError:
            # 被新的 focus 取消，正常行为
            pass
