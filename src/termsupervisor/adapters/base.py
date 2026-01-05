"""Terminal Adapter 抽象接口

定义终端适配器的统一接口，支持不同终端后端：
- iTerm2
- tmux
- 未来: kitty, alacritty 等

设计原则：
1. 最小接口：只定义必要的操作
2. 布局无关：使用通用的 Window/Tab/Pane 模型
3. 异步优先：所有 IO 操作都是 async

注意：布局数据模型定义在各适配器模块中（如 iterm2/models.py）。
"""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .iterm2.models import LayoutData


class TerminalAdapter(ABC):
    """终端适配器抽象接口

    所有终端后端（iTerm2, tmux 等）必须实现此接口。

    使用示例:
        adapter = ITerm2Adapter(connection)
        await adapter.connect()
        layout = await adapter.get_layout()
        for window in layout.windows:
            for tab in window.tabs:
                for pane in tab.panes:
                    content = await adapter.get_pane_content(pane.pane_id)
                    print(content)
        await adapter.disconnect()
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """适配器名称（如 "iterm2", "tmux"）"""
        pass

    @abstractmethod
    async def connect(self) -> bool:
        """连接到终端

        Returns:
            是否连接成功
        """
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """断开连接"""
        pass

    @abstractmethod
    async def get_layout(self) -> "LayoutData":
        """获取完整布局

        Returns:
            包含所有 window/tab/pane 的布局数据
        """
        pass

    @abstractmethod
    async def get_pane_content(self, pane_id: str) -> str:
        """获取 pane 屏幕内容

        Args:
            pane_id: Pane 标识符

        Returns:
            屏幕内容文本
        """
        pass

    @abstractmethod
    async def activate_pane(self, pane_id: str) -> bool:
        """激活指定 pane（切换焦点）

        Args:
            pane_id: Pane 标识符

        Returns:
            是否成功
        """
        pass

    # 可选方法（有默认实现）

    async def rename_pane(self, pane_id: str, new_name: str) -> bool:
        """重命名 pane"""
        return False

    async def rename_tab(self, tab_id: str, new_name: str) -> bool:
        """重命名 tab"""
        return False

    async def rename_window(self, window_id: str, new_name: str) -> bool:
        """重命名 window"""
        return False

    async def create_tab(self, window_id: str, layout: str = "single") -> bool:
        """创建新 tab"""
        return False
