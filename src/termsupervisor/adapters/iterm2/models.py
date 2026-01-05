"""iTerm2 Layout 数据模型

布局相关的 DTO：Window, Tab, Pane, Layout。
"""

from dataclasses import asdict, dataclass, field


@dataclass
class PaneInfo:
    """Pane 信息"""

    pane_id: str  # renamed from session_id for consistency
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
    updated_panes: list[str] = field(default_factory=list)  # renamed from updated_sessions
    active_pane_id: str | None = None  # renamed from active_session_id

    def to_dict(self) -> dict:
        """转换为字典"""
        return asdict(self)
