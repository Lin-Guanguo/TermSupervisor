"""Tests for tmux layout parser."""

import pytest

from termsupervisor.adapters.iterm2.models import LayoutData, PaneInfo, TabInfo, WindowInfo
from termsupervisor.adapters.tmux.layout import TmuxLayoutBuilder


class TestTmuxLayoutBuilder:
    """Tests for TmuxLayoutBuilder class."""

    def test_build_empty(self):
        """Test building layout with no data."""
        builder = TmuxLayoutBuilder()
        layout = builder.build(windows=[], panes=[])

        assert isinstance(layout, LayoutData)
        assert layout.windows == []

    def test_build_single_window_single_pane(self):
        """Test building layout with one window and one pane."""
        builder = TmuxLayoutBuilder()

        windows = [
            {
                "session_id": "0",
                "window_id": "0",
                "window_name": "bash",
                "width": 80,
                "height": 24,
                "active": True,
            }
        ]
        panes = [
            {
                "pane_id": "%0",
                "session_id": "0",
                "window_id": "0",
                "pane_name": "bash",
                "x": 0,
                "y": 0,
                "width": 80,
                "height": 24,
                "active": True,
                "path": "/home/user",
            }
        ]

        layout = builder.build(windows=windows, panes=panes)

        assert len(layout.windows) == 1
        win = layout.windows[0]
        assert isinstance(win, WindowInfo)
        assert win.window_id == "0:0"  # session:window format
        assert win.name == "bash"
        assert win.width == 80.0
        assert win.height == 24.0

        assert len(win.tabs) == 1
        tab = win.tabs[0]
        assert isinstance(tab, TabInfo)
        assert tab.name == "bash"

        assert len(tab.panes) == 1
        pane = tab.panes[0]
        assert isinstance(pane, PaneInfo)
        assert pane.pane_id == "%0"
        assert pane.name == "bash"
        assert pane.width == 80.0
        assert pane.height == 24.0

    def test_build_multiple_windows(self):
        """Test building layout with multiple windows in same session."""
        builder = TmuxLayoutBuilder()

        windows = [
            {
                "session_id": "0",
                "window_id": "0",
                "window_name": "editor",
                "width": 80,
                "height": 24,
                "active": True,
            },
            {
                "session_id": "0",
                "window_id": "1",
                "window_name": "shell",
                "width": 80,
                "height": 24,
                "active": False,
            },
        ]
        panes = [
            {
                "pane_id": "%0",
                "session_id": "0",
                "window_id": "0",
                "pane_name": "vim",
                "x": 0,
                "y": 0,
                "width": 80,
                "height": 24,
                "active": True,
                "path": "/home/user",
            },
            {
                "pane_id": "%1",
                "session_id": "0",
                "window_id": "1",
                "pane_name": "zsh",
                "x": 0,
                "y": 0,
                "width": 80,
                "height": 24,
                "active": True,
                "path": "/tmp",
            },
        ]

        layout = builder.build(windows=windows, panes=panes)

        # Each window becomes a WindowInfo
        assert len(layout.windows) == 2
        assert layout.windows[0].name == "editor"
        assert layout.windows[1].name == "shell"

        # Each window has one tab with its panes
        assert len(layout.windows[0].tabs[0].panes) == 1
        assert layout.windows[0].tabs[0].panes[0].pane_id == "%0"
        assert len(layout.windows[1].tabs[0].panes) == 1
        assert layout.windows[1].tabs[0].panes[0].pane_id == "%1"

    def test_build_split_panes(self):
        """Test building layout with split panes in one window."""
        builder = TmuxLayoutBuilder()

        windows = [
            {
                "session_id": "0",
                "window_id": "0",
                "window_name": "main",
                "width": 160,
                "height": 48,
                "active": True,
            }
        ]
        # Vertical split: two panes side by side
        panes = [
            {
                "pane_id": "%0",
                "session_id": "0",
                "window_id": "0",
                "pane_name": "left",
                "x": 0,
                "y": 0,
                "width": 80,
                "height": 48,
                "active": True,
                "path": "/home/user",
            },
            {
                "pane_id": "%1",
                "session_id": "0",
                "window_id": "0",
                "pane_name": "right",
                "x": 80,
                "y": 0,
                "width": 80,
                "height": 48,
                "active": False,
                "path": "/home/user",
            },
        ]

        layout = builder.build(windows=windows, panes=panes)

        assert len(layout.windows) == 1
        tab = layout.windows[0].tabs[0]
        assert len(tab.panes) == 2

        # Check pane positions
        left_pane = tab.panes[0]
        right_pane = tab.panes[1]
        assert left_pane.x == 0
        assert right_pane.x == 80

    def test_build_multiple_sessions(self):
        """Test building layout with multiple tmux sessions."""
        builder = TmuxLayoutBuilder()

        windows = [
            {
                "session_id": "main",
                "window_id": "0",
                "window_name": "work",
                "width": 80,
                "height": 24,
                "active": True,
            },
            {
                "session_id": "dev",
                "window_id": "0",
                "window_name": "code",
                "width": 80,
                "height": 24,
                "active": False,
            },
        ]
        panes = [
            {
                "pane_id": "%0",
                "session_id": "main",
                "window_id": "0",
                "pane_name": "shell",
                "x": 0,
                "y": 0,
                "width": 80,
                "height": 24,
                "active": True,
                "path": "/home/user",
            },
            {
                "pane_id": "%1",
                "session_id": "dev",
                "window_id": "0",
                "pane_name": "vim",
                "x": 0,
                "y": 0,
                "width": 80,
                "height": 24,
                "active": True,
                "path": "/projects",
            },
        ]

        layout = builder.build(windows=windows, panes=panes)

        # Each session:window combo becomes a WindowInfo
        assert len(layout.windows) == 2
        assert layout.windows[0].window_id == "main:0"
        assert layout.windows[1].window_id == "dev:0"

    def test_pane_index_assignment(self):
        """Test that panes get correct index within their window."""
        builder = TmuxLayoutBuilder()

        windows = [
            {
                "session_id": "0",
                "window_id": "0",
                "window_name": "splits",
                "width": 160,
                "height": 48,
                "active": True,
            }
        ]
        panes = [
            {
                "pane_id": "%0",
                "session_id": "0",
                "window_id": "0",
                "pane_name": "p0",
                "x": 0,
                "y": 0,
                "width": 80,
                "height": 24,
                "active": False,
                "path": "/",
            },
            {
                "pane_id": "%1",
                "session_id": "0",
                "window_id": "0",
                "pane_name": "p1",
                "x": 80,
                "y": 0,
                "width": 80,
                "height": 24,
                "active": True,
                "path": "/",
            },
            {
                "pane_id": "%2",
                "session_id": "0",
                "window_id": "0",
                "pane_name": "p2",
                "x": 0,
                "y": 24,
                "width": 160,
                "height": 24,
                "active": False,
                "path": "/",
            },
        ]

        layout = builder.build(windows=windows, panes=panes)

        tab = layout.windows[0].tabs[0]
        assert len(tab.panes) == 3
        # Indices should be sequential
        assert tab.panes[0].index == 0
        assert tab.panes[1].index == 1
        assert tab.panes[2].index == 2

    def test_coordinate_conversion(self):
        """Test that tmux character coordinates are preserved."""
        builder = TmuxLayoutBuilder()

        windows = [
            {
                "session_id": "0",
                "window_id": "0",
                "window_name": "test",
                "width": 200,
                "height": 50,
                "active": True,
            }
        ]
        panes = [
            {
                "pane_id": "%0",
                "session_id": "0",
                "window_id": "0",
                "pane_name": "pane",
                "x": 10,
                "y": 5,
                "width": 100,
                "height": 30,
                "active": True,
                "path": "/",
            }
        ]

        layout = builder.build(windows=windows, panes=panes)

        pane = layout.windows[0].tabs[0].panes[0]
        # Coordinates should be preserved as floats
        assert pane.x == 10.0
        assert pane.y == 5.0
        assert pane.width == 100.0
        assert pane.height == 30.0

    def test_window_coordinates(self):
        """Test window position defaults."""
        builder = TmuxLayoutBuilder()

        windows = [
            {
                "session_id": "0",
                "window_id": "0",
                "window_name": "test",
                "width": 80,
                "height": 24,
                "active": True,
            }
        ]
        panes = [
            {
                "pane_id": "%0",
                "session_id": "0",
                "window_id": "0",
                "pane_name": "pane",
                "x": 0,
                "y": 0,
                "width": 80,
                "height": 24,
                "active": True,
                "path": "/",
            }
        ]

        layout = builder.build(windows=windows, panes=panes)

        win = layout.windows[0]
        # tmux windows don't have position, default to 0,0
        assert win.x == 0.0
        assert win.y == 0.0
