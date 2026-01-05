"""ITerm2Adapter - iTerm2 终端适配器

实现 TerminalAdapter 接口，封装 iTerm2 特定的 API 调用。
"""

from typing import TYPE_CHECKING

from ..base import TerminalAdapter
from .client import ITerm2Client
from .layout import get_layout as iterm_get_layout
from .models import LayoutData, PaneInfo, TabInfo, WindowInfo

if TYPE_CHECKING:
    import iterm2


class ITerm2Adapter(TerminalAdapter):
    """iTerm2 终端适配器

    封装 ITerm2Client 和 get_layout，提供统一的 TerminalAdapter 接口。

    使用示例:
        async with iterm2.Connection() as connection:
            adapter = ITerm2Adapter(connection)
            await adapter.connect()
            layout = await adapter.get_layout()
            for window in layout.windows:
                print(window.name)
            await adapter.disconnect()
    """

    def __init__(self, connection: "iterm2.Connection"):
        """初始化适配器

        Args:
            connection: iTerm2 连接
        """
        self._connection = connection
        self._client = ITerm2Client(connection)
        self._app: iterm2.App | None = None

    @property
    def name(self) -> str:
        """适配器名称"""
        return "iterm2"

    @property
    def client(self) -> ITerm2Client:
        """获取底层 client（用于高级操作）"""
        return self._client

    async def connect(self) -> bool:
        """连接到 iTerm2

        Returns:
            是否连接成功
        """
        self._app = await self._client.get_app()
        return self._app is not None

    async def disconnect(self) -> None:
        """断开连接"""
        self._app = None

    async def get_layout(self, exclude_names: list[str] | None = None) -> LayoutData:
        """获取完整布局

        Args:
            exclude_names: 要排除的 pane 名称列表

        Returns:
            包含所有 window/tab/pane 的布局数据（通用格式）
        """
        if self._app is None:
            return LayoutData(windows=[])

        # 获取 iTerm2 原始布局
        iterm_layout = await iterm_get_layout(self._app, exclude_names)

        # 转换为通用格式
        return self._convert_layout(iterm_layout)

    def _convert_layout(self, iterm_layout) -> LayoutData:
        """将 iTerm2 布局转换为通用格式

        Args:
            iterm_layout: iTerm2 原生布局数据

        Returns:
            通用布局数据
        """
        windows = []
        for iterm_window in iterm_layout.windows:
            tabs = []
            for iterm_tab in iterm_window.tabs:
                panes = []
                for iterm_pane in iterm_tab.panes:
                    pane = PaneInfo(
                        pane_id=iterm_pane.session_id,
                        name=iterm_pane.name,
                        index=iterm_pane.index,
                        x=iterm_pane.x,
                        y=iterm_pane.y,
                        width=iterm_pane.width,
                        height=iterm_pane.height,
                    )
                    panes.append(pane)
                tab = TabInfo(
                    tab_id=iterm_tab.tab_id,
                    name=iterm_tab.name,
                    panes=panes,
                )
                tabs.append(tab)
            window = WindowInfo(
                window_id=iterm_window.window_id,
                name=iterm_window.name,
                x=iterm_window.x,
                y=iterm_window.y,
                width=iterm_window.width,
                height=iterm_window.height,
                tabs=tabs,
            )
            windows.append(window)

        return LayoutData(
            windows=windows,
            active_pane_id=iterm_layout.active_session_id,
        )

    async def get_pane_content(self, pane_id: str) -> str:
        """获取 pane 屏幕内容

        Args:
            pane_id: Pane 标识符（iTerm2 session_id）

        Returns:
            屏幕内容文本
        """
        if self._app is None:
            return ""

        session = self._app.get_session_by_id(pane_id)
        if session is None:
            return ""

        return await self._client.get_session_content(session)

    async def activate_pane(self, pane_id: str) -> bool:
        """激活指定 pane（切换焦点）

        Args:
            pane_id: Pane 标识符

        Returns:
            是否成功
        """
        return await self._client.activate_session(pane_id)

    async def rename_pane(self, pane_id: str, new_name: str) -> bool:
        """重命名 pane

        Args:
            pane_id: Pane 标识符
            new_name: 新名称

        Returns:
            是否成功
        """
        return await self._client.rename_session(pane_id, new_name)

    async def rename_tab(self, tab_id: str, new_name: str) -> bool:
        """重命名 tab

        Args:
            tab_id: Tab 标识符
            new_name: 新名称

        Returns:
            是否成功
        """
        return await self._client.rename_tab(tab_id, new_name)

    async def rename_window(self, window_id: str, new_name: str) -> bool:
        """重命名 window

        Args:
            window_id: Window 标识符
            new_name: 新名称

        Returns:
            是否成功
        """
        return await self._client.rename_window(window_id, new_name)

    async def create_tab(self, window_id: str, layout: str = "single") -> bool:
        """创建新 tab

        Args:
            window_id: 窗口 ID
            layout: 布局类型（single, 2rows, 2cols, 2x2）

        Returns:
            是否成功
        """
        return await self._client.create_tab(window_id, layout)
