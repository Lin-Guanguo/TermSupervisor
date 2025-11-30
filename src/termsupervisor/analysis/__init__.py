"""状态分析模块

注意：TaskStatus 已统一到 pane 模块，请从 termsupervisor.pane 导入。
"""

from .base import StatusAnalyzer
from .cleaner import ChangeCleaner
from .content_cleaner import ContentCleaner
from ..pane import TaskStatus  # 内部使用

__all__ = [
    "StatusAnalyzer",
    "ChangeCleaner",
    "ContentCleaner",
    "get_hook_manager",
    "get_timer",
    "create_analyzer",  # 保留用于兼容性，但已废弃
]


# 全局 HookManager 单例（新架构）
_hook_manager = None
_timer = None


def get_hook_manager():
    """获取 HookManager 单例（新架构）

    使用依赖注入方式创建，持有独立的 Timer 实例。
    """
    global _hook_manager, _timer
    if _hook_manager is None:
        from ..hooks.manager import HookManager
        from ..timer import Timer

        # 创建 Timer
        _timer = Timer()

        # 创建 HookManager（注入 Timer）
        _hook_manager = HookManager(timer=_timer)

        # 注册 tick_all 到 Timer（每秒检查一次 LONG_RUNNING）
        from ..config import TIMER_TICK_INTERVAL
        _timer.register_interval("long_running_check", TIMER_TICK_INTERVAL, _hook_manager.tick_all)

    return _hook_manager


def get_timer():
    """获取 Timer 单例"""
    global _timer
    if _timer is None:
        # 触发 HookManager 初始化，同时创建 Timer
        get_hook_manager()
    return _timer


class _DummyAnalyzer(StatusAnalyzer):
    """空分析器 - Hook 系统直接管理状态，不需要分析器"""

    async def analyze(self, pane) -> TaskStatus:
        """不执行任何分析，状态由 HookManager 管理"""
        return pane.current_status or TaskStatus.IDLE

    def should_analyze(self, pane) -> bool:
        """始终返回 False，不触发分析"""
        return False


def create_analyzer(analyzer_type: str = "hook") -> StatusAnalyzer:
    """工厂函数 - 已废弃

    状态管理已完全由 HookManager 接管，此函数仅保留用于兼容性。
    返回一个空分析器，不执行任何操作。
    """
    return _DummyAnalyzer()
