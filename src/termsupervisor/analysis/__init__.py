"""状态分析模块"""

from .base import StatusAnalyzer, TaskStatus
from .cleaner import ChangeCleaner

__all__ = ["StatusAnalyzer", "TaskStatus", "ChangeCleaner", "create_analyzer"]


# 全局 HookManager 单例（hook 模式下使用）
_hook_manager = None


def get_hook_manager():
    """获取 HookManager 单例"""
    global _hook_manager
    if _hook_manager is None:
        from ..hooks.manager import HookManager
        _hook_manager = HookManager()
    return _hook_manager


def create_analyzer(analyzer_type: str = "llm") -> StatusAnalyzer:
    """工厂函数

    Args:
        analyzer_type: "hook" | "rule" | "llm"
            - hook: 基于外部 Hook 事件（推荐，准确度最高）
            - rule: 基于规则引擎
            - llm: 基于 LLM 分析
    """
    if analyzer_type == "hook":
        from .hook import HookAnalyzer
        return HookAnalyzer(get_hook_manager())
    if analyzer_type == "rule":
        from .rule_based import RuleBasedAnalyzer
        return RuleBasedAnalyzer()
    from .llm import LLMAnalyzer
    return LLMAnalyzer()
