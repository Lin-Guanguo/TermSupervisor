"""Render Pipeline 数据类型

统一的数据类型，用于 Render Pipeline 各模块之间的通信。
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from termsupervisor.adapters.iterm2.client import JobMetadata
    from termsupervisor.adapters.iterm2.models import LayoutData


@dataclass
class ContentSnapshot:
    """Pane 内容快照"""

    pane_id: str
    content: str
    content_hash: str
    cleaned_content: str
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class PaneState:
    """Pane 完整状态

    包含内容快照、渲染控制、Job metadata 等信息。
    """

    pane_id: str
    name: str

    # 最新内容
    current: ContentSnapshot

    # 渲染控制
    last_render: ContentSnapshot | None = None
    last_render_at: datetime | None = None

    # Job metadata (用于 tooltip)
    job: "JobMetadata | None" = None

    # 状态标记
    is_waiting: bool = False


@dataclass
class LayoutUpdate:
    """布局更新通知

    用于通知订阅者布局发生了变化。
    """

    layout: "LayoutData"
    updated_panes: list[str] = field(default_factory=list)  # 需要刷新 SVG 的 pane_id 列表
    pane_states: dict[str, PaneState] = field(default_factory=dict)
