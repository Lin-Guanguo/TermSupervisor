"""Terminal Adapters 模块

提供终端适配器数据结构：
- LayoutData, WindowInfo, TabInfo, PaneInfo: 布局数据结构（定义在 iterm2/models.py）
"""

from .iterm2.models import (
    LayoutData,
    PaneInfo,
    TabInfo,
    WindowInfo,
)

__all__ = [
    "LayoutData",
    "WindowInfo",
    "TabInfo",
    "PaneInfo",
]
