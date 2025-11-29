"""状态机 - Signal 到 State 的映射

状态机负责根据当前状态和输入信号计算新状态。
状态机是纯函数，不维护状态，只做转换计算。
"""

import logging
from datetime import datetime

from ..analysis.base import TaskStatus
from ..config import SOURCE_PRIORITY
from .state import PaneState

logger = logging.getLogger(__name__)


class StateMachine:
    """状态机 - 处理状态转换逻辑

    设计原则：
    1. 单一状态：每个 pane 只有一个状态
    2. Source 优先级：高优先级 source 可以覆盖低优先级状态
    3. 纯函数：不维护状态，只计算转换结果
    """

    def can_override(self, current_source: str, new_source: str) -> bool:
        """检查新 source 是否可以覆盖当前状态

        Args:
            current_source: 当前状态的来源
            new_source: 新事件的来源

        Returns:
            True 如果可以覆盖
        """
        # 用户操作总是可以覆盖
        if new_source in ("iterm", "frontend"):
            return True

        current_priority = SOURCE_PRIORITY.get(current_source, 0)
        new_priority = SOURCE_PRIORITY.get(new_source, 0)
        return new_priority >= current_priority

    def transition(
        self,
        current: PaneState,
        signal: str,
        data: dict | None = None
    ) -> PaneState | None:
        """执行状态转换

        Args:
            current: 当前状态
            signal: 信号，格式为 source.event_type
            data: 事件数据

        Returns:
            新状态，None 表示不转换
        """
        data = data or {}
        source, event = self._parse_signal(signal)
        current_status = current.status

        # 优先级检查（用户操作、timer、render 例外）
        # render 用于兜底检测，不受优先级限制
        if source not in ("iterm", "frontend", "timer", "render"):
            if not self.can_override(current.source, source):
                logger.debug(f"Signal {signal} ignored: priority too low")
                return None

        # ===== Shell 事件 =====
        if source == "shell":
            return self._handle_shell(current, event, data)

        # ===== Claude Code 事件 =====
        if source == "claude-code":
            return self._handle_claude_code(current, event, data)

        # ===== Render 事件 =====
        if source == "render":
            return self._handle_render(current, event, data)

        # ===== 定时检查 =====
        if source == "timer":
            return self._handle_timer(current, event, data)

        # ===== 用户操作 =====
        if source in ("iterm", "frontend"):
            return self._handle_user_action(current, event, data)

        return None

    def _handle_shell(
        self,
        current: PaneState,
        event: str,
        data: dict
    ) -> PaneState | None:
        """处理 shell 事件"""
        if event == "command_start":
            command = data.get("command", "")
            desc = f"执行: {command[:30]}" if command else "执行命令"
            return PaneState(
                status=TaskStatus.RUNNING,
                source="shell",
                description=desc,
                started_at=datetime.now(),
                history=current.history,
            )

        if event == "command_end":
            # 只有当前是 shell 的 RUNNING/LONG_RUNNING 才处理
            if current.source != "shell":
                return None
            if current.status not in (TaskStatus.RUNNING, TaskStatus.LONG_RUNNING):
                return None

            exit_code = data.get("exit_code", 0)
            if exit_code == 0:
                return PaneState(
                    status=TaskStatus.DONE,
                    source="shell",
                    description="命令完成",
                    history=current.history,
                )
            else:
                return PaneState(
                    status=TaskStatus.FAILED,
                    source="shell",
                    description=f"命令失败 (exit={exit_code})",
                    history=current.history,
                )

        return None

    def _handle_claude_code(
        self,
        current: PaneState,
        event: str,
        data: dict
    ) -> PaneState | None:
        """处理 claude-code 事件"""
        if event == "SessionStart":
            return PaneState(
                status=TaskStatus.RUNNING,
                source="claude-code",
                description="会话开始",
                started_at=datetime.now(),
                history=current.history,
            )

        if event == "PreToolUse":
            tool = data.get("tool_name", "")
            return PaneState(
                status=TaskStatus.RUNNING,
                source="claude-code",
                description=f"工具: {tool}" if tool else "执行工具",
                started_at=current.started_at if current.source == "claude-code" else datetime.now(),
                history=current.history,
            )

        if event == "PostToolUse":
            # 兜底：工具完成，保持 RUNNING
            if current.source != "claude-code":
                return None
            if current.status not in (TaskStatus.RUNNING, TaskStatus.LONG_RUNNING):
                return None
            tool = data.get("tool_name", "")
            return current.copy_with(
                description=f"工具完成: {tool}" if tool else "工具完成"
            )

        if event == "SubagentStop":
            # 兜底：子 Agent 完成，保持 RUNNING
            if current.source != "claude-code":
                return None
            if current.status not in (TaskStatus.RUNNING, TaskStatus.LONG_RUNNING):
                return None
            return current.copy_with(description="子任务完成")

        if event == "Stop":
            # 只有 claude-code 的 RUNNING/LONG_RUNNING 才处理
            if current.source != "claude-code":
                return None
            if current.status not in (TaskStatus.RUNNING, TaskStatus.LONG_RUNNING):
                return None
            return PaneState(
                status=TaskStatus.DONE,
                source="claude-code",
                description="Claude 已完成回复",
                history=current.history,
            )

        # Notification 事件，格式: Notification:matcher
        if event.startswith("Notification:"):
            matcher = event.split(":", 1)[1]

            if matcher == "permission_prompt":
                return PaneState(
                    status=TaskStatus.WAITING_APPROVAL,
                    source="claude-code",
                    description="需要权限确认",
                    started_at=current.started_at,
                    history=current.history,
                )

            if matcher == "idle_prompt":
                return PaneState(
                    status=TaskStatus.IDLE,
                    source="claude-code",
                    description="",
                    history=current.history,
                )

        if event == "SessionEnd":
            # SessionEnd → IDLE（不恢复 shell 状态）
            return PaneState(
                status=TaskStatus.IDLE,
                source="claude-code",
                description="",
                history=current.history,
            )

        return None

    def _handle_render(
        self,
        current: PaneState,
        event: str,
        data: dict
    ) -> PaneState | None:
        """处理 render 事件"""
        if event == "content_updated":
            # 仅用于 WAITING_APPROVAL 兜底
            if current.status == TaskStatus.WAITING_APPROVAL:
                return PaneState(
                    status=TaskStatus.RUNNING,
                    source=current.source,  # 保持原 source
                    description="检测到内容变化",
                    started_at=datetime.now(),
                    history=current.history,
                )

        return None

    def _handle_timer(
        self,
        current: PaneState,
        event: str,
        data: dict
    ) -> PaneState | None:
        """处理 timer 事件"""
        if event == "check":
            # 只修改 RUNNING 状态
            if current.status == TaskStatus.RUNNING:
                elapsed = data.get("elapsed", "")
                return PaneState(
                    status=TaskStatus.LONG_RUNNING,
                    source=current.source,  # 保持原 source
                    description=f"已运行 {elapsed}" if elapsed else "长时间运行",
                    started_at=current.started_at,
                    history=current.history,
                )

        return None

    def _handle_user_action(
        self,
        current: PaneState,
        event: str,
        data: dict
    ) -> PaneState | None:
        """处理用户操作"""
        # 只清除"待确认"状态
        if current.status in (TaskStatus.DONE, TaskStatus.FAILED, TaskStatus.WAITING_APPROVAL):
            return PaneState(
                status=TaskStatus.IDLE,
                source="user",
                description="",
                history=current.history,
            )

        return None

    def _parse_signal(self, signal: str) -> tuple[str, str]:
        """解析信号为 (source, event)

        Args:
            signal: 信号字符串，格式为 source.event_type

        Returns:
            (source, event) 元组
        """
        parts = signal.split(".", 1)
        if len(parts) == 2:
            return parts[0], parts[1]
        return signal, ""
