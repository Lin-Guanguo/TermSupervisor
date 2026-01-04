"""Tests for render/poller.py"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from termsupervisor.render.poller import ContentPoller
from termsupervisor.adapters.iterm2.models import (
    LayoutData,
    WindowInfo,
    TabInfo,
    PaneInfo,
)


class TestContentPoller:
    """Tests for ContentPoller class."""

    def test_init(self):
        """Test poller initialization."""
        mock_client = MagicMock()
        poller = ContentPoller(mock_client)
        assert poller._client == mock_client
        assert poller._exclude_names == []

    def test_init_with_exclude_names(self):
        """Test poller initialization with exclude names."""
        mock_client = MagicMock()
        poller = ContentPoller(mock_client, exclude_names=["htop", "vim"])
        assert poller._exclude_names == ["htop", "vim"]

    @pytest.mark.asyncio
    async def test_poll_layout_no_app(self):
        """Test poll_layout when app is not available."""
        mock_client = MagicMock()
        mock_client.get_app = AsyncMock(return_value=None)

        poller = ContentPoller(mock_client)
        result = await poller.poll_layout()
        assert result is None

    @pytest.mark.asyncio
    async def test_poll_layout_success(self):
        """Test poll_layout returns layout data."""
        mock_client = MagicMock()
        mock_app = MagicMock()
        mock_client.get_app = AsyncMock(return_value=mock_app)

        # Mock get_layout function
        with patch("termsupervisor.render.poller.get_layout") as mock_get_layout:
            mock_layout = LayoutData(windows=[])
            mock_get_layout.return_value = mock_layout

            poller = ContentPoller(mock_client)
            result = await poller.poll_layout()

            assert result == mock_layout
            mock_get_layout.assert_called_once_with(mock_app, [])

    @pytest.mark.asyncio
    async def test_poll_layout_with_exclude(self):
        """Test poll_layout passes exclude names."""
        mock_client = MagicMock()
        mock_app = MagicMock()
        mock_client.get_app = AsyncMock(return_value=mock_app)

        with patch("termsupervisor.render.poller.get_layout") as mock_get_layout:
            mock_layout = LayoutData(windows=[])
            mock_get_layout.return_value = mock_layout

            poller = ContentPoller(mock_client, exclude_names=["htop"])
            await poller.poll_layout()

            mock_get_layout.assert_called_once_with(mock_app, ["htop"])

    @pytest.mark.asyncio
    async def test_get_pane_content_no_app(self):
        """Test get_pane_content when app is not available."""
        mock_client = MagicMock()
        mock_client.get_app = AsyncMock(return_value=None)

        poller = ContentPoller(mock_client)
        result = await poller.get_pane_content("pane-1")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_pane_content_no_session(self):
        """Test get_pane_content when session doesn't exist."""
        mock_client = MagicMock()
        mock_app = MagicMock()
        mock_app.get_session_by_id.return_value = None
        mock_client.get_app = AsyncMock(return_value=mock_app)

        poller = ContentPoller(mock_client)
        result = await poller.get_pane_content("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_pane_content_success(self):
        """Test get_pane_content returns content."""
        mock_client = MagicMock()
        mock_app = MagicMock()
        mock_session = MagicMock()
        mock_app.get_session_by_id.return_value = mock_session
        mock_client.get_app = AsyncMock(return_value=mock_app)
        mock_client.get_session_content = AsyncMock(return_value="hello world")

        poller = ContentPoller(mock_client)
        result = await poller.get_pane_content("pane-1")

        assert result == "hello world"
        mock_app.get_session_by_id.assert_called_once_with("pane-1")
        mock_client.get_session_content.assert_called_once_with(mock_session)

    @pytest.mark.asyncio
    async def test_get_job_metadata_no_app(self):
        """Test get_job_metadata when app is not available."""
        mock_client = MagicMock()
        mock_client.get_app = AsyncMock(return_value=None)

        poller = ContentPoller(mock_client)
        result = await poller.get_job_metadata("pane-1")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_job_metadata_no_session(self):
        """Test get_job_metadata when session doesn't exist."""
        mock_client = MagicMock()
        mock_app = MagicMock()
        mock_app.get_session_by_id.return_value = None
        mock_client.get_app = AsyncMock(return_value=mock_app)

        poller = ContentPoller(mock_client)
        result = await poller.get_job_metadata("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_job_metadata_success(self):
        """Test get_job_metadata returns metadata."""
        mock_client = MagicMock()
        mock_app = MagicMock()
        mock_session = MagicMock()
        mock_job = MagicMock()
        mock_app.get_session_by_id.return_value = mock_session
        mock_client.get_app = AsyncMock(return_value=mock_app)
        mock_client.get_session_job_metadata = AsyncMock(return_value=mock_job)

        poller = ContentPoller(mock_client)
        result = await poller.get_job_metadata("pane-1")

        assert result == mock_job
        mock_client.get_session_job_metadata.assert_called_once_with(mock_session)
