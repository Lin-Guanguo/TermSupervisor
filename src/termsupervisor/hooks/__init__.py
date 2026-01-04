"""Hook 系统 - 接收外部工具状态事件

模块结构：
- manager: HookManager 门面（主入口）
- receiver: HookReceiver HTTP 接收器
- sources/: 各类 Hook 源

类型重导出：
- TaskStatus, HookEvent 等类型统一从 state 模块导出
"""

# 主模块
# 统一类型（从 state 模块重导出）
from ..state import HookEvent, TaskStatus
from .manager import HookManager
from .receiver import HookReceiver
from .sources.base import HookSource

__all__ = [
    # 主模块
    "HookManager",
    "HookReceiver",
    "HookSource",
    # 类型
    "TaskStatus",
    "HookEvent",
]
