"""状态分析器基类和状态枚举"""

from abc import ABC, abstractmethod
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..models import PaneHistory


class TaskStatus(Enum):
    """任务状态枚举"""
    UNKNOWN = "unknown"
    IDLE = "idle"
    RUNNING = "running"
    THINKING = "thinking"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"

    @property
    def needs_notification(self) -> bool:
        """是否需要通知用户"""
        return self in {
            TaskStatus.WAITING_APPROVAL,
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.INTERRUPTED,
        }

    @property
    def color(self) -> str:
        """状态对应的颜色"""
        colors = {
            TaskStatus.UNKNOWN: "gray",
            TaskStatus.IDLE: "gray",
            TaskStatus.RUNNING: "blue",
            TaskStatus.THINKING: "purple",
            TaskStatus.WAITING_APPROVAL: "yellow",
            TaskStatus.COMPLETED: "green",
            TaskStatus.FAILED: "red",
            TaskStatus.INTERRUPTED: "orange",
        }
        return colors.get(self, "gray")


class StatusAnalyzer(ABC):
    """状态分析器基类"""

    @abstractmethod
    async def analyze(self, pane: "PaneHistory") -> TaskStatus:
        """分析 pane 状态"""
        pass

    @abstractmethod
    def should_analyze(self, pane: "PaneHistory") -> bool:
        """判断是否需要分析"""
        pass
