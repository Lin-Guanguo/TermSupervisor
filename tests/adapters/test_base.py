"""TerminalAdapter 接口测试"""

import pytest
from abc import ABC

from termsupervisor.adapters.base import TerminalAdapter, LayoutData, PaneInfo, TabInfo, WindowInfo


class TestLayoutDataClasses:
    """布局数据类测试"""

    def test_pane_info_structure(self):
        """PaneInfo 基本结构"""
        pane = PaneInfo(
            pane_id="pane-123",
            name="zsh",
            index=0,
            x=0.0,
            y=0.0,
            width=100.0,
            height=50.0,
        )
        assert pane.pane_id == "pane-123"
        assert pane.name == "zsh"
        assert pane.width == 100.0

    def test_tab_info_structure(self):
        """TabInfo 基本结构"""
        pane = PaneInfo(pane_id="p1", name="zsh", index=0, x=0, y=0, width=100, height=50)
        tab = TabInfo(tab_id="tab-1", name="Tab 1", panes=[pane])
        assert tab.tab_id == "tab-1"
        assert len(tab.panes) == 1

    def test_window_info_structure(self):
        """WindowInfo 基本结构"""
        window = WindowInfo(
            window_id="w1",
            name="Window 1",
            x=0,
            y=0,
            width=800,
            height=600,
            tabs=[],
        )
        assert window.window_id == "w1"
        assert window.width == 800

    def test_layout_data_structure(self):
        """LayoutData 基本结构"""
        layout = LayoutData(windows=[], active_pane_id=None)
        assert layout.windows == []
        assert layout.active_pane_id is None


class TestTerminalAdapterInterface:
    """TerminalAdapter 接口测试"""

    def test_is_abstract_class(self):
        """TerminalAdapter 是抽象类"""
        assert issubclass(TerminalAdapter, ABC)

    def test_cannot_instantiate(self):
        """不能直接实例化"""
        with pytest.raises(TypeError):
            TerminalAdapter()

    def test_has_required_properties(self):
        """必须有 name 属性"""
        # 创建一个测试实现
        class TestAdapter(TerminalAdapter):
            @property
            def name(self) -> str:
                return "test"

            async def connect(self) -> bool:
                return True

            async def disconnect(self) -> None:
                pass

            async def get_layout(self) -> LayoutData:
                return LayoutData(windows=[])

            async def get_pane_content(self, pane_id: str) -> str:
                return ""

            async def activate_pane(self, pane_id: str) -> bool:
                return True

        adapter = TestAdapter()
        assert adapter.name == "test"

    def test_has_required_methods(self):
        """必须有必要的方法"""
        required_methods = [
            "connect",
            "disconnect",
            "get_layout",
            "get_pane_content",
            "activate_pane",
        ]
        for method in required_methods:
            assert hasattr(TerminalAdapter, method)


class TestConcreteAdapter:
    """具体实现测试（用于验证接口契约）"""

    @pytest.fixture
    def mock_adapter(self):
        """创建 mock adapter"""
        class MockAdapter(TerminalAdapter):
            def __init__(self):
                self._connected = False

            @property
            def name(self) -> str:
                return "mock"

            async def connect(self) -> bool:
                self._connected = True
                return True

            async def disconnect(self) -> None:
                self._connected = False

            async def get_layout(self) -> LayoutData:
                return LayoutData(
                    windows=[
                        WindowInfo(
                            window_id="w1",
                            name="Test Window",
                            x=0,
                            y=0,
                            width=800,
                            height=600,
                            tabs=[
                                TabInfo(
                                    tab_id="t1",
                                    name="Tab 1",
                                    panes=[
                                        PaneInfo(
                                            pane_id="p1",
                                            name="zsh",
                                            index=0,
                                            x=0,
                                            y=0,
                                            width=800,
                                            height=600,
                                        )
                                    ],
                                )
                            ],
                        )
                    ],
                    active_pane_id="p1",
                )

            async def get_pane_content(self, pane_id: str) -> str:
                return f"Content of {pane_id}"

            async def activate_pane(self, pane_id: str) -> bool:
                return True

        return MockAdapter()

    async def test_connect(self, mock_adapter):
        """测试连接"""
        result = await mock_adapter.connect()
        assert result is True
        assert mock_adapter._connected is True

    async def test_disconnect(self, mock_adapter):
        """测试断开"""
        await mock_adapter.connect()
        await mock_adapter.disconnect()
        assert mock_adapter._connected is False

    async def test_get_layout(self, mock_adapter):
        """测试获取布局"""
        layout = await mock_adapter.get_layout()
        assert len(layout.windows) == 1
        assert layout.windows[0].window_id == "w1"
        assert len(layout.windows[0].tabs) == 1
        assert len(layout.windows[0].tabs[0].panes) == 1

    async def test_get_pane_content(self, mock_adapter):
        """测试获取 pane 内容"""
        content = await mock_adapter.get_pane_content("p1")
        assert "p1" in content

    async def test_activate_pane(self, mock_adapter):
        """测试激活 pane"""
        result = await mock_adapter.activate_pane("p1")
        assert result is True
