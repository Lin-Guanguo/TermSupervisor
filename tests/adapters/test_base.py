"""布局数据结构测试"""

from termsupervisor.adapters.iterm2.models import LayoutData, PaneInfo, TabInfo, WindowInfo


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
