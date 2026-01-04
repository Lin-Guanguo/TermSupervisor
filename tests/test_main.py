"""TermSupervisor 测试"""

from termsupervisor.adapters.iterm2.models import LayoutData, PaneInfo, TabInfo, WindowInfo


def test_pane_info():
    """测试 PaneInfo 数据模型"""
    pane = PaneInfo(
        session_id="test-session",
        name="test-pane",
        index=0,
        x=0.0,
        y=0.0,
        width=100.0,
        height=50.0,
    )
    assert pane.session_id == "test-session"
    assert pane.name == "test-pane"
    assert pane.width == 100.0


def test_layout_data():
    """测试 LayoutData 数据模型"""
    pane = PaneInfo(
        session_id="s1",
        name="pane1",
        index=0,
        x=0.0,
        y=0.0,
        width=100.0,
        height=100.0,
    )
    tab = TabInfo(tab_id="t1", name="tab1", panes=[pane])
    window = WindowInfo(
        window_id="w1",
        name="window1",
        x=0.0,
        y=0.0,
        width=800.0,
        height=600.0,
        tabs=[tab],
    )
    layout = LayoutData(windows=[window], updated_sessions=["s1"])

    data = layout.to_dict()
    assert len(data["windows"]) == 1
    assert data["windows"][0]["name"] == "window1"
    assert data["updated_sessions"] == ["s1"]


def test_supervisor_import():
    """测试 TermSupervisor 导入"""
    from termsupervisor.supervisor import TermSupervisor

    supervisor = TermSupervisor(interval=1.0)
    assert supervisor.interval == 1.0
    assert supervisor._running is False
