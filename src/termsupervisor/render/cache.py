"""布局和内容缓存

管理布局数据和 pane 内容快照的缓存。
"""

from datetime import datetime
from typing import TYPE_CHECKING

from termsupervisor.adapters.iterm2.models import LayoutData, PaneSnapshot

if TYPE_CHECKING:
    from termsupervisor.adapters.iterm2.client import JobMetadata

from .types import ContentSnapshot, PaneState


class LayoutCache:
    """布局和内容缓存

    维护：
    - 当前布局 (layout)
    - Pane 内容快照 (snapshots)
    - Pane 状态 (pane_states)
    """

    def __init__(self):
        self.layout: LayoutData = LayoutData()
        self.snapshots: dict[str, PaneSnapshot] = {}
        self.pane_states: dict[str, PaneState] = {}

    def update_layout(self, layout: LayoutData) -> None:
        """更新布局数据"""
        self.layout = layout

    def update_pane_state(
        self,
        pane_id: str,
        name: str,
        content: str,
        content_hash: str,
        cleaned_content: str,
        job: "JobMetadata | None" = None,
        is_waiting: bool = False,
    ) -> PaneState:
        """更新或创建 pane 状态"""
        now = datetime.now()
        current_snapshot = ContentSnapshot(
            pane_id=pane_id,
            content=content,
            content_hash=content_hash,
            cleaned_content=cleaned_content,
            timestamp=now,
        )

        if pane_id in self.pane_states:
            state = self.pane_states[pane_id]
            state.name = name
            state.current = current_snapshot
            state.job = job
            state.is_waiting = is_waiting
        else:
            state = PaneState(
                pane_id=pane_id,
                name=name,
                current=current_snapshot,
                job=job,
                is_waiting=is_waiting,
            )
            self.pane_states[pane_id] = state

        return state

    def mark_rendered(self, pane_id: str) -> None:
        """标记 pane 已渲染"""
        if pane_id in self.pane_states:
            state = self.pane_states[pane_id]
            state.last_render = state.current
            state.last_render_at = datetime.now()

    def get_snapshot(self, pane_id: str) -> PaneSnapshot | None:
        """获取 pane 内容快照"""
        return self.snapshots.get(pane_id)

    def get_pane_state(self, pane_id: str) -> PaneState | None:
        """获取 pane 状态"""
        return self.pane_states.get(pane_id)

    def remove_pane(self, pane_id: str) -> None:
        """移除 pane 相关数据"""
        self.snapshots.pop(pane_id, None)
        self.pane_states.pop(pane_id, None)

    def get_current_pane_ids(self) -> set[str]:
        """获取当前布局中的所有 pane ID"""
        return {
            pane.pane_id
            for window in self.layout.windows
            for tab in window.tabs
            for pane in tab.panes
        }

    def cleanup_closed_panes(self) -> list[str]:
        """清理已关闭的 pane，返回被清理的 pane ID 列表"""
        current_ids = self.get_current_pane_ids()
        # Check both snapshots and pane_states for closed panes
        cached_ids = set(self.snapshots.keys()) | set(self.pane_states.keys())
        closed_ids = cached_ids - current_ids

        for pane_id in closed_ids:
            self.remove_pane(pane_id)

        return list(closed_ids)
