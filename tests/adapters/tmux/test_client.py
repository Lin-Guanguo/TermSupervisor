"""Tests for TmuxClient."""

from unittest.mock import AsyncMock, patch

import pytest

from termsupervisor.adapters.tmux.client import TmuxClient


class TestTmuxClient:
    """Tests for TmuxClient class."""

    def test_init_default(self):
        """Test TmuxClient initialization with defaults."""
        client = TmuxClient()
        assert client._socket_path is None

    def test_init_with_socket(self):
        """Test TmuxClient initialization with custom socket."""
        client = TmuxClient(socket_path="/tmp/tmux-test/default")
        assert client._socket_path == "/tmp/tmux-test/default"

    @pytest.mark.asyncio
    async def test_run_success(self):
        """Test running tmux command successfully."""
        client = TmuxClient()

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.communicate.return_value = (b"output\n", b"")
            mock_proc.returncode = 0
            mock_exec.return_value = mock_proc

            result = await client.run("list-sessions")

            assert result == "output\n"
            mock_exec.assert_called_once()
            # Check that 'tmux' and 'list-sessions' are in the call
            call_args = mock_exec.call_args[0]
            assert call_args[0] == "tmux"
            assert "list-sessions" in call_args

    @pytest.mark.asyncio
    async def test_run_with_socket(self):
        """Test running tmux command with socket path."""
        client = TmuxClient(socket_path="/tmp/test.sock")

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.communicate.return_value = (b"ok\n", b"")
            mock_proc.returncode = 0
            mock_exec.return_value = mock_proc

            await client.run("list-windows")

            call_args = mock_exec.call_args[0]
            assert "-S" in call_args
            assert "/tmp/test.sock" in call_args

    @pytest.mark.asyncio
    async def test_run_failure(self):
        """Test running tmux command that fails."""
        client = TmuxClient()

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.communicate.return_value = (b"", b"error: no server running\n")
            mock_proc.returncode = 1
            mock_exec.return_value = mock_proc

            result = await client.run("list-sessions")

            assert result is None

    @pytest.mark.asyncio
    async def test_list_windows(self):
        """Test listing tmux windows."""
        client = TmuxClient()

        # Sample tmux list-windows -a -F output (tab-delimited)
        output = "0\t0\tbash\t80\t24\t0\n0\t1\tvim\t80\t24\t1\n1\t0\tzsh\t120\t30\t0\n"
        with patch.object(client, "run", return_value=output):
            windows = await client.list_windows()

            assert len(windows) == 3
            assert windows[0] == {
                "session_id": "0",
                "window_id": "0",
                "window_name": "bash",
                "width": 80,
                "height": 24,
                "active": False,
            }
            assert windows[1]["active"] is True  # window_id=1 with flag=1
            assert windows[2]["session_id"] == "1"

    @pytest.mark.asyncio
    async def test_list_windows_with_colons(self):
        """Test listing windows with colons in window name."""
        client = TmuxClient()

        # Window name contains colon (e.g., "my:project")
        output = "0\t0\tmy:project\t80\t24\t1\n"
        with patch.object(client, "run", return_value=output):
            windows = await client.list_windows()

            assert len(windows) == 1
            assert windows[0]["window_name"] == "my:project"

    @pytest.mark.asyncio
    async def test_list_windows_empty(self):
        """Test listing windows when tmux returns nothing."""
        client = TmuxClient()

        with patch.object(client, "run", return_value=None):
            windows = await client.list_windows()
            assert windows == []

    @pytest.mark.asyncio
    async def test_list_panes(self):
        """Test listing tmux panes."""
        client = TmuxClient()

        # Sample tmux list-panes -a -F output (tab-delimited, 12 fields with pid/tty)
        output = (
            "%0\t0\t0\tbash\t0\t0\t80\t24\t1\t/home/user\t12345\t/dev/ttys001\n"
            "%1\t0\t0\tvim\t80\t0\t80\t24\t0\t/home/user/project\t12346\t/dev/ttys002\n"
            "%2\t1\t0\tzsh\t0\t0\t120\t30\t1\t/tmp\t12347\t/dev/ttys003\n"
        )
        with patch.object(client, "run", return_value=output):
            panes = await client.list_panes()

            assert len(panes) == 3
            assert panes[0]["pane_id"] == "%0"
            assert panes[0]["session_id"] == "0"
            assert panes[0]["window_id"] == "0"
            assert panes[0]["pane_name"] == "bash"
            assert panes[0]["x"] == 0
            assert panes[0]["y"] == 0
            assert panes[0]["width"] == 80
            assert panes[0]["height"] == 24
            assert panes[0]["active"] is True
            assert panes[0]["path"] == "/home/user"
            assert panes[0]["pane_pid"] == 12345
            assert panes[0]["pane_tty"] == "/dev/ttys001"
            assert panes[1]["active"] is False
            assert panes[2]["path"] == "/tmp"

    @pytest.mark.asyncio
    async def test_list_panes_with_colons(self):
        """Test listing panes with colons in path."""
        client = TmuxClient()

        # Path contains colon (e.g., "/home/user/code:project")
        output = "%0\t0\t0\tbash\t0\t0\t80\t24\t1\t/home/user/code:project\t123\t/dev/pts/0\n"
        with patch.object(client, "run", return_value=output):
            panes = await client.list_panes()

            assert len(panes) == 1
            assert panes[0]["path"] == "/home/user/code:project"

    @pytest.mark.asyncio
    async def test_list_panes_empty(self):
        """Test listing panes when tmux returns nothing."""
        client = TmuxClient()

        with patch.object(client, "run", return_value=None):
            panes = await client.list_panes()
            assert panes == []

    @pytest.mark.asyncio
    async def test_capture_pane(self):
        """Test capturing pane content."""
        client = TmuxClient()

        content = """$ ls -la
total 0
drwxr-xr-x  2 user user  40 Jan  1 00:00 .
$ _
"""
        with patch.object(client, "run", return_value=content):
            result = await client.capture_pane("%0")

            assert result == content
            # Verify correct command was called
            client.run.assert_called_once()
            call_args = client.run.call_args[0]  # All positional args
            assert "capture-pane" in call_args
            assert "-t" in call_args
            assert "%0" in call_args

    @pytest.mark.asyncio
    async def test_capture_pane_with_lines(self):
        """Test capturing pane content with custom line count."""
        client = TmuxClient()

        with patch.object(client, "run", return_value="content"):
            await client.capture_pane("%1", lines=50)

            call_args = client.run.call_args[0]  # All positional args
            assert "-S" in call_args  # Start line
            assert "-50" in call_args

    @pytest.mark.asyncio
    async def test_capture_pane_failure(self):
        """Test capturing pane when it fails."""
        client = TmuxClient()

        with patch.object(client, "run", return_value=None):
            result = await client.capture_pane("%99")
            assert result is None

    @pytest.mark.asyncio
    async def test_select_pane_success(self):
        """Test selecting/activating a pane."""
        client = TmuxClient()

        with patch.object(client, "run", return_value=""):
            result = await client.select_pane("%0")

            assert result is True
            client.run.assert_called_once()
            call_args = client.run.call_args[0]  # All positional args
            assert "select-pane" in call_args
            assert "-t" in call_args
            assert "%0" in call_args

    @pytest.mark.asyncio
    async def test_select_pane_failure(self):
        """Test selecting pane that doesn't exist."""
        client = TmuxClient()

        with patch.object(client, "run", return_value=None):
            result = await client.select_pane("%99")
            assert result is False

    @pytest.mark.asyncio
    async def test_get_active_pane(self):
        """Test getting currently active pane."""
        client = TmuxClient()

        with patch.object(client, "run", return_value="%2\n"):
            result = await client.get_active_pane()

            assert result == "%2"
            client.run.assert_called_once()
            call_args = client.run.call_args[0]  # All positional args
            assert "display-message" in call_args

    @pytest.mark.asyncio
    async def test_get_active_pane_none(self):
        """Test getting active pane when tmux not running."""
        client = TmuxClient()

        with patch.object(client, "run", return_value=None):
            result = await client.get_active_pane()
            assert result is None

    @pytest.mark.asyncio
    async def test_rename_pane(self):
        """Test renaming a pane."""
        client = TmuxClient()

        with patch.object(client, "run", return_value=""):
            result = await client.rename_pane("%0", "my-pane")

            assert result is True
            client.run.assert_called_once()
            call_args = client.run.call_args[0]  # All positional args
            assert "select-pane" in call_args
            assert "-T" in call_args  # Title flag
            assert "my-pane" in call_args

    @pytest.mark.asyncio
    async def test_rename_pane_failure(self):
        """Test renaming pane that doesn't exist."""
        client = TmuxClient()

        with patch.object(client, "run", return_value=None):
            result = await client.rename_pane("%99", "test")
            assert result is False

    @pytest.mark.asyncio
    async def test_get_pane_info(self):
        """Test getting info for a specific pane."""
        client = TmuxClient()

        # Tab-delimited output with pid and tty
        output = "%0\tbash\t/home/user\tvim file.txt\t12345\t/dev/ttys001\n"
        with patch.object(client, "run", return_value=output):
            result = await client.get_pane_info("%0")

            assert result is not None
            assert result["pane_id"] == "%0"
            assert result["pane_name"] == "bash"
            assert result["path"] == "/home/user"
            assert result["current_command"] == "vim file.txt"
            assert result["pane_pid"] == 12345
            assert result["pane_tty"] == "/dev/ttys001"

    @pytest.mark.asyncio
    async def test_get_pane_info_with_colons(self):
        """Test getting pane info with colons in path/command."""
        client = TmuxClient()

        # Path and command contain colons
        output = "%0\tbash\t/home/user:project\tvim file.txt:100\t123\t/dev/pts/0\n"
        with patch.object(client, "run", return_value=output):
            result = await client.get_pane_info("%0")

            assert result is not None
            assert result["path"] == "/home/user:project"
            assert result["current_command"] == "vim file.txt:100"

    @pytest.mark.asyncio
    async def test_get_pane_info_not_found(self):
        """Test getting info for non-existent pane."""
        client = TmuxClient()

        with patch.object(client, "run", return_value=None):
            result = await client.get_pane_info("%99")
            assert result is None
