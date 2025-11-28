"""数据模型定义"""

from dataclasses import dataclass, field, asdict
from collections import deque
from datetime import datetime
from typing import Callable, Awaitable, TYPE_CHECKING

if TYPE_CHECKING:
    from .analysis.base import TaskStatus


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


@dataclass
class PaneChange:
    """单次变化记录"""
    timestamp: datetime
    change_type: str  # "significant" | "minor" | "thinking"
    diff_lines: list[str]  # 原始 diff 行
    diff_summary: str  # 变化摘要（截取关键行）
    last_n_lines: list[str]  # 屏幕最后 N 行
    changed_line_count: int  # 变化行数


@dataclass
class PaneHistory:
    """Pane 历史记录 - 用于状态分析"""
    session_id: str
    pane_name: str
    changes: deque = field(default_factory=lambda: deque(maxlen=10))

    # 当前状态（由 Analyzer 更新）
    current_status: "TaskStatus | None" = None
    status_reason: str = ""
    last_analysis: datetime | None = None

    # 思考状态跟踪
    is_thinking: bool = False
    thinking_since: datetime | None = None

    def add_change(self, change: PaneChange) -> None:
        """添加变化记录"""
        self.changes.append(change)

    def get_thinking_duration(self) -> float:
        """获取思考时长（秒）"""
        if self.is_thinking and self.thinking_since:
            return (datetime.now() - self.thinking_since).total_seconds()
        return 0.0
