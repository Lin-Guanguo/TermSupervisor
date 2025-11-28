"""规则引擎分析器 - 基于模式匹配检测终端状态"""

import re
from datetime import datetime
from typing import TYPE_CHECKING

from .base import StatusAnalyzer, TaskStatus
from .cleaner import ChangeCleaner
from .. import config

if TYPE_CHECKING:
    from ..models import PaneHistory


# === 模式定义 ===

# Shell prompt 模式（行尾）
PROMPT_PATTERNS = [
    r'[$%>❯›»]\s*$',           # 常见 prompt 结尾
    r'\$\s*$',                  # bash $
    r'%\s*$',                   # zsh %
    r'>\s*$',                   # 通用 >
    r'❯\s*$',                   # oh-my-zsh
    r'›\s*$',                   # fish
    r'#\s*$',                   # root #
]

# 思考状态模式
THINKING_SYMBOLS = {'✽', '✳', '✶', '✢', '✻', '·', '⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏'}
THINKING_KEYWORDS = [
    'Thinking', 'Contemplating', 'Pondering', 'Mulling',
    'esc to interrupt', 'ctrl+c to cancel',
    'Stewing', 'Brewing', 'Forging', 'Weaving',
    'Harmonizing', 'Transfiguring', 'Germinating',
    'Razzle-dazzling', 'Gallivanting', 'Schlepping',
    'Quantumizing', 'Prestidigitating', 'Unravelling',
    'Booping', 'Zesting',
]

# 等待审批模式
APPROVAL_PATTERNS = [
    r'\[Y/n\]',                 # [Y/n] 确认
    r'\[y/N\]',                 # [y/N] 确认
    r'Y/n',                     # Y/n
    r'\(y/n\)',                 # (y/n)
    r'Do you want to proceed\?',
    r'Approve',
    r'confirm',
    r'Press Enter to continue',
    r'Continue\?',
    r'Esc to exit',             # Claude Code 选择菜单
    r'❯\s+\d+\.',               # Claude Code 选项列表
]

# 完成状态模式
COMPLETED_PATTERNS = [
    r'✓',                       # 勾选符号
    r'✔',                       # 另一种勾选
    r'⏺',                       # Claude Code 完成标记
    r'\bDone\b',                # Done
    r'\bSuccess\b',             # Success
    r'\bCompleted?\b',          # Complete/Completed
    r'\bFinished\b',            # Finished
    r'successfully',            # successfully
]

# 失败状态模式
FAILED_PATTERNS = [
    r'\bError\b',               # Error
    r'\bERROR\b',               # ERROR
    r'\bFailed\b',              # Failed
    r'\bFAILED\b',              # FAILED
    r'\bException\b',           # Exception
    r'\bTraceback\b',           # Python traceback
    r'exit code [1-9]',         # 非零退出码
    r'command not found',       # 命令未找到
    r'No such file',            # 文件不存在
    r'Permission denied',       # 权限拒绝
]

# 中断状态模式
INTERRUPTED_PATTERNS = [
    r'\^C',                     # Ctrl+C
    r'Interrupted',             # Interrupted
    r'KeyboardInterrupt',       # Python 键盘中断
    r'SIGINT',                  # 信号中断
    r'Aborted',                 # Aborted
    r'Cancelled',               # Cancelled
]


