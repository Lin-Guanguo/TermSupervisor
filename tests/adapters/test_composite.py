"""Tests for CompositeAdapter."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from termsupervisor.adapters.base import JobMetadata
from termsupervisor.adapters.composite import CompositeAdapter, TmuxMapping
from termsupervisor.adapters.iterm2.models import (
    LayoutData,
    PaneInfo,
    TabInfo,
    WindowInfo,
)
from termsupervisor.core.ids import (
    AdapterType,
    get_adapter_type,
    get_native_id,
    is_iterm2_id,
    is_tmux_id,
    make_pane_id,
    make_tab_id,
    parse_id,
)


class TestNamespacedIds:
    """Test namespaced ID utilities."""

    def test_make_pane_id_with_enum(self):
        """Test make_pane_id with AdapterType enum."""
        assert make_pane_id(AdapterType.ITERM2, "uuid-123") == "iterm2:uuid-123"
        assert make_pane_id(AdapterType.TMUX, "%0") == "tmux:%0"

    def test_make_pane_id_with_string(self):
        """Test make_pane_id with string adapter type."""
        assert make_pane_id("iterm2", "uuid-123") == "iterm2:uuid-123"
        assert make_pane_id("tmux", "%0") == "tmux:%0"

    def test_make_tab_id(self):
        """Test make_tab_id for tmux windows."""
        assert make_tab_id(AdapterType.TMUX, "$0", "@1") == "tmux:$0:@1"

    def test_parse_id_iterm2(self):
        """Test parsing iTerm2 namespaced ID."""
        parsed = parse_id("iterm2:uuid-123")
        assert parsed is not None
        assert parsed.adapter == AdapterType.ITERM2
        assert parsed.native_id == "uuid-123"
        assert parsed.session is None

    def test_parse_id_tmux_pane(self):
        """Test parsing tmux pane ID."""
        parsed = parse_id("tmux:%0")
        assert parsed is not None
        assert parsed.adapter == AdapterType.TMUX
        assert parsed.native_id == "%0"
        assert parsed.session is None

    def test_parse_id_tmux_tab(self):
        """Test parsing tmux tab ID with session."""
        parsed = parse_id("tmux:$0:@1")
        assert parsed is not None
        assert parsed.adapter == AdapterType.TMUX
        assert parsed.native_id == "@1"
        assert parsed.session == "$0"

    def test_parse_id_invalid(self):
        """Test parsing invalid ID returns None."""
        assert parse_id("invalid") is None
        assert parse_id("unknown:id") is None

    def test_get_adapter_type(self):
        """Test extracting adapter type from namespaced ID."""
        assert get_adapter_type("iterm2:uuid") == AdapterType.ITERM2
        assert get_adapter_type("tmux:%0") == AdapterType.TMUX
        assert get_adapter_type("invalid") is None

    def test_get_native_id(self):
        """Test extracting native ID from namespaced ID."""
        assert get_native_id("iterm2:uuid-123") == "uuid-123"
        assert get_native_id("tmux:%0") == "%0"
        # Fallback for non-namespaced IDs
        assert get_native_id("plain-id") == "plain-id"

    def test_is_tmux_id(self):
        """Test checking if ID is from tmux."""
        assert is_tmux_id("tmux:%0") is True
        assert is_tmux_id("iterm2:uuid") is False
        assert is_tmux_id("plain") is False

    def test_is_iterm2_id(self):
        """Test checking if ID is from iTerm2."""
        assert is_iterm2_id("iterm2:uuid") is True
        assert is_iterm2_id("tmux:%0") is False
        assert is_iterm2_id("plain") is False


class TestCompositeAdapter:
    """Test CompositeAdapter functionality."""

    @pytest.fixture
    def mock_iterm2_adapter(self):
        """Create mock iTerm2 adapter."""
        adapter = MagicMock()
        adapter.name = "iterm2"
        adapter.get_layout = AsyncMock()
        adapter.get_pane_content = AsyncMock()
        adapter.get_job_metadata = AsyncMock()
        adapter.activate_pane = AsyncMock()
        adapter.rename_pane = AsyncMock()
        return adapter

    @pytest.fixture
    def mock_tmux_adapter(self):
        """Create mock tmux adapter."""
        adapter = MagicMock()
        adapter.name = "tmux"
        adapter.get_layout = AsyncMock()
        adapter.get_pane_content = AsyncMock()
        adapter.get_job_metadata = AsyncMock()
        adapter.activate_pane = AsyncMock()
        adapter.rename_pane = AsyncMock()
        return adapter

    @pytest.fixture
    def mock_tmux_client(self):
        """Create mock tmux client."""
        client = MagicMock()
        client.list_clients = AsyncMock(return_value=[])
        return client

    @pytest.fixture
    def composite_adapter(self, mock_iterm2_adapter, mock_tmux_adapter, mock_tmux_client):
        """Create CompositeAdapter with mocks."""
        return CompositeAdapter(
            iterm2_adapter=mock_iterm2_adapter,
            tmux_adapter=mock_tmux_adapter,
            tmux_client=mock_tmux_client,
        )

    @pytest.mark.asyncio
    async def test_get_pane_content_routes_iterm2(
        self, composite_adapter, mock_iterm2_adapter
    ):
        """Test get_pane_content routes to iTerm2 for iterm2: prefixed ID."""
        mock_iterm2_adapter.get_pane_content.return_value = "content"

        result = await composite_adapter.get_pane_content("iterm2:uuid-123")

        assert result == "content"
        mock_iterm2_adapter.get_pane_content.assert_called_once_with("uuid-123")

    @pytest.mark.asyncio
    async def test_get_pane_content_routes_tmux(
        self, composite_adapter, mock_tmux_adapter
    ):
        """Test get_pane_content routes to tmux for tmux: prefixed ID."""
        mock_tmux_adapter.get_pane_content.return_value = "tmux content"

        result = await composite_adapter.get_pane_content("tmux:%0")

        assert result == "tmux content"
        mock_tmux_adapter.get_pane_content.assert_called_once_with("%0")

    @pytest.mark.asyncio
    async def test_get_job_metadata_routes_iterm2(
        self, composite_adapter, mock_iterm2_adapter
    ):
        """Test get_job_metadata routes to iTerm2."""
        job = JobMetadata(job_name="vim")
        mock_iterm2_adapter.get_job_metadata.return_value = job

        result = await composite_adapter.get_job_metadata("iterm2:uuid-123")

        assert result == job
        mock_iterm2_adapter.get_job_metadata.assert_called_once_with("uuid-123")

    @pytest.mark.asyncio
    async def test_get_job_metadata_routes_tmux(
        self, composite_adapter, mock_tmux_adapter
    ):
        """Test get_job_metadata routes to tmux."""
        job = JobMetadata(job_name="bash")
        mock_tmux_adapter.get_job_metadata.return_value = job

        result = await composite_adapter.get_job_metadata("tmux:%0")

        assert result == job
        mock_tmux_adapter.get_job_metadata.assert_called_once_with("%0")

    @pytest.mark.asyncio
    async def test_activate_pane_routes_iterm2(
        self, composite_adapter, mock_iterm2_adapter
    ):
        """Test activate_pane routes to iTerm2."""
        mock_iterm2_adapter.activate_pane.return_value = True

        result = await composite_adapter.activate_pane("iterm2:uuid-123")

        assert result is True
        mock_iterm2_adapter.activate_pane.assert_called_once_with("uuid-123")

    @pytest.mark.asyncio
    async def test_activate_pane_routes_tmux_with_host(
        self, composite_adapter, mock_iterm2_adapter, mock_tmux_adapter
    ):
        """Test activate_pane for tmux pane activates host first."""
        mock_iterm2_adapter.activate_pane.return_value = True
        mock_tmux_adapter.activate_pane.return_value = True

        # Set up host pane mapping
        composite_adapter._tmux_host_panes["tmux:%0"] = "host-uuid"

        result = await composite_adapter.activate_pane("tmux:%0")

        assert result is True
        # Should activate host iTerm2 pane first
        mock_iterm2_adapter.activate_pane.assert_called_once_with("host-uuid")
        # Then activate tmux pane
        mock_tmux_adapter.activate_pane.assert_called_once_with("%0")

    @pytest.mark.asyncio
    async def test_rename_pane_routes_iterm2(
        self, composite_adapter, mock_iterm2_adapter
    ):
        """Test rename_pane routes to iTerm2."""
        mock_iterm2_adapter.rename_pane.return_value = True

        result = await composite_adapter.rename_pane("iterm2:uuid-123", "new-name")

        assert result is True
        mock_iterm2_adapter.rename_pane.assert_called_once_with("uuid-123", "new-name")

    @pytest.mark.asyncio
    async def test_rename_pane_routes_tmux(
        self, composite_adapter, mock_tmux_adapter
    ):
        """Test rename_pane routes to tmux."""
        mock_tmux_adapter.rename_pane.return_value = True

        result = await composite_adapter.rename_pane("tmux:%0", "new-name")

        assert result is True
        mock_tmux_adapter.rename_pane.assert_called_once_with("%0", "new-name")

    @pytest.mark.asyncio
    async def test_get_layout_returns_namespaced_ids(
        self, composite_adapter, mock_iterm2_adapter, mock_tmux_client
    ):
        """Test get_layout returns pane IDs with namespace prefixes."""
        # Set up iTerm2 layout without tmux
        mock_iterm2_adapter.get_layout.return_value = LayoutData(
            windows=[
                WindowInfo(
                    window_id="win-1",
                    name="Main",
                    x=0,
                    y=0,
                    width=100,
                    height=50,
                    tabs=[
                        TabInfo(
                            tab_id="tab-1",
                            name="Tab 1",
                            panes=[
                                PaneInfo(
                                    pane_id="uuid-123",
                                    name="pane 1",
                                    index=0,
                                    x=0,
                                    y=0,
                                    width=100,
                                    height=50,
                                )
                            ],
                        )
                    ],
                )
            ]
        )

        # No tmux clients
        mock_tmux_client.list_clients.return_value = []
        mock_iterm2_adapter.get_job_metadata.return_value = JobMetadata(
            job_name="vim", tty=""
        )

        result = await composite_adapter.get_layout()

        assert result is not None
        assert len(result.windows) == 1
        # Window ID should be namespaced
        assert result.windows[0].window_id == "iterm2:win-1"
        # Tab ID should be namespaced
        assert result.windows[0].tabs[0].tab_id == "iterm2:tab-1"
        # Pane ID should be namespaced
        assert result.windows[0].tabs[0].panes[0].pane_id == "iterm2:uuid-123"
