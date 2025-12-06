"""变化清洗器：判断是否值得调用 LLM"""

import difflib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .change_queue import PaneChange, PaneHistory

# 思考符号（Claude Code 等 AI 工具）
THINKING_SYMBOLS = {"✽", "✳", "✶", "✢", "✻", "·", "⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"}


class ChangeCleaner:
    """变化清洗器：判断是否值得调用 LLM（节省 API 成本）"""

    def __init__(
        self,
        min_changed_lines: int = 3,
        similarity_threshold: float = 0.9,
        debounce_seconds: float = 5.0,
    ):
        self.min_changed_lines = min_changed_lines
        self.similarity_threshold = similarity_threshold
        self.debounce_seconds = debounce_seconds

    def should_analyze(self, pane: "PaneHistory") -> tuple[bool, str]:
        """
        判断是否应该调用 LLM 分析
        返回: (是否分析, 原因)
        """
        if not pane.changes:
            return False, "no_changes"

        last_change = pane.changes[-1]

        # 1. 变化行数太少，跳过
        if last_change.changed_line_count < self.min_changed_lines:
            return False, "too_few_lines"

        # 2. 只有思考符号在变（spinner），跳过
        if self._is_only_thinking_spinner(last_change):
            # 更新 thinking 状态
            pane.is_thinking = True
            if pane.thinking_since is None:
                pane.thinking_since = last_change.timestamp
            return False, "thinking_spinner"

        # 3. 与上次变化太相似，跳过
        if len(pane.changes) >= 2:
            prev_change = pane.changes[-2]
            if self._is_similar(prev_change, last_change):
                return False, "too_similar"

        # 4. 距离上次分析时间太短（防抖）
        if pane.last_analysis:
            elapsed = (last_change.timestamp - pane.last_analysis).total_seconds()
            if elapsed < self.debounce_seconds:
                return False, "too_frequent"

        # 有实质性变化，重置 thinking 状态
        pane.is_thinking = False
        pane.thinking_since = None

        return True, "should_analyze"

    def _is_only_thinking_spinner(self, change: "PaneChange") -> bool:
        """检查是否只有思考符号在变"""
        if change.changed_line_count > 2:
            return False

        # 检查 diff 中是否只有符号变化
        for line in change.diff_lines:
            if line.startswith("+") or line.startswith("-"):
                content = line[1:].strip()
                # 如果行内容除了符号外还有实质变化，返回 False
                has_thinking_symbol = any(sym in content for sym in THINKING_SYMBOLS)
                has_thinking_keyword = (
                    "Thinking" in content
                    or "Contemplating" in content
                    or "esc to interrupt" in content
                )
                if not (has_thinking_symbol or has_thinking_keyword):
                    # 有其他内容变化
                    if len(content) > 10:
                        return False
        return True

    def _is_similar(self, prev: "PaneChange", curr: "PaneChange") -> bool:
        """检查两次变化是否太相似"""
        ratio = difflib.SequenceMatcher(None, prev.diff_summary, curr.diff_summary).ratio()
        return ratio > self.similarity_threshold
