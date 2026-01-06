"""Pane 模块数据类型定义

包含：
- HookEvent: 统一事件 DTO
- StateChange: 状态变更记录
- DisplayState: 显示状态
- TransitionRule: 流转规则
- StateHistoryEntry: 历史记录条目
- TypedDict definitions for dict structures
"""

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TypedDict

from ..core.ids import short_id

logger = logging.getLogger(__name__)


class TaskStatus(Enum):
    """任务状态枚举

    状态设计（5 个）：
    - IDLE: 空闲，等待输入
    - RUNNING: 执行中
    - WAITING_APPROVAL: 等待权限确认
    - DONE: 完成待确认
    - FAILED: 失败待确认
    """

    IDLE = "idle"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    DONE = "done"
    FAILED = "failed"

    @property
    def needs_notification(self) -> bool:
        """是否需要通知用户"""
        return self in {
            TaskStatus.WAITING_APPROVAL,
            TaskStatus.DONE,
            TaskStatus.FAILED,
        }

    @property
    def needs_attention(self) -> bool:
        """是否需要用户关注（边框闪烁 + 状态闪烁）"""
        return self in {
            TaskStatus.WAITING_APPROVAL,
            TaskStatus.DONE,
            TaskStatus.FAILED,
        }

    @property
    def is_running(self) -> bool:
        """是否为运行中状态（边框转圈）"""
        return self == TaskStatus.RUNNING

    @property
    def color(self) -> str:
        """状态对应的颜色"""
        colors = {
            TaskStatus.IDLE: "gray",
            TaskStatus.RUNNING: "blue",
            TaskStatus.WAITING_APPROVAL: "yellow",
            TaskStatus.DONE: "green",
            TaskStatus.FAILED: "red",
        }
        return colors.get(self, "gray")

    @property
    def display(self) -> bool:
        """是否需要前端显示"""
        return self != TaskStatus.IDLE


# TypedDict definitions for dict structures


class PaneStatusInfo(TypedDict):
    """Status provider return type.

    Used by StatusProviderCallback in render/pipeline.py.
    """

    status: str  # TaskStatus.value
    status_color: str  # TaskStatus.color
    status_reason: str  # description
    is_running: bool
    needs_notification: bool
    needs_attention: bool
    display: bool


class PaneStatusDisplay(PaneStatusInfo):
    """Extended status info with job metadata.

    Used in get_layout_dict() pane_statuses.
    """

    job_name: str
    path: str


class DisplayStateDict(TypedDict):
    """DisplayState.to_dict() return type.

    Used for WebSocket broadcast.
    """

    status: str
    status_color: str
    source: str
    description: str
    state_id: int
    is_running: bool
    needs_notification: bool
    needs_attention: bool
    display: bool
    running_duration: float
    recently_finished: bool
    quiet_completion: bool


class StateHistoryEntryDict(TypedDict):
    """StateHistoryEntry.to_dict() return type."""

    signal: str
    from_status: str
    to_status: str
    success: bool
    description: str
    timestamp: float


@dataclass
class HookEvent:
    """Hook 事件 - 统一事件 DTO

    所有 Signal Source 产生的事件都转换为此格式。
    由 HookManager 入口统一构造/补全。

    Attributes:
        source: 来源标识 (shell, claude-code, content, iterm, frontend)
        pane_id: iTerm2 session_id
        event_type: 事件类型 (command_start, Stop, content_updated, etc.)
        signal: 完整信号 source.event_type
        data: 事件数据
        timestamp: 事件时间
        pane_generation: pane 代次（用于拒绝旧事件）
    """

    source: str
    pane_id: str
    event_type: str
    signal: str = ""  # 由 HookManager 补全
    data: dict = field(default_factory=dict)
    timestamp: float = 0.0  # 由 HookManager 补全
    pane_generation: int = 0  # 由 HookManager 补全

    def __post_init__(self):
        if not self.signal:
            self.signal = f"{self.source}.{self.event_type}"
        if self.timestamp == 0.0:
            self.timestamp = datetime.now().timestamp()

    def format_log(self) -> str:
        """格式化为日志字符串"""
        ts = datetime.fromtimestamp(self.timestamp).strftime("%H:%M:%S.%f")[:-3]
        pane_short = short_id(self.pane_id)
        return f"[HookEvent] {ts} | {self.source:12} | {pane_short:8} | {self.event_type}"


@dataclass
class StateHistoryEntry:
    """状态变化历史条目

    用于记录状态转换历史，便于排查问题。
    """

    signal: str  # 触发信号
    from_status: TaskStatus  # 原状态
    to_status: TaskStatus  # 新状态
    success: bool = True  # 是否成功转换
    description: str = ""  # 状态描述
    timestamp: float = field(default_factory=lambda: datetime.now().timestamp())

    def __str__(self) -> str:
        ts = datetime.fromtimestamp(self.timestamp).strftime("%H:%M:%S")
        mark = "✓" if self.success else "✗"
        return f"{ts} | {mark} {self.signal} → {self.to_status.value}"

    def to_dict(self) -> StateHistoryEntryDict:
        """转换为可序列化的字典"""
        return StateHistoryEntryDict(
            signal=self.signal,
            from_status=self.from_status.value,
            to_status=self.to_status.value,
            success=self.success,
            description=self.description,
            timestamp=self.timestamp,
        )


