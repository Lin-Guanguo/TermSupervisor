"""状态分析器基类和状态枚举"""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

# 统一使用 pane/types.py 中的 TaskStatus
from ..pane.types import TaskStatus

if TYPE_CHECKING:
    from ..models import PaneHistory


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
