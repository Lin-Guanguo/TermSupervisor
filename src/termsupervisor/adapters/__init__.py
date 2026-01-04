"""Terminal Adapters 模块

提供终端适配器抽象层：
- TerminalAdapter: 终端适配器接口
- LayoutData, WindowInfo, TabInfo, PaneInfo: 布局数据结构
"""

from .base import (
    LayoutData,
    PaneInfo,
    TabInfo,
    TerminalAdapter,
    WindowInfo,
)

__all__ = [
    "TerminalAdapter",
    "LayoutData",
    "WindowInfo",
    "TabInfo",
    "PaneInfo",
]