@dataclass
class StateChange:
    """状态变更记录

    用于从 StateMachine 传递到 Pane 显示层。

    Attributes:
        old_status: 原状态
        new_status: 新状态
        old_source: 原来源
        new_source: 新来源
        description: 状态描述
        state_id: 状态唯一 ID（自增）
        started_at: 运行开始时间
        running_duration: 运行时长（秒）
    """

    old_status: TaskStatus
    new_status: TaskStatus
    old_source: str
    new_source: str
    description: str
    state_id: int
    started_at: float | None = None
    running_duration: float = 0.0


@dataclass
class DisplayState:
    """显示状态

    Pane 维护的显示层数据，用于 WebSocket 广播。
    """

    status: TaskStatus
    source: str
    description: str
    state_id: int
    started_at: float | None = None
    running_duration: float = 0.0
    recently_finished: bool = False  # 最近完成提示（auto-dismiss 后短暂显示）
    quiet_completion: bool = False  # 静默完成（短任务不闪烁）

    def to_dict(self) -> DisplayStateDict:
        """转换为字典（用于 WebSocket）"""
        return DisplayStateDict(
            status=self.status.value,
            status_color=self.status.color,
            source=self.source,
            description=self.description,
            state_id=self.state_id,
            is_running=self.status.is_running,
            needs_notification=self.status.needs_notification,
            needs_attention=self.status.needs_attention,
            display=self.status.display,
            running_duration=self.running_duration,
            recently_finished=self.recently_finished,
            quiet_completion=self.quiet_completion,
        )


@dataclass
class DisplayUpdate:
    """显示更新 - StateManager 处理事件后的返回值

    用于替代回调机制。StateManager.process_event() 返回此对象，
    HookManager 根据返回值决定是否广播到 WebSocket。

    Attributes:
        pane_id: pane 标识
        display_state: 显示状态数据
        reason: 更新原因（用于调试）
    """

    pane_id: str
    display_state: DisplayState
    reason: str = ""

    def to_dict(self) -> dict:
        """转换为字典（用于 WebSocket 广播）"""
        return {
            "pane_id": self.pane_id,
            "display_state": self.display_state.to_dict(),
            "reason": self.reason,
        }


# 状态快照类型，用于谓词函数
@dataclass
class StateSnapshot:
    """状态快照

    提供给谓词函数访问的当前状态信息。
    """

    status: TaskStatus
    source: str
    state_id: int
    started_at: float | None
    pane_generation: int
    now: float = field(default_factory=lambda: datetime.now().timestamp())


# 谓词函数类型
Predicate = Callable[[HookEvent, StateSnapshot], bool]


@dataclass
class TransitionRule:
    """状态流转规则

    结构化的流转规则定义，支持谓词函数验证。

    Attributes:
        from_status: 原状态集合，None 表示任意状态
        from_source: 原来源，None 表示任意来源，"=" 表示与当前 source 相同
        signal_pattern: 信号模式（如 "shell.command_start"）
        to_status: 目标状态
        to_source: 目标来源，"=" 表示保持原 source
        description_template: 描述模板，支持 {key} 格式化
        reset_started_at: 是否重置开始时间
        predicates: 谓词函数列表，全部满足才匹配
    """

    from_status: set[TaskStatus] | None  # None = any
    from_source: str | None  # None = any, "=" = same as current
    signal_pattern: str
    to_status: TaskStatus
    to_source: str  # "=" = keep current source
    description_template: str
    reset_started_at: bool = True
    preserve_started_at_if_same_source: bool = False  # 同源时保持 started_at
    predicates: list[Predicate] = field(default_factory=list)

    def matches_signal(self, signal: str) -> bool:
        """检查信号是否匹配"""
        return signal == self.signal_pattern

    def matches_from_status(self, status: TaskStatus) -> bool:
        """检查原状态是否匹配"""
        if self.from_status is None:
            return True
        return status in self.from_status

    def matches_from_source(self, current_source: str, event_source: str) -> bool:
        """检查原来源是否匹配"""
        if self.from_source is None:
            return True
        if self.from_source == "=":
            return current_source == event_source
        return current_source == self.from_source

    def check_predicates(self, event: HookEvent, snapshot: StateSnapshot) -> bool:
        """检查所有谓词"""
        for predicate in self.predicates:
            if not predicate(event, snapshot):
                return False
        return True

    def format_description(self, data: dict, max_length: int = 50) -> str:
        """格式化描述，支持截断

        Args:
            data: 事件数据
            max_length: 最大长度

        Returns:
            格式化后的描述
        """
        try:
            # 支持 {key:length} 格式
            result = self.description_template
            for key, value in data.items():
                # 处理 {key:30} 格式
                pattern = rf"\{{{key}:(\d+)\}}"
                match = re.search(pattern, result)
                if match:
                    length = int(match.group(1))
                    truncated = str(value)[:length]
                    # Use lambda to avoid backslash interpretation in replacement
                    result = re.sub(pattern, lambda m: truncated, result)
                else:
                    result = result.replace(f"{{{key}}}", str(value))

            # 整体截断
            if len(result) > max_length:
                result = result[: max_length - 3] + "..."

            return result
        except Exception as e:
            logger.debug(f"Failed to format description template: {e}")
            return self.description_template[:max_length]

    def get_target_source(self, current_source: str) -> str:
        """获取目标来源"""
        if self.to_source == "=":
            return current_source
        return self.to_source
