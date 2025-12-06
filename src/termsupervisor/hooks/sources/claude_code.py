"""Claude Code Hook 源 - 通过 HTTP API 接收事件

负责：
- 接收 HTTP API 的 Claude Code 事件
- 规范化事件类型（小写转标准格式）
- 清理大 payload（可选截断 tool_input）
- 通过 emit_event 发送事件（由 HookManager 处理日志/指标）
"""

from typing import TYPE_CHECKING

from ...telemetry import get_logger
from ..sources.base import HookSource

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)

# 事件类型映射表（在 source 中规范化，而非 manager）
_EVENT_TYPE_MAP = {
    "stop": "Stop",
    "pre_tool": "PreToolUse",
    "pre_tool_use": "PreToolUse",
    "post_tool": "PostToolUse",
    "post_tool_use": "PostToolUse",
    "session_start": "SessionStart",
    "session_end": "SessionEnd",
    "permission_prompt": "Notification:permission_prompt",
    "idle_prompt": "Notification:idle_prompt",
    "subagent_stop": "SubagentStop",
}


def normalize_claude_event_type(event_type: str) -> str:
    """规范化 Claude 事件类型

    Args:
        event_type: 原始事件类型

    Returns:
        规范化后的事件类型
    """
    return _EVENT_TYPE_MAP.get(event_type.lower(), event_type)


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
        logger.info("[ClaudeSrc] started, waiting for HTTP events")

    async def stop(self) -> None:
        """停止"""
        logger.info("[ClaudeSrc] stopped")

    async def handle_event(self, pane_id: str, event: str, data: dict | None = None) -> None:
        """处理 Claude Code 事件

        Args:
            pane_id: iTerm2 session_id (来自 $ITERM_SESSION_ID)
            event: 事件类型（HTTP hook 原始事件名）
            data: 额外数据（原始 HTTP 请求数据）
        """
        # 1. 规范化事件类型（在 source 中完成）
        normalized_type = normalize_claude_event_type(event)

        # 2. 使用 emit_event 发送，Manager 负责日志/指标
        await self.manager.emit_event(
            source="claude-code",
            pane_id=pane_id,
            event_type=normalized_type,
            data=data,
        )
