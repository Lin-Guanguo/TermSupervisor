"""内容变化队列

用于 Supervisor 内容节流的数据结构。
"""

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..iterm.client import JobMetadata
    from ..pane import TaskStatus


@dataclass
class PaneChange:
    """单次变化记录"""

    timestamp: datetime
    change_type: str  # "significant" | "minor" | "thinking"
    diff_lines: list[str]  # 原始 diff 行
    diff_summary: str  # 变化摘要（截取关键行）
    last_n_lines: list[str]  # 屏幕最后 N 行
    changed_line_count: int  # 变化行数
    # Content heuristic fields (Phase 2)
    newline_count: int = 0  # Number of newlines in cleaned tail
    burst_length: int = 0  # Char count increase since last record


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

    # Job metadata (for whitelist matching and tooltip display)
    job: "JobMetadata | None" = None

    def add_change(self, change: PaneChange) -> None:
        """添加变化记录"""
        self.changes.append(change)

    def get_thinking_duration(self) -> float:
        """获取思考时长（秒）"""
        if self.is_thinking and self.thinking_since:
            return (datetime.now() - self.thinking_since).total_seconds()
        return 0.0


@dataclass
class ChangeRecord:
    """队列变化记录"""

    timestamp: datetime  # 创建时间
    updated_at: datetime  # 最后更新时间
    content_hash: str  # 内容 hash（清洗后）
    content_snapshot: str  # 内容快照（清洗后）
    diff_summary: str  # 变化摘要（与 [-2] 的差异）
    changed_lines: int  # 与 [-2] 的变化行数
    # Content heuristic fields (Phase 2)
    newline_count: int = 0  # Line count in cleaned content
    char_count: int = 0  # Char count in cleaned content (for burst calc)
    raw_tail: str = ""  # Raw (uncleaned) last N lines for heuristic pattern matching


