"""Claude Code Hook 源 - 通过 HTTP API 接收事件"""

import logging
from typing import TYPE_CHECKING

from ..sources.base import HookSource
from ...analysis.base import TaskStatus

if TYPE_CHECKING:
    from ..manager import HookManager

logger = logging.getLogger(__name__)


class ClaudeCodeHookSource(HookSource):
    """Claude Code Hook 源

    通过 HTTP API 接收 Claude Code 的 hook 事件。

    事件类型：
    - stop: 任务完成
    - permission_prompt: 需要权限确认
    - idle_prompt: 空闲等待
    - pre_tool: 工具调用前
    - post_tool: 工具调用后
    - session_start: 会话开始
    - session_end: 会话结束
    """

    source_name = "claude-code"

    # 事件 -> 状态映射
    EVENT_STATUS_MAP = {
        "stop": TaskStatus.COMPLETED,
        "permission_prompt": TaskStatus.WAITING_APPROVAL,
        "idle_prompt": TaskStatus.IDLE,
        "pre_tool": TaskStatus.RUNNING,
        "post_tool": TaskStatus.RUNNING,
        "session_start": TaskStatus.RUNNING,
        "session_end": TaskStatus.IDLE,
        # 扩展事件
        "thinking": TaskStatus.THINKING,
        "error": TaskStatus.FAILED,
    }

    # 事件 -> 原因描述
    EVENT_REASON_MAP = {
        "stop": "Claude 已完成回复",
        "permission_prompt": "等待权限确认",
        "idle_prompt": "等待用户输入",
        "pre_tool": "正在执行工具",
        "post_tool": "工具执行完成",
        "session_start": "会话开始",
        "session_end": "会话结束",
        "thinking": "Claude 正在思考",
        "error": "发生错误",
    }

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
            event: 事件类型
            data: 额外数据
        """
        status = self.EVENT_STATUS_MAP.get(event, TaskStatus.UNKNOWN)
        reason = self.EVENT_REASON_MAP.get(event, "")

        # 可以从 data 中获取更多信息来丰富 reason
        if data:
            if tool_name := data.get("tool_name"):
                if event == "pre_tool":
                    reason = f"执行工具: {tool_name}"
                elif event == "post_tool":
                    reason = f"工具完成: {tool_name}"
            if error_msg := data.get("error"):
                reason = f"错误: {error_msg}"

        logger.info(f"[ClaudeCodeHook] pane={pane_id} event={event} status={status.value}")

        await self.manager.update_status(
            pane_id=pane_id,
            source=self.source_name,
            status=status,
            reason=reason,
            data=data or {}
        )
