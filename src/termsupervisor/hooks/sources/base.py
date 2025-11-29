"""Hook 源适配器基类"""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..manager import HookManager


class HookSource(ABC):
    """Hook 源适配器基类

    每个适配器负责：
    1. 接收特定来源的事件
    2. 转换为统一的 HookEvent
    3. 调用 HookManager 更新状态
    """

    source_name: str  # 适配器标识: "shell", "claude-code", "gemini", "codex"

    def __init__(self, manager: "HookManager"):
        self.manager = manager

    @abstractmethod
    async def start(self) -> None:
        """启动监听"""
        pass

    @abstractmethod
    async def stop(self) -> None:
        """停止监听"""
        pass