class PaneChangeQueue:
    """Pane 变化历史队列

    核心逻辑:
    - 每秒更新 queue[-1]
    - 页面刷新: 当前 vs last_render_content (阈值 5行 或 10s超时)
    - 队列新增: queue[-1] vs queue[-2] (阈值 20行)
    - WAITING 状态下刷新阈值更低（1行）

    两个独立判断，两个不同的对比基准
    """

    def __init__(self, session_id: str):
        from termsupervisor import config

        self.session_id = session_id
        self._records: list[ChangeRecord] = []

        # 刷新相关状态
        self._last_render_content: str = ""  # 上次渲染的内容
        self._last_render_time: datetime | None = None  # 上次渲染时间

        # 配置
        self._max_size = config.QUEUE_MAX_SIZE
        self._refresh_lines = config.QUEUE_REFRESH_LINES
        self._waiting_refresh_lines = config.WAITING_REFRESH_LINES
        self._new_record_lines = config.QUEUE_NEW_RECORD_LINES
        self._flush_timeout = config.QUEUE_FLUSH_TIMEOUT

        # 状态感知
        self._is_waiting = False  # 外部设置，用于降低刷新阈值

        # Heuristic quiet tracking (independent of record push)
        self._last_change_at: datetime | None = None  # When content hash last changed
        self._last_hash: str = ""  # Previous hash for change detection

    def set_waiting(self, is_waiting: bool) -> None:
        """设置 WAITING 状态（影响刷新阈值）"""
        self._is_waiting = is_waiting

    def check_and_record(self, content: str) -> bool:
        """检查变化并记录

        流程:
        1. 队列空 → 初始化 (push 两条相同记录)
        2. 更新 queue[-1] (每次都更新队尾)
        3. 判断页面刷新 (当前 vs last_render_content)
        4. 判断队列新增 (queue[-1] vs queue[-2])

        Args:
            content: 原始终端内容

        Returns:
            是否应触发 SVG 刷新
        """
        from termsupervisor import config
        from termsupervisor.analysis.content_cleaner import ContentCleaner

        now = datetime.now()
        cleaned_content = ContentCleaner.clean_content_str(content)
        content_hash = ContentCleaner.content_hash(content)
        # Store raw tail for heuristic pattern matching
        raw_lines = content.split("\n")
        raw_tail = "\n".join(raw_lines[-config.SCREEN_LAST_N_LINES :])

        # === 队列为空: 初始化 ===
        if len(self._records) == 0:
            self._init_queue(now, content_hash, cleaned_content, raw_tail)
            return True

        # === Step 1: 更新 queue[-1] ===
        self._update_tail(now, content_hash, cleaned_content, raw_tail)

        # === Step 2: 判断是否刷新页面 ===
        should_refresh = self._check_should_refresh(cleaned_content, now)

        if should_refresh:
            self._last_render_content = cleaned_content
            self._last_render_time = now

        # === Step 3: 判断是否新增队列记录 ===
        self._check_should_push(now, content_hash, cleaned_content)

        return should_refresh

    def _init_queue(self, now: datetime, content_hash: str, cleaned_content: str, raw_tail: str):
        """初始化: push 两条相同记录"""
        newline_count = cleaned_content.count("\n") + 1 if cleaned_content else 0
        char_count = len(cleaned_content)
        record = ChangeRecord(
            timestamp=now,
            updated_at=now,
            content_hash=content_hash,
            content_snapshot=cleaned_content,
            diff_summary="(initial)",
            changed_lines=0,
            newline_count=newline_count,
            char_count=char_count,
            raw_tail=raw_tail,
        )
        # 添加两条相同记录
        self._records.append(record)
        self._records.append(
            ChangeRecord(
                timestamp=now,
                updated_at=now,
                content_hash=content_hash,
                content_snapshot=cleaned_content,
                diff_summary="(initial)",
                changed_lines=0,
                newline_count=newline_count,
                char_count=char_count,
                raw_tail=raw_tail,
            )
        )
        self._last_render_content = cleaned_content
        self._last_render_time = now
        # Initialize heuristic tracking
        self._last_change_at = now
        self._last_hash = content_hash

    def _update_tail(self, now: datetime, content_hash: str, cleaned_content: str, raw_tail: str):
        """更新队尾 (每秒都执行)"""
        tail = self._records[-1]
        tail.updated_at = now
        tail.content_hash = content_hash
        tail.content_snapshot = cleaned_content
        # Update heuristic metrics
        tail.newline_count = cleaned_content.count("\n") + 1 if cleaned_content else 0
        tail.char_count = len(cleaned_content)
        tail.raw_tail = raw_tail

        # Track content changes for heuristic quiet detection
        if content_hash != self._last_hash:
            self._last_change_at = now
            self._last_hash = content_hash

    def _check_should_refresh(self, cleaned_content: str, now: datetime) -> bool:
        """判断是否刷新页面

        对比: 当前内容 vs last_render_content
        条件 (OR):
        - 变化 >= threshold (WAITING 时 1行，否则 5行)
        - 有变化 且 距上次刷新 >= 10s (兜底)
        """
        from termsupervisor.analysis.content_cleaner import ContentCleaner

        changed_lines, _ = ContentCleaner.diff_lines(self._last_render_content, cleaned_content)

        if changed_lines == 0:
            return False

        # 根据状态选择阈值
        threshold = self._waiting_refresh_lines if self._is_waiting else self._refresh_lines

        # 中等变化（WAITING 时更敏感）
        if changed_lines >= threshold:
            return True

        # 兜底: 有变化且超时
        if self._last_render_time:
            elapsed = (now - self._last_render_time).total_seconds()
            if elapsed >= self._flush_timeout:
                return True

        return False

    def _check_should_push(self, now: datetime, content_hash: str, cleaned_content: str):
        """判断是否新增队列记录

        对比: queue[-1] vs queue[-2]
        条件: 变化 >= 20行 (大变化)
        """
        from termsupervisor.analysis.content_cleaner import ContentCleaner

        if len(self._records) < 2:
            return

        base = self._records[-2]
        tail = self._records[-1]

        changed_lines, diff_details = ContentCleaner.diff_lines(
            base.content_snapshot, tail.content_snapshot
        )

        if changed_lines >= self._new_record_lines:
            # push 新记录，当前 tail 变成 base
            diff_summary = self._make_summary(diff_details)
            newline_count = cleaned_content.count("\n") + 1 if cleaned_content else 0
            char_count = len(cleaned_content)
            new_record = ChangeRecord(
                timestamp=now,
                updated_at=now,
                content_hash=content_hash,
                content_snapshot=cleaned_content,
                diff_summary=diff_summary,
                changed_lines=changed_lines,
                newline_count=newline_count,
                char_count=char_count,
            )
            self._records.append(new_record)
            self._trim()

    def _make_summary(self, diff_details: list[str]) -> str:
        """生成变化摘要"""
        # 取前 3 行新增内容
        added_lines = [line[1:] for line in diff_details if line.startswith("+")][:3]
        return " | ".join(added_lines) if added_lines else "(no summary)"

    def _trim(self):
        """裁剪队列到最大长度"""
        while len(self._records) > self._max_size:
            self._records.pop(0)

    # === 随机访问接口 ===

    def __getitem__(self, index: int) -> ChangeRecord:
        """支持 queue[-1], queue[-2], queue[0] 等访问"""
        return self._records[index]

    def __len__(self) -> int:
        """队列长度"""
        return len(self._records)

    @property
    def tail(self) -> ChangeRecord | None:
        """队尾 (最新)"""
        return self._records[-1] if self._records else None

    @property
    def base(self) -> ChangeRecord | None:
        """对比基准 (倒数第二)"""
        return self._records[-2] if len(self._records) >= 2 else None

    def get_recent(self, n: int = 5) -> list[ChangeRecord]:
        """获取最近 n 条"""
        return self._records[-n:] if self._records else []

    @property
    def last_render_content(self) -> str:
        """上次渲染的内容"""
        return self._last_render_content

    @property
    def last_render_time(self) -> datetime | None:
        """上次渲染时间"""
        return self._last_render_time

    # === Heuristic helper methods ===

    def get_newline_delta(self) -> int:
        """Get newline count change between base and tail (for heuristic_run gate)"""
        if len(self._records) < 2:
            return 0
        return self._records[-1].newline_count - self._records[-2].newline_count

    def get_burst_length(self) -> int:
        """Get char count increase between base and tail (for heuristic_run gate)"""
        if len(self._records) < 2:
            return 0
        delta = self._records[-1].char_count - self._records[-2].char_count
        return max(0, delta)

    def get_tail_lines(self, n: int = 5, raw: bool = True) -> list[str]:
        """Get last N lines from tail content

        Args:
            n: Number of lines to return
            raw: If True, use raw (uncleaned) content for pattern matching.
                 If False, use cleaned content.
        """
        if not self._records:
            return []
        if raw:
            content = self._records[-1].raw_tail
        else:
            content = self._records[-1].content_snapshot
        if not content:
            return []
        lines = content.split("\n")
        return lines[-n:] if len(lines) >= n else lines

    def get_quiet_duration(self) -> float:
        """Get seconds since last content change (for quiet thresholds)

        Uses dedicated _last_change_at tracking, independent of record push.
        This ensures small updates still age into quiet periods.
        """
        if self._last_change_at is None:
            return 0.0
        return (datetime.now() - self._last_change_at).total_seconds()

    def is_hash_stable(self) -> bool:
        """Check if content has been stable (no changes since last check)

        Uses dedicated hash tracking for accurate quiet detection.
        """
        if not self._records:
            return False
        current_hash = self._records[-1].content_hash
        return current_hash == self._last_hash
