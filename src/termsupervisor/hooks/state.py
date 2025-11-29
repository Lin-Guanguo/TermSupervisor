"""状态数据结构定义"""

from dataclasses import dataclass, field
from datetime import datetime

from ..analysis.base import TaskStatus
from ..config import STATE_HISTORY_MAX_LENGTH


@dataclass
class StateHistoryEntry:
    """状态变化历史条目

    用于记录状态转换历史，便于排查问题。
    """
    status: TaskStatus
    signal: str              # 触发此状态的信号
    success: bool = True     # 是否成功转换（False 表示无匹配规则）
    timestamp: datetime = field(default_factory=datetime.now)

    def __str__(self) -> str:
        ts = self.timestamp.strftime("%H:%M:%S")
        mark = "✓" if self.success else "✗"
        return f"{ts} | {mark} {self.signal} → {self.status.value}"


@dataclass
class PaneState:
    """Pane 状态

    每个 pane 维护一个状态实例，包含当前状态和变化历史。

    Attributes:
        status: 当前状态
        source: 状态来源 (shell, claude-code, user, timer, render)
        description: 状态描述，hover 显示
        updated_at: 状态更新时间
        started_at: RUNNING 开始时间，用于计算 LONG_RUNNING
        history: 状态变化历史队列
    """
    status: TaskStatus
    source: str
    description: str = ""
    updated_at: datetime = field(default_factory=datetime.now)
    started_at: datetime | None = None
    history: list[StateHistoryEntry] = field(default_factory=list)

    def add_history(self, signal: str, success: bool = True) -> None:
        """添加历史记录

        Args:
            signal: 触发信号
            success: 是否成功转换，False 表示无匹配规则
        """
        self.history.append(StateHistoryEntry(
            status=self.status,
            signal=signal,
            success=success
        ))
        # 限制队列长度
        if len(self.history) > STATE_HISTORY_MAX_LENGTH:
            self.history = self.history[-STATE_HISTORY_MAX_LENGTH:]

    def get_history_log(self) -> str:
        """获取历史日志（用于调试）

        Returns:
            格式化的历史日志字符串
        """
        if not self.history:
            return "  (no history)"
        return "\n".join(f"  {entry}" for entry in self.history)

    def copy_with(
        self,
        status: TaskStatus | None = None,
        source: str | None = None,
        description: str | None = None,
        started_at: datetime | None = ...,  # type: ignore
    ) -> "PaneState":
        """创建带有部分更新的副本

        Args:
            status: 新状态，None 保持原值
            source: 新来源，None 保持原值
            description: 新描述，None 保持原值
            started_at: 新开始时间，... 保持原值，None 清除

        Returns:
            新的 PaneState 实例，保留历史队列引用
        """
        return PaneState(
            status=status if status is not None else self.status,
            source=source if source is not None else self.source,
            description=description if description is not None else self.description,
            updated_at=datetime.now(),
            started_at=self.started_at if started_at is ... else started_at,
            history=self.history,  # 共享历史队列
        )

    def to_dict(self) -> dict:
        """转换为字典（用于序列化）"""
        return {
            "status": self.status.value,
            "source": self.source,
            "description": self.description,
            "updated_at": self.updated_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "history_count": len(self.history),
        }

    @classmethod
    def idle(cls, source: str = "shell") -> "PaneState":
        """创建 IDLE 状态实例"""
        return cls(status=TaskStatus.IDLE, source=source)
