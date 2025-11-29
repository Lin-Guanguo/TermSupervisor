"""iTerm2 PromptMonitor 封装 - 零侵入的命令状态监控"""

import asyncio
import logging
from typing import Callable, Awaitable

import iterm2

logger = logging.getLogger(__name__)

# 命令事件回调类型
# (session_id, event_type, info) -> None
# event_type: "command_start" | "command_end"
# info: 命令字符串(start) 或 退出码(end)
CommandEventCallback = Callable[[str, str, str | int], Awaitable[None]]


class PromptMonitorManager:
    """PromptMonitor 管理器

    管理所有 session 的 PromptMonitor，处理：
    - 自动启动/停止监听
    - Session 生命周期
    - 错误恢复

    前提条件：iTerm2 Shell Integration 已安装
    """

    def __init__(self, connection: iterm2.Connection):
        self.connection = connection
        self._monitors: dict[str, asyncio.Task] = {}  # session_id -> monitor task
        self._running = False
        self._on_command: CommandEventCallback | None = None

    def set_command_callback(self, callback: CommandEventCallback) -> None:
        """设置命令事件回调"""
        self._on_command = callback

    async def start(self) -> None:
        """启动监控"""
        self._running = True
        logger.info("[PromptMonitor] 管理器已启动")

    async def stop(self) -> None:
        """停止所有监控"""
        self._running = False

        # 取消所有监控任务
        for session_id, task in list(self._monitors.items()):
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        self._monitors.clear()
        logger.info("[PromptMonitor] 管理器已停止")

    async def add_session(self, session_id: str) -> bool:
        """为 session 添加监控

        Returns:
            是否成功添加
        """
        if not self._running:
            return False

        if session_id in self._monitors:
            return True  # 已存在

        # 启动监控任务
        task = asyncio.create_task(self._monitor_session(session_id))
        self._monitors[session_id] = task
        logger.debug(f"[PromptMonitor] 添加监控: {session_id}")
        return True

    async def remove_session(self, session_id: str) -> None:
        """移除 session 监控"""
        if task := self._monitors.pop(session_id, None):
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            logger.debug(f"[PromptMonitor] 移除监控: {session_id}")

    async def sync_sessions(self, active_session_ids: set[str]) -> None:
        """同步 session 列表

        添加新 session，移除已关闭的 session
        """
        current_ids = set(self._monitors.keys())

        # 添加新 session
        for session_id in active_session_ids - current_ids:
            await self.add_session(session_id)

        # 移除已关闭的 session
        for session_id in current_ids - active_session_ids:
            await self.remove_session(session_id)

    async def _monitor_session(self, session_id: str) -> None:
        """监控单个 session 的命令状态"""
        try:
            async with iterm2.PromptMonitor(
                self.connection,
                session_id,
                modes=[
                    iterm2.PromptMonitor.Mode.COMMAND_START,
                    iterm2.PromptMonitor.Mode.COMMAND_END,
                ]
            ) as monitor:
                logger.info(f"[PromptMonitor] 开始监控 session: {session_id}")

                while self._running:
                    try:
                        mode, info = await asyncio.wait_for(
                            monitor.async_get(),
                            timeout=60.0  # 每分钟检查一次运行状态
                        )

                        if mode == iterm2.PromptMonitor.Mode.COMMAND_START:
                            # info 是命令字符串
                            command = info if info else ""
                            logger.debug(f"[PromptMonitor] {session_id} 命令开始: {command[:50]}")
                            if self._on_command:
                                await self._on_command(session_id, "command_start", command)

                        elif mode == iterm2.PromptMonitor.Mode.COMMAND_END:
                            # info 是退出码
                            exit_code = info if info is not None else 0
                            logger.debug(f"[PromptMonitor] {session_id} 命令结束: exit={exit_code}")
                            if self._on_command:
                                await self._on_command(session_id, "command_end", exit_code)

                    except asyncio.TimeoutError:
                        # 超时，继续循环检查运行状态
                        continue

        except iterm2.RPCException as e:
            # Shell Integration 未安装或其他 API 错误
            logger.warning(f"[PromptMonitor] {session_id} 监控失败: {e}")
        except asyncio.CancelledError:
            logger.debug(f"[PromptMonitor] {session_id} 监控已取消")
            raise
        except Exception as e:
            logger.error(f"[PromptMonitor] {session_id} 监控异常: {e}")
        finally:
            # 从监控列表移除
            self._monitors.pop(session_id, None)
