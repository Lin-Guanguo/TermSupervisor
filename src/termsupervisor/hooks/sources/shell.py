"""Shell Hook 源 - 基于 iTerm2 PromptMonitor

负责：
- 接收 iTerm2 PromptMonitor 命令事件
- 清洗命令字符串（去除 NUL/newlines，截断）
- 通过 emit_event 发送事件（由 HookManager 处理日志/指标）
- 暴露 PromptMonitor 状态给内容启发式分析器
"""

import re
from typing import TYPE_CHECKING

import iterm2

from ...config import LOG_MAX_CMD_LEN
from ...telemetry import get_logger
from ..prompt_monitor import PromptMonitorManager, PromptMonitorStatus
from ..sources.base import HookSource

if TYPE_CHECKING:
    from ..manager import HookManager

logger = get_logger(__name__)

# 命令清洗配置
_CMD_TRUNCATE_LEN = LOG_MAX_CMD_LEN  # 从 config.py 读取，默认 120


def sanitize_command(command: str, max_len: int = _CMD_TRUNCATE_LEN) -> str:
    """清洗命令字符串

    - 移除 NUL 字符
    - 将换行替换为空格
    - 折叠连续空白
    - 截断到 max_len

    Args:
        command: 原始命令
        max_len: 最大长度

    Returns:
        清洗后的命令
    """
    if not command:
        return ""
    # 移除 NUL
    cmd = command.replace("\x00", "")
    # 换行替换为空格
    cmd = cmd.replace("\n", " ").replace("\r", " ")
    # 折叠连续空白
    cmd = re.sub(r"\s+", " ", cmd).strip()
    # 截断
    if len(cmd) > max_len:
        return cmd[: max_len - 3] + "..."
    return cmd


class ShellHookSource(HookSource):
    """Shell Hook 源

    基于 iTerm2 PromptMonitor API，监控命令执行状态。
    零侵入，无需修改 .zshrc。

    前提条件：
    - iTerm2 Python API 已启用
    - Shell Integration 已安装

    Signal 格式：
    - shell.command_start: 命令开始
    - shell.command_end: 命令结束
    """

    source_name = "shell"

    def __init__(self, manager: "HookManager", connection: iterm2.Connection):
        super().__init__(manager)
        self.connection = connection
        self._prompt_monitor = PromptMonitorManager(connection)
        self._prompt_monitor.set_command_callback(self._on_command_event)

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

    def get_prompt_monitor_status(self, session_id: str) -> PromptMonitorStatus:
        """Get PromptMonitor status for a session (for heuristic gating)"""
        return self._prompt_monitor.get_status(session_id)

    async def _on_command_event(self, session_id: str, event_type: str, info: str | int) -> None:
        """处理命令事件

        Args:
            session_id: iTerm2 session_id
            event_type: "command_start" | "command_end"
            info: 命令字符串(start) 或 退出码(end)
        """
        if event_type == "command_start":
            # 命令开始 - 清洗命令后发送
            raw_command = str(info) if info else ""
            sanitized = sanitize_command(raw_command)

            # 使用 emit_event 发送，Manager 负责日志/指标
            await self.manager.emit_event(
                source="shell",
                pane_id=session_id,
                event_type="command_start",
                data={"command": sanitized},  # 传递清洗后的命令
            )

        elif event_type == "command_end":
            # 命令结束
            exit_code = int(info) if info else 0

            await self.manager.emit_event(
                source="shell",
                pane_id=session_id,
                event_type="command_end",
                data={"exit_code": exit_code},
            )
