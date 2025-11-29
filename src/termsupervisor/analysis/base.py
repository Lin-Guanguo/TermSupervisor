"""状态分析器基类和状态枚举"""

from abc import ABC, abstractmethod
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..models import PaneHistory


class TaskStatus(Enum):
    """任务状态枚举

    状态设计（6 个）：
    - IDLE: 空闲，等待输入
    - RUNNING: 执行中（< 60s）
    - LONG_RUNNING: 执行超过 60s
    - WAITING_APPROVAL: 等待权限确认
    - DONE: 完成待确认
    - FAILED: 失败待确认
    """
    IDLE = "idle"
    RUNNING = "running"
    LONG_RUNNING = "long_running"
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
        return self in {
            TaskStatus.RUNNING,
            TaskStatus.LONG_RUNNING,
        }

    @property
    def color(self) -> str:
        """状态对应的颜色"""
        colors = {
            TaskStatus.IDLE: "gray",
            TaskStatus.RUNNING: "blue",
            TaskStatus.LONG_RUNNING: "darkblue",
            TaskStatus.WAITING_APPROVAL: "yellow",
            TaskStatus.DONE: "green",
            TaskStatus.FAILED: "red",
        }
        return colors.get(self, "gray")

    @property
    def display(self) -> bool:
        """是否需要前端显示"""
        return self != TaskStatus.IDLE


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
