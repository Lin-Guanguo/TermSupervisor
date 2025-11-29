"""Hook 分析器 - 基于外部 Hook 事件的状态检测"""

from typing import TYPE_CHECKING

from .base import StatusAnalyzer, TaskStatus

if TYPE_CHECKING:
    from ..models import PaneHistory
    from ..hooks.manager import HookManager


class HookAnalyzer(StatusAnalyzer):
    """Hook 分析器

    通过 HookManager 获取状态，支持：
    - Shell Layer (PromptMonitor) - 基础层
    - Claude Code / Gemini / Codex - 高优先级覆盖层

    与 rule/llm 分析器不同，Hook 分析器是被动的：
    - 不主动分析屏幕内容
    - 依赖外部事件推送
    - 状态由 HookManager 管理
    """

    def __init__(self, manager: "HookManager"):
        self.manager = manager

    async def analyze(self, pane: "PaneHistory") -> TaskStatus:
        """获取 pane 状态（从 HookManager）

        注意：Hook 分析器不主动分析，而是返回已知状态
        """
        status = self.manager.get_status(pane.session_id)

        # 更新 pane 状态
        pane.current_status = status
        pane.status_reason = self.manager.get_reason(pane.session_id)

        return status

    def should_analyze(self, pane: "PaneHistory") -> bool:
        """Hook 分析器总是可以分析（成本为零）"""
        return True

    def get_source(self, pane: "PaneHistory") -> str:
        """获取当前生效的 hook 源"""
        return self.manager.get_active_source(pane.session_id)
