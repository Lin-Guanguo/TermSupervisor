"""Claude Code Hook 源 - 通过 HTTP API 接收事件"""

import logging
from typing import TYPE_CHECKING

from ..sources.base import HookSource

if TYPE_CHECKING:
    from ..manager import HookManager

logger = logging.getLogger(__name__)


class ClaudeCodeHookSource(HookSource):
    """Claude Code Hook 源

    通过 HTTP API 接收 Claude Code 的 hook 事件。

    Signal 格式 (claude-code.{event}):
    - SessionStart: 会话开始
    - PreToolUse: 工具调用前
    - PostToolUse: 工具调用后
    - SubagentStop: 子 Agent 完成
    - Stop: 任务完成
    - SessionEnd: 会话结束
    - Notification:permission_prompt: 需要权限确认
    - Notification:idle_prompt: 空闲等待输入
    """

    source_name = "claude-code"

    async def start(self) -> None:
        """启动（无需操作，由 HTTP 接收器触发）"""
        logger.info("[ClaudeCodeHook] 已启动，等待 HTTP 事件")

    async def stop(self) -> None:
        """停止"""
        logger.info("[ClaudeCodeHook] 已停止")

    async def handle_event(
        self,
        pane_id: str,
        event: str,
        data: dict | None = None
    ) -> None:
        """处理 Claude Code 事件

        Args:
            pane_id: iTerm2 session_id (来自 $ITERM_SESSION_ID)
            event: 事件类型（HTTP hook 原始事件名）
            data: 额外数据（原始 HTTP 请求数据）
        """
        logger.info(f"[ClaudeCodeHook] pane={pane_id} event={event}")

        # 使用 HookManager 的便捷方法处理事件
        # HookManager 会负责事件名规范化
        await self.manager.process_claude_code_event(pane_id, event, data)
