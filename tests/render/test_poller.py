"""Tests for render/poller.py"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from termsupervisor.adapters import JobMetadata
from termsupervisor.adapters.iterm2.models import LayoutData
from termsupervisor.render.poller import ContentPoller


class TestContentPoller:
    """Tests for ContentPoller class."""

    def _create_mock_adapter(self):
        """Create a mock TerminalAdapter."""
        adapter = MagicMock()
        adapter.name = "mock"
        return adapter

    def test_init(self):
        """Test poller initialization."""
        mock_adapter = self._create_mock_adapter()
        poller = ContentPoller(mock_adapter)
        assert poller._adapter == mock_adapter
        assert poller._exclude_names == []

    def test_init_with_exclude_names(self):
        """Test poller initialization with exclude names."""
        mock_adapter = self._create_mock_adapter()
        poller = ContentPoller(mock_adapter, exclude_names=["htop", "vim"])
        assert poller._exclude_names == ["htop", "vim"]

    @pytest.mark.asyncio
    async def test_poll_layout_returns_none(self):
        """Test poll_layout when adapter returns None."""
        mock_adapter = self._create_mock_adapter()
        mock_adapter.get_layout = AsyncMock(return_value=None)

        poller = ContentPoller(mock_adapter)
        result = await poller.poll_layout()
        assert result is None

    @pytest.mark.asyncio
    async def test_poll_layout_success(self):
        """Test poll_layout returns layout data."""
        mock_adapter = self._create_mock_adapter()
        mock_layout = LayoutData(windows=[])
        mock_adapter.get_layout = AsyncMock(return_value=mock_layout)

        poller = ContentPoller(mock_adapter)
        result = await poller.poll_layout()

        assert result == mock_layout
        mock_adapter.get_layout.assert_called_once()

    @pytest.mark.asyncio
    async def test_poll_layout_with_exclude(self):
        """Test poller stores exclude names."""
        mock_adapter = self._create_mock_adapter()
        mock_adapter.get_layout = AsyncMock(return_value=LayoutData(windows=[]))

        poller = ContentPoller(mock_adapter, exclude_names=["htop"])
        await poller.poll_layout()

        # Exclude names are stored but not passed to adapter
        # (adapter handles exclusion in its own get_layout)
        assert poller._exclude_names == ["htop"]

    @pytest.mark.asyncio
    async def test_get_pane_content_returns_none(self):
        """Test get_pane_content when adapter returns None."""
        mock_adapter = self._create_mock_adapter()
        mock_adapter.get_pane_content = AsyncMock(return_value=None)

        poller = ContentPoller(mock_adapter)
        result = await poller.get_pane_content("pane-1")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_pane_content_success(self):
        """Test get_pane_content returns content."""
        mock_adapter = self._create_mock_adapter()
        mock_adapter.get_pane_content = AsyncMock(return_value="hello world")

        poller = ContentPoller(mock_adapter)
        result = await poller.get_pane_content("pane-1")

        assert result == "hello world"
        mock_adapter.get_pane_content.assert_called_once_with("pane-1")

    @pytest.mark.asyncio
    async def test_get_job_metadata_returns_none(self):
        """Test get_job_metadata when adapter returns None."""
        mock_adapter = self._create_mock_adapter()
        mock_adapter.get_job_metadata = AsyncMock(return_value=None)

        poller = ContentPoller(mock_adapter)
        result = await poller.get_job_metadata("pane-1")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_job_metadata_success(self):
        """Test get_job_metadata returns metadata."""
        mock_adapter = self._create_mock_adapter()
        mock_job = JobMetadata(job_name="vim", path="/home/user")
        mock_adapter.get_job_metadata = AsyncMock(return_value=mock_job)

        poller = ContentPoller(mock_adapter)
        result = await poller.get_job_metadata("pane-1")

        assert result == mock_job
        mock_adapter.get_job_metadata.assert_called_once_with("pane-1")
