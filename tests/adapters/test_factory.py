"""Tests for adapter factory."""

from unittest.mock import MagicMock, patch

import pytest

from termsupervisor.adapters import create_adapter, detect_terminal_type
from termsupervisor.adapters.iterm2 import ITerm2Adapter
from termsupervisor.adapters.tmux import TmuxAdapter


class TestDetectTerminalType:
    """Tests for detect_terminal_type function."""

    def test_detect_tmux_when_tmux_set(self):
        """Detect tmux when $TMUX environment variable is set."""
        with patch.dict("os.environ", {"TMUX": "/tmp/tmux-1000/default,12345,0"}):
            result = detect_terminal_type()
        assert result == "tmux"

    def test_detect_iterm2_when_tmux_not_set(self):
        """Detect iTerm2 when $TMUX is not set."""
        with patch.dict("os.environ", {}, clear=True):
            # Remove TMUX from environment
            with patch.dict("os.environ", {"TMUX": ""}, clear=False):
                import os

                os.environ.pop("TMUX", None)
            result = detect_terminal_type()
        assert result == "iterm2"


class TestCreateAdapter:
    """Tests for create_adapter function."""

    def test_create_iterm2_adapter(self):
        """Create iTerm2 adapter with connection."""
        mock_connection = MagicMock()
        adapter = create_adapter(
            adapter_type="iterm2",
            connection=mock_connection,
            exclude_names=["test"],
        )
        assert isinstance(adapter, ITerm2Adapter)
        assert adapter.name == "iterm2"

    def test_create_iterm2_without_connection_raises(self):
        """Creating iTerm2 adapter without connection raises ValueError."""
        with pytest.raises(ValueError, match="requires connection"):
            create_adapter(adapter_type="iterm2")

    def test_create_tmux_adapter(self):
        """Create tmux adapter."""
        adapter = create_adapter(adapter_type="tmux")
        assert isinstance(adapter, TmuxAdapter)
        assert adapter.name == "tmux"

    def test_create_tmux_adapter_with_socket(self):
        """Create tmux adapter with custom socket path."""
        adapter = create_adapter(
            adapter_type="tmux", socket_path="/tmp/test.sock"
        )
        assert isinstance(adapter, TmuxAdapter)
        assert adapter._client._socket_path == "/tmp/test.sock"

    def test_create_auto_detects_tmux(self):
        """Auto mode detects tmux from environment."""
        with patch.dict("os.environ", {"TMUX": "/tmp/tmux/default,123,0"}):
            adapter = create_adapter(adapter_type="auto")
        assert isinstance(adapter, TmuxAdapter)

    def test_create_auto_detects_iterm2(self):
        """Auto mode falls back to iTerm2."""
        mock_connection = MagicMock()
        with patch.dict("os.environ", {}, clear=True):
            with patch(
                "termsupervisor.adapters.factory.detect_terminal_type",
                return_value="iterm2",
            ):
                adapter = create_adapter(
                    adapter_type="auto", connection=mock_connection
                )
        assert isinstance(adapter, ITerm2Adapter)

    def test_create_unknown_type_raises(self):
        """Creating unknown adapter type raises ValueError."""
        with pytest.raises(ValueError, match="Unknown adapter type"):
            create_adapter(adapter_type="unknown")

    def test_create_uses_config_default(self):
        """Create adapter uses config default when type not specified."""
        mock_connection = MagicMock()
        with patch("termsupervisor.adapters.factory.config.TERMINAL_ADAPTER", "iterm2"):
            adapter = create_adapter(connection=mock_connection)
        assert isinstance(adapter, ITerm2Adapter)
