"""Terminal Adapters 模块

提供终端适配器接口和数据结构：
- TerminalAdapter: 适配器协议
- JobMetadata: 进程元数据
- LayoutData, WindowInfo, TabInfo, PaneInfo: 布局数据结构
"""

from .base import JobMetadata, TerminalAdapter
from .iterm2.models import (
    LayoutData,
    PaneInfo,
    TabInfo,
    WindowInfo,
)

__all__ = [
    # Protocol
    "TerminalAdapter",
    "JobMetadata",
    # Layout models
    "LayoutData",
    "WindowInfo",
    "TabInfo",
    "PaneInfo",
]
