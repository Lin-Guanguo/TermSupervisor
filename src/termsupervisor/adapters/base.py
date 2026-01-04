"""Terminal Adapter 抽象接口

定义终端适配器的统一接口，支持不同终端后端：
- iTerm2
- tmux
- 未来: kitty, alacritty 等

设计原则：
1. 最小接口：只定义必要的操作
2. 布局无关：使用通用的 Window/Tab/Pane 模型
3. 异步优先：所有 IO 操作都是 async
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class PaneInfo:
    """Pane 信息（通用模型）

    Attributes:
        pane_id: 唯一标识符（适配器内部 ID）
        name: 显示名称
        index: 在 tab 内的索引
        x, y: 位置（百分比或像素，由适配器决定）
        width, height: 尺寸（百分比或像素）
    """

    pane_id: str
    name: str
    index: int
    x: float
    y: float
    width: float
    height: float


@dataclass
class TabInfo:
    """Tab 信息（通用模型）

    Attributes:
        tab_id: 唯一标识符
        name: 显示名称
        panes: 包含的 pane 列表
    """

    tab_id: str
    name: str
    panes: list[PaneInfo] = field(default_factory=list)


@dataclass
class WindowInfo:
    """Window 信息（通用模型）

    Attributes:
        window_id: 唯一标识符
        name: 显示名称
        x, y: 窗口位置
        width, height: 窗口尺寸
        tabs: 包含的 tab 列表
    """

    window_id: str
    name: str
    x: float
    y: float
    width: float
    height: float
    tabs: list[TabInfo] = field(default_factory=list)


@dataclass
class LayoutData:
    """完整布局数据（通用模型）

    Attributes:
        windows: 所有窗口
        active_pane_id: 当前焦点 pane
        updated_panes: 本次更新的 pane ID 列表（用于增量更新）
    """

    windows: list[WindowInfo] = field(default_factory=list)
    active_pane_id: str | None = None
    updated_panes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """转换为可序列化的字典"""
        from dataclasses import asdict

        return asdict(self)

    def get_all_pane_ids(self) -> set[str]:
        """获取所有 pane ID"""
        return {
            pane.pane_id
            for window in self.windows
            for tab in window.tabs
            for pane in tab.panes
        }


class TerminalAdapter(ABC):
    """终端适配器抽象接口

    所有终端后端（iTerm2, tmux 等）必须实现此接口。

    使用示例:
        adapter = ITerm2Adapter()
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
    async def get_layout(self) -> LayoutData:
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
        """重命名 pane

        Args:
            pane_id: Pane 标识符
            new_name: 新名称

        Returns:
            是否成功
        """
        return False

    async def rename_tab(self, tab_id: str, new_name: str) -> bool:
        """重命名 tab

        Args:
            tab_id: Tab 标识符
            new_name: 新名称

        Returns:
            是否成功
        """
        return False

    async def rename_window(self, window_id: str, new_name: str) -> bool:
        """重命名 window

        Args:
            window_id: Window 标识符
            new_name: 新名称

        Returns:
            是否成功
        """
        return False

    async def create_tab(self, window_id: str, layout: str = "single") -> bool:
        """创建新 tab

        Args:
            window_id: 窗口 ID
            layout: 布局类型（single, 2rows, 2cols, 2x2）

        Returns:
            是否成功
        """
        return False
