"""状态分析模块"""

from .base import StatusAnalyzer, TaskStatus
from .cleaner import ChangeCleaner

__all__ = ["StatusAnalyzer", "TaskStatus", "ChangeCleaner", "create_analyzer"]


def create_analyzer(analyzer_type: str = "llm") -> StatusAnalyzer:
    """工厂函数（默认 LLM）"""
    if analyzer_type == "rule":
        from .rule_based import RuleBasedAnalyzer
        return RuleBasedAnalyzer()
    from .llm import LLMAnalyzer
    return LLMAnalyzer()
