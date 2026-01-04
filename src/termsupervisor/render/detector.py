"""变化检测器

检测 pane 内容变化，决定是否需要刷新 SVG。
"""

from datetime import datetime

from termsupervisor import config
from termsupervisor.analysis import ContentCleaner


class ChangeDetector:
    """变化检测器

    负责：
    - 检测内容变化
    - 决定是否需要刷新 SVG（基于阈值和超时）
    - 维护防抖状态
    """

    def __init__(
        self,
        refresh_lines: int | None = None,
        waiting_refresh_lines: int | None = None,
        flush_timeout: float | None = None,
    ):
        self._refresh_lines = refresh_lines or config.QUEUE_REFRESH_LINES
        self._waiting_refresh_lines = waiting_refresh_lines or config.WAITING_REFRESH_LINES
        self._flush_timeout = flush_timeout or config.QUEUE_FLUSH_TIMEOUT

        # 每个 pane 的最后渲染状态
        self._last_render_content: dict[str, str] = {}
        self._last_render_time: dict[str, datetime] = {}

    def should_refresh(
        self,
        pane_id: str,
        cleaned_content: str,
        is_waiting: bool = False,
    ) -> bool:
        """判断是否需要刷新 SVG

        条件 (OR):
        - 变化 >= threshold (WAITING 时 1行，否则 5行)
        - 有变化 且 距上次刷新 >= 10s (兜底)

        Args:
            pane_id: pane ID
            cleaned_content: 清洗后的内容
            is_waiting: 是否处于 WAITING 状态（更敏感）

        Returns:
            是否需要刷新
        """
        now = datetime.now()
        last_content = self._last_render_content.get(pane_id, "")
        last_time = self._last_render_time.get(pane_id)

        # 首次渲染
        if pane_id not in self._last_render_content:
            return True

        # 计算变化行数
        changed_lines, _ = ContentCleaner.diff_lines(last_content, cleaned_content)

        if changed_lines == 0:
            return False

        # 根据状态选择阈值
        threshold = self._waiting_refresh_lines if is_waiting else self._refresh_lines

        # 超过阈值
        if changed_lines >= threshold:
            return True

        # 兜底: 有变化且超时
        if last_time:
            elapsed = (now - last_time).total_seconds()
            if elapsed >= self._flush_timeout:
                return True

        return False

    def mark_rendered(self, pane_id: str, cleaned_content: str) -> None:
        """标记 pane 已渲染"""
        self._last_render_content[pane_id] = cleaned_content
        self._last_render_time[pane_id] = datetime.now()

    def remove_pane(self, pane_id: str) -> None:
        """移除 pane 的检测状态"""
        self._last_render_content.pop(pane_id, None)
        self._last_render_time.pop(pane_id, None)

    def get_last_render_content(self, pane_id: str) -> str | None:
        """获取上次渲染的内容"""
        return self._last_render_content.get(pane_id)

    def get_last_render_time(self, pane_id: str) -> datetime | None:
        """获取上次渲染时间"""
        return self._last_render_time.get(pane_id)
