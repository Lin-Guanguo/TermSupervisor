"""数据模型定义"""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Callable, Awaitable


@dataclass
class PaneInfo:
    """Pane 信息"""
    session_id: str
    name: str
    index: int
    x: float
    y: float
    width: float
    height: float


@dataclass
class TabInfo:
    """Tab 信息"""
    tab_id: str
    name: str
    panes: list[PaneInfo] = field(default_factory=list)


@dataclass
class WindowInfo:
    """Window 信息"""
    window_id: str
    name: str
    x: float
    y: float
    width: float
    height: float
    tabs: list[TabInfo] = field(default_factory=list)


@dataclass
class LayoutData:
    """完整布局数据"""
    windows: list[WindowInfo] = field(default_factory=list)
    updated_sessions: list[str] = field(default_factory=list)
    active_session_id: str | None = None  # 当前 focus 的 session

    def to_dict(self) -> dict:
        """转换为字典"""
        return asdict(self)


@dataclass
class PaneSnapshot:
    """Pane 内容快照"""
    session_id: str
    index: int
    content: str
    updated_at: datetime = field(default_factory=datetime.now)


# 更新回调类型
UpdateCallback = Callable[[LayoutData], Awaitable[None]]