class RuleBasedAnalyzer(StatusAnalyzer):
    """基于规则的状态分析器

    检测优先级（从高到低）：
    1. interrupted - 用户中断
    2. failed - 任务失败
    3. waiting_approval - 等待确认
    4. completed - 任务完成
    5. thinking - AI 思考中
    6. idle - 空闲等待输入
    7. running - 运行中（默认）
    """

    def __init__(self):
        self.cleaner = ChangeCleaner(
            min_changed_lines=config.CLEANER_MIN_CHANGED_LINES,
            similarity_threshold=config.CLEANER_SIMILARITY_THRESHOLD,
            debounce_seconds=config.CLEANER_DEBOUNCE_SECONDS,
        )
        # 编译正则以提高性能
        self._prompt_re = [re.compile(p) for p in PROMPT_PATTERNS]
        self._approval_re = [re.compile(p, re.IGNORECASE) for p in APPROVAL_PATTERNS]
        self._completed_re = [re.compile(p, re.IGNORECASE) for p in COMPLETED_PATTERNS]
        self._failed_re = [re.compile(p) for p in FAILED_PATTERNS]
        self._interrupted_re = [re.compile(p) for p in INTERRUPTED_PATTERNS]

    async def analyze(self, pane: "PaneHistory") -> TaskStatus:
        """分析 pane 状态"""
        if not pane.changes:
            return TaskStatus.UNKNOWN

        last_change = pane.changes[-1]
        lines = last_change.last_n_lines
        diff_lines = last_change.diff_lines

        if not lines:
            return TaskStatus.UNKNOWN

        # 获取最后几行用于分析
        last_lines = lines[-10:]  # 最后 10 行
        last_line = lines[-1].strip() if lines else ""
        content = '\n'.join(last_lines)
        diff_content = '\n'.join(diff_lines)

        # 按优先级检测状态
        status, reason = self._detect_status(last_line, content, diff_content, last_lines)

        # 更新 pane 状态
        pane.last_analysis = datetime.now()
        pane.current_status = status
        pane.status_reason = reason

        # 更新 thinking 状态跟踪
        if status == TaskStatus.THINKING:
            if not pane.is_thinking:
                pane.is_thinking = True
                pane.thinking_since = datetime.now()
        else:
            pane.is_thinking = False
            pane.thinking_since = None

        return status

    def _detect_status(self, last_line: str, content: str, diff_content: str, last_lines: list[str]) -> tuple[TaskStatus, str]:
        """检测状态，返回 (状态, 原因)"""

        # 1. 检测中断
        if self._match_any(self._interrupted_re, diff_content):
            return TaskStatus.INTERRUPTED, "检测到中断信号"

        # 2. 检测失败
        if self._match_any(self._failed_re, diff_content):
            return TaskStatus.FAILED, "检测到错误信息"

        # 3. 检测等待审批（优先级高于完成）
        # 检查最后几行是否有审批提示
        recent_content = '\n'.join(last_lines[-5:])
        if self._match_any(self._approval_re, recent_content):
            return TaskStatus.WAITING_APPROVAL, "等待用户确认"

        # 4. 检测完成（在 diff 中检测，表示刚完成）
        if self._match_any(self._completed_re, diff_content):
            # 排除：如果同时检测到 thinking，说明还在进行中
            if not self._is_thinking(content, last_line):
                return TaskStatus.COMPLETED, "任务已完成"

        # 5. 检测思考状态
        if self._is_thinking(content, last_line):
            return TaskStatus.THINKING, "AI 正在思考"

        # 6. 检测空闲（shell prompt）
        if self._is_idle(last_line):
            return TaskStatus.IDLE, "等待用户输入"

        # 7. 默认：运行中
        return TaskStatus.RUNNING, "命令执行中"

    def _match_any(self, patterns: list[re.Pattern], text: str) -> bool:
        """检查文本是否匹配任一模式"""
        return any(p.search(text) for p in patterns)

    def _is_thinking(self, content: str, last_line: str) -> bool:
        """检测是否处于思考状态"""
        # 检查思考符号
        has_symbol = any(sym in content for sym in THINKING_SYMBOLS)

        # 检查思考关键词
        has_keyword = any(kw.lower() in content.lower() for kw in THINKING_KEYWORDS)

        # 两者都有，或者最后一行包含典型的思考模式
        if has_symbol and has_keyword:
            return True

        # 检查 Claude Code 特有的思考状态行
        # 例如: "✽ Thinking… (esc to interrupt)"
        thinking_line_pattern = r'[✽✳✶✢✻·]\s*\w+.*esc to interrupt'
        if re.search(thinking_line_pattern, last_line, re.IGNORECASE):
            return True

        return False

    def _is_idle(self, last_line: str) -> bool:
        """检测是否处于空闲状态（显示 shell prompt）"""
        # 检查是否是空行或只有空格
        if not last_line.strip():
            return False

        # 检查是否匹配 prompt 模式
        for pattern in self._prompt_re:
            if pattern.search(last_line):
                # 排除：如果行太长，可能不是 prompt
                if len(last_line) < 200:
                    return True

        return False

    def should_analyze(self, pane: "PaneHistory") -> bool:
        """判断是否需要分析"""
        if not pane.changes:
            return False

        # 使用 cleaner 判断，但规则引擎可以更频繁地分析
        should, reason = self.cleaner.should_analyze(pane)

        # 规则引擎成本低，即使 cleaner 说不需要，也可以分析
        # 但至少要有变化
        return len(pane.changes) > 0
