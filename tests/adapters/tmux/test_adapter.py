"""Tests for TmuxAdapter."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from termsupervisor.adapters import JobMetadata, TerminalAdapter
from termsupervisor.adapters.iterm2.models import LayoutData, PaneInfo, TabInfo, WindowInfo
from termsupervisor.adapters.tmux.adapter import TmuxAdapter


class TestTmuxAdapter:
    """Tests for TmuxAdapter class."""

    def test_implements_protocol(self):
        """TmuxAdapter satisfies TerminalAdapter protocol."""
        adapter = TmuxAdapter()
        assert isinstance(adapter, TerminalAdapter)

    def test_name(self):
        """TmuxAdapter has correct name."""
        adapter = TmuxAdapter()
        assert adapter.name == "tmux"

    def test_init_default(self):
        """Test TmuxAdapter initialization with defaults."""
        adapter = TmuxAdapter()
        assert adapter._client is not None

    def test_init_with_socket(self):
        """Test TmuxAdapter initialization with socket path."""
        adapter = TmuxAdapter(socket_path="/tmp/test.sock")
        assert adapter._client._socket_path == "/tmp/test.sock"

    @pytest.mark.asyncio
    async def test_get_layout(self):
        """Test get_layout returns LayoutData."""
        adapter = TmuxAdapter()

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

        with patch.object(adapter._client, "list_windows", return_value=windows):
            with patch.object(adapter._client, "list_panes", return_value=panes):
                layout = await adapter.get_layout()

        assert isinstance(layout, LayoutData)
        assert len(layout.windows) == 1
        assert layout.windows[0].name == "bash"

    @pytest.mark.asyncio
    async def test_get_layout_empty(self):
        """Test get_layout when tmux has no windows."""
        adapter = TmuxAdapter()

        with patch.object(adapter._client, "list_windows", return_value=[]):
            with patch.object(adapter._client, "list_panes", return_value=[]):
                layout = await adapter.get_layout()

        assert isinstance(layout, LayoutData)
        assert layout.windows == []

    @pytest.mark.asyncio
    async def test_get_layout_none_on_error(self):
        """Test get_layout returns None when tmux not available."""
        adapter = TmuxAdapter()

        with patch.object(adapter._client, "list_windows", side_effect=Exception("tmux error")):
            layout = await adapter.get_layout()

        assert layout is None

    @pytest.mark.asyncio
    async def test_get_pane_content(self):
        """Test get_pane_content returns content string."""
        adapter = TmuxAdapter()
        content = "$ ls\nfile1\nfile2\n"

        with patch.object(adapter._client, "capture_pane", return_value=content):
            result = await adapter.get_pane_content("%0")

        assert result == content

    @pytest.mark.asyncio
    async def test_get_pane_content_none(self):
        """Test get_pane_content returns None when pane not found."""
        adapter = TmuxAdapter()

        with patch.object(adapter._client, "capture_pane", return_value=None):
            result = await adapter.get_pane_content("%99")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_job_metadata(self):
        """Test get_job_metadata returns JobMetadata."""
        adapter = TmuxAdapter()

        pane_info = {
            "pane_id": "%0",
            "pane_name": "vim",
            "path": "/home/user/project",
            "current_command": "vim main.py",
        }

        with patch.object(adapter._client, "get_pane_info", return_value=pane_info):
            result = await adapter.get_job_metadata("%0")

        assert isinstance(result, JobMetadata)
        assert result.job_name == "vim"
        assert result.path == "/home/user/project"
        assert result.command_line == "vim main.py"

    @pytest.mark.asyncio
    async def test_get_job_metadata_none(self):
        """Test get_job_metadata returns None when pane not found."""
        adapter = TmuxAdapter()

        with patch.object(adapter._client, "get_pane_info", return_value=None):
            result = await adapter.get_job_metadata("%99")

        assert result is None

    @pytest.mark.asyncio
    async def test_activate_pane_success(self):
        """Test activate_pane returns True on success."""
        adapter = TmuxAdapter()

        with patch.object(adapter._client, "select_pane", return_value=True):
            result = await adapter.activate_pane("%0")

        assert result is True

    @pytest.mark.asyncio
    async def test_activate_pane_failure(self):
        """Test activate_pane returns False on failure."""
        adapter = TmuxAdapter()

        with patch.object(adapter._client, "select_pane", return_value=False):
            result = await adapter.activate_pane("%99")

        assert result is False

    @pytest.mark.asyncio
    async def test_rename_pane_success(self):
        """Test rename_pane returns True on success."""
        adapter = TmuxAdapter()

        with patch.object(adapter._client, "rename_pane", return_value=True):
            result = await adapter.rename_pane("%0", "my-pane")

        assert result is True

    @pytest.mark.asyncio
    async def test_rename_pane_failure(self):
        """Test rename_pane returns False on failure."""
        adapter = TmuxAdapter()

        with patch.object(adapter._client, "rename_pane", return_value=False):
            result = await adapter.rename_pane("%99", "test")

        assert result is False

    def test_client_property(self):
        """Test client property access."""
        adapter = TmuxAdapter()
        assert adapter.client is adapter._client
