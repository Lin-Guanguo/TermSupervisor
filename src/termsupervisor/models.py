"""数据模型定义"""

from dataclasses import dataclass, field, asdict
from collections import deque
from datetime import datetime
from typing import Callable, Awaitable, TYPE_CHECKING, List

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


@dataclass
class ChangeRecord:
    """队列变化记录"""
    timestamp: datetime           # 创建时间
    updated_at: datetime          # 最后更新时间
    content_hash: str             # 内容 hash（清洗后）
    content_snapshot: str         # 内容快照（清洗后）
    diff_summary: str             # 变化摘要（与 [-2] 的差异）
    changed_lines: int            # 与 [-2] 的变化行数


class PaneChangeQueue:
    """Pane 变化历史队列

    核心逻辑:
    - 每秒更新 queue[-1]
    - 页面刷新: 当前 vs last_render_content (阈值 5行 或 10s超时)
    - 队列新增: queue[-1] vs queue[-2] (阈值 20行)

    两个独立判断，两个不同的对比基准
    """

    def __init__(self, session_id: str):
        from termsupervisor import config

        self.session_id = session_id
        self._records: List[ChangeRecord] = []

        # 刷新相关状态
        self._last_render_content: str = ""      # 上次渲染的内容
        self._last_render_time: datetime | None = None  # 上次渲染时间

        # 配置
        self._max_size = config.QUEUE_MAX_SIZE
        self._refresh_lines = config.QUEUE_REFRESH_LINES
        self._new_record_lines = config.QUEUE_NEW_RECORD_LINES
        self._flush_timeout = config.QUEUE_FLUSH_TIMEOUT

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
        from termsupervisor.analysis.content_cleaner import ContentCleaner

        now = datetime.now()
        cleaned_content = ContentCleaner.clean_content_str(content)
        content_hash = ContentCleaner.content_hash(content)

        # === 队列为空: 初始化 ===
        if len(self._records) == 0:
            self._init_queue(now, content_hash, cleaned_content)
            return True

        # === Step 1: 更新 queue[-1] ===
        self._update_tail(now, content_hash, cleaned_content)

        # === Step 2: 判断是否刷新页面 ===
        should_refresh = self._check_should_refresh(cleaned_content, now)

        if should_refresh:
            self._last_render_content = cleaned_content
            self._last_render_time = now

        # === Step 3: 判断是否新增队列记录 ===
        self._check_should_push(now, content_hash, cleaned_content)

        return should_refresh

    def _init_queue(self, now: datetime, content_hash: str, cleaned_content: str):
        """初始化: push 两条相同记录"""
        record = ChangeRecord(
            timestamp=now,
            updated_at=now,
            content_hash=content_hash,
            content_snapshot=cleaned_content,
            diff_summary="(initial)",
            changed_lines=0,
        )
        # 添加两条相同记录
        self._records.append(record)
        self._records.append(ChangeRecord(
            timestamp=now,
            updated_at=now,
            content_hash=content_hash,
            content_snapshot=cleaned_content,
            diff_summary="(initial)",
            changed_lines=0,
        ))
        self._last_render_content = cleaned_content
        self._last_render_time = now

    def _update_tail(self, now: datetime, content_hash: str, cleaned_content: str):
        """更新队尾 (每秒都执行)"""
        tail = self._records[-1]
        tail.updated_at = now
        tail.content_hash = content_hash
        tail.content_snapshot = cleaned_content

    def _check_should_refresh(self, cleaned_content: str, now: datetime) -> bool:
        """判断是否刷新页面

        对比: 当前内容 vs last_render_content
        条件 (OR):
        - 变化 >= 5行 (中等变化)
        - 有变化 且 距上次刷新 >= 10s (兜底)
        """
        from termsupervisor.analysis.content_cleaner import ContentCleaner

        changed_lines, _ = ContentCleaner.diff_lines(
            self._last_render_content, cleaned_content
        )

        if changed_lines == 0:
            return False

        # 中等变化
        if changed_lines >= self._refresh_lines:
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
            new_record = ChangeRecord(
                timestamp=now,
                updated_at=now,
                content_hash=content_hash,
                content_snapshot=cleaned_content,
                diff_summary=diff_summary,
                changed_lines=changed_lines,
            )
            self._records.append(new_record)
            self._trim()

    def _make_summary(self, diff_details: List[str]) -> str:
        """生成变化摘要"""
        # 取前 3 行新增内容
        added_lines = [l[1:] for l in diff_details if l.startswith('+')][:3]
        return ' | '.join(added_lines) if added_lines else "(no summary)"

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

    def get_recent(self, n: int = 5) -> List[ChangeRecord]:
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
