"""状态分析模块"""

from .base import StatusAnalyzer, TaskStatus
from .cleaner import ChangeCleaner
from .content_cleaner import ContentCleaner

__all__ = [
    "StatusAnalyzer",
    "TaskStatus",
    "ChangeCleaner",
    "ContentCleaner",
    "get_hook_manager",
    "create_analyzer",  # 保留用于兼容性，但已废弃
]


# 全局 HookManager 单例
_hook_manager = None


def get_hook_manager():
    """获取 HookManager 单例"""
    global _hook_manager
    if _hook_manager is None:
        from ..hooks.manager import HookManager
        _hook_manager = HookManager()
    return _hook_manager


class _DummyAnalyzer(StatusAnalyzer):
    """空分析器 - Hook 系统直接管理状态，不需要分析器"""

    async def analyze(self, pane) -> TaskStatus:
        """不执行任何分析，状态由 HookManager 管理"""
        return pane.current_status or TaskStatus.UNKNOWN

    def should_analyze(self, pane) -> bool:
        """始终返回 False，不触发分析"""
        return False


def create_analyzer(analyzer_type: str = "hook") -> StatusAnalyzer:
    """工厂函数 - 已废弃

    状态管理已完全由 HookManager 接管，此函数仅保留用于兼容性。
    返回一个空分析器，不执行任何操作。
    """
    return _DummyAnalyzer()
