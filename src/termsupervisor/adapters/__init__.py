"""Terminal Adapters 模块

提供终端适配器抽象层：
- TerminalAdapter: 终端适配器接口
- LayoutData, WindowInfo, TabInfo, PaneInfo: 布局数据结构（定义在 iterm2/models.py）
"""

from .base import TerminalAdapter
from .iterm2.models import (
    LayoutData,
    PaneInfo,
    TabInfo,
    WindowInfo,
)

__all__ = [
    "TerminalAdapter",
    "LayoutData",
    "WindowInfo",
    "TabInfo",
    "PaneInfo",
]
