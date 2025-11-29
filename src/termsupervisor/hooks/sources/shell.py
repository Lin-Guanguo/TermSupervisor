"""Shell Hook 源 - 基于 iTerm2 PromptMonitor"""

import logging
from typing import TYPE_CHECKING

import iterm2

from ..sources.base import HookSource
from ..prompt_monitor import PromptMonitorManager
from ...analysis.base import TaskStatus

if TYPE_CHECKING:
    from ..manager import HookManager

logger = logging.getLogger(__name__)


class ShellHookSource(HookSource):
    """Shell Hook 源

    基于 iTerm2 PromptMonitor API，监控命令执行状态。
    零侵入，无需修改 .zshrc。

    前提条件：
    - iTerm2 Python API 已启用
    - Shell Integration 已安装
    """

    source_name = "shell"

    def __init__(self, manager: "HookManager", connection: iterm2.Connection):
        super().__init__(manager)
        self.connection = connection
        self._prompt_monitor = PromptMonitorManager(connection)
        self._prompt_monitor.set_command_callback(self._on_command_event)

        # 跟踪每个 session 的当前命令
        self._current_commands: dict[str, str] = {}  # session_id -> command

    async def start(self) -> None:
        """启动 Shell Hook 监听"""
        await self._prompt_monitor.start()
        logger.info("[ShellHook] 已启动")

    async def stop(self) -> None:
        """停止监听"""
        await self._prompt_monitor.stop()
        logger.info("[ShellHook] 已停止")

    async def sync_sessions(self, session_ids: set[str]) -> None:
        """同步 session 列表"""
        await self._prompt_monitor.sync_sessions(session_ids)

    async def _on_command_event(
        self,
        session_id: str,
        event_type: str,
        info: str | int
    ) -> None:
        """处理命令事件

        Args:
            session_id: iTerm2 session_id
            event_type: "command_start" | "command_end"
            info: 命令字符串(start) 或 退出码(end)
        """
        if event_type == "command_start":
            # 命令开始
            command = str(info) if info else ""
            self._current_commands[session_id] = command

            await self.manager.update_status(
                pane_id=session_id,
                source=self.source_name,
                status=TaskStatus.RUNNING,
                reason=f"执行: {command[:30]}..." if len(command) > 30 else f"执行: {command}",
                event_type="command_start",
                raw_data={"command": command}
            )

        elif event_type == "command_end":
            # 命令结束
            exit_code = int(info) if info else 0
            command = self._current_commands.pop(session_id, "")

            status = TaskStatus.COMPLETED if exit_code == 0 else TaskStatus.FAILED
            reason = "命令执行完成" if exit_code == 0 else f"命令失败 (exit={exit_code})"

            await self.manager.update_status(
                pane_id=session_id,
                source=self.source_name,
                status=status,
                reason=reason,
                event_type="command_end",
                raw_data={"command": command, "exit_code": exit_code}
            )
