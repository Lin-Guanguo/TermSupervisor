"""Tests for render/pipeline.py"""

from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

import pytest

from termsupervisor.render.pipeline import RenderPipeline
from termsupervisor.render.types import LayoutUpdate
from termsupervisor.adapters.iterm2.models import (
    LayoutData,
    WindowInfo,
    TabInfo,
    PaneInfo,
)


class TestRenderPipeline:
    """Tests for RenderPipeline class."""

    def _create_mock_client(self):
        """Create a mock ITerm2Client."""
        return MagicMock()

    def test_init(self):
        """Test pipeline initialization."""
        mock_client = self._create_mock_client()
        pipeline = RenderPipeline(mock_client)

        assert pipeline._poller is not None
        assert pipeline._detector is not None
        assert pipeline._cache is not None
        assert pipeline._callbacks == []
        assert pipeline._running is False

    def test_init_with_options(self):
        """Test pipeline initialization with options."""
        mock_client = self._create_mock_client()
        pipeline = RenderPipeline(
            mock_client,
            exclude_names=["htop"],
            refresh_lines=10,
            waiting_refresh_lines=2,
            flush_timeout=30.0,
        )
        assert pipeline._poller._exclude_names == ["htop"]
        assert pipeline._detector._refresh_lines == 10

    def test_cache_property(self):
        """Test cache property access."""
        mock_client = self._create_mock_client()
        pipeline = RenderPipeline(mock_client)
        assert pipeline.cache is pipeline._cache

    def test_layout_property(self):
        """Test layout property access."""
        mock_client = self._create_mock_client()
        pipeline = RenderPipeline(mock_client)
        assert pipeline.layout == pipeline._cache.layout

    def test_on_update_callback(self):
        """Test registering update callback."""
        mock_client = self._create_mock_client()
        pipeline = RenderPipeline(mock_client)

        callback = AsyncMock()
        pipeline.on_update(callback)

        assert callback in pipeline._callbacks

    @pytest.mark.asyncio
    async def test_tick_no_layout(self):
        """Test tick when layout is unavailable."""
        mock_client = self._create_mock_client()
        pipeline = RenderPipeline(mock_client)

        with patch.object(pipeline._poller, "poll_layout", return_value=None):
            update = await pipeline.tick()

            assert isinstance(update, LayoutUpdate)
            assert update.updated_panes == []

    @pytest.mark.asyncio
    async def test_tick_with_panes(self):
        """Test tick with panes in layout."""
        mock_client = self._create_mock_client()
        pipeline = RenderPipeline(mock_client)

        # Create mock layout
        pane = PaneInfo(
            pane_id="pane-1",
            name="zsh",
            index=0,
            x=0,
            y=0,
            width=100,
            height=50,
        )
        tab = TabInfo(tab_id="tab-1", name="Tab1", panes=[pane])
        window = WindowInfo(window_id="win-1", name="Window1", x=0, y=0, width=800, height=600, tabs=[tab])
        layout = LayoutData(windows=[window])

        with patch.object(
            pipeline._poller, "poll_layout", new_callable=AsyncMock
        ) as mock_poll:
            mock_poll.return_value = layout

            with patch.object(
                pipeline._poller, "get_pane_content", new_callable=AsyncMock
            ) as mock_content:
                mock_content.return_value = "hello world"

                with patch.object(
                    pipeline._poller, "get_job_metadata", new_callable=AsyncMock
                ) as mock_job:
                    mock_job.return_value = None

                    update = await pipeline.tick()

                    assert isinstance(update, LayoutUpdate)
                    # First tick should trigger refresh for new pane
                    assert "pane-1" in update.updated_panes
                    assert "pane-1" in update.pane_states

    @pytest.mark.asyncio
    async def test_tick_no_content_change(self):
        """Test tick when content hasn't changed."""
        mock_client = self._create_mock_client()
        pipeline = RenderPipeline(mock_client)

        pane = PaneInfo(
            pane_id="pane-1",
            name="zsh",
            index=0,
            x=0,
            y=0,
            width=100,
            height=50,
        )
        tab = TabInfo(tab_id="tab-1", name="Tab1", panes=[pane])
        window = WindowInfo(window_id="win-1", name="Window1", x=0, y=0, width=800, height=600, tabs=[tab])
        layout = LayoutData(windows=[window])

        with patch.object(
            pipeline._poller, "poll_layout", new_callable=AsyncMock
        ) as mock_poll:
            mock_poll.return_value = layout

            with patch.object(
                pipeline._poller, "get_pane_content", new_callable=AsyncMock
            ) as mock_content:
                mock_content.return_value = "hello world"

                with patch.object(
                    pipeline._poller, "get_job_metadata", new_callable=AsyncMock
                ) as mock_job:
                    mock_job.return_value = None

                    # First tick
                    await pipeline.tick()

                    # Second tick - same content
                    update = await pipeline.tick()

                    # Should not be in updated_panes since content hasn't changed
                    assert "pane-1" not in update.updated_panes

    @pytest.mark.asyncio
    async def test_tick_with_status_provider_waiting(self):
        """Test tick derives is_waiting from status_provider."""
        mock_client = self._create_mock_client()
        pipeline = RenderPipeline(mock_client)

        # Set status provider that returns WAITING status for pane-1
        def status_provider(pane_id):
            if pane_id == "pane-1":
                return {"status": "waiting_approval", "status_color": "yellow"}
            return None

        pipeline.set_status_provider(status_provider)

        pane = PaneInfo(
            pane_id="pane-1",
            name="zsh",
            index=0,
            x=0,
            y=0,
            width=100,
            height=50,
        )
        tab = TabInfo(tab_id="tab-1", name="Tab1", panes=[pane])
        window = WindowInfo(window_id="win-1", name="Window1", x=0, y=0, width=800, height=600, tabs=[tab])
        layout = LayoutData(windows=[window])

        with patch.object(
            pipeline._poller, "poll_layout", new_callable=AsyncMock
        ) as mock_poll:
            mock_poll.return_value = layout

            with patch.object(
                pipeline._poller, "get_pane_content", new_callable=AsyncMock
            ) as mock_content:
                mock_content.return_value = "hello"

                with patch.object(
                    pipeline._poller, "get_job_metadata", new_callable=AsyncMock
                ) as mock_job:
                    mock_job.return_value = None

                    await pipeline.tick()

                    # Verify is_waiting is set
                    state = pipeline.cache.get_pane_state("pane-1")
                    assert state is not None
                    assert state.is_waiting is True

    @pytest.mark.asyncio
    async def test_tick_notifies_callbacks(self):
        """Test tick notifies registered callbacks."""
        mock_client = self._create_mock_client()
        pipeline = RenderPipeline(mock_client)

        callback = AsyncMock()
        pipeline.on_update(callback)

        layout = LayoutData(windows=[])

        with patch.object(
            pipeline._poller, "poll_layout", new_callable=AsyncMock
        ) as mock_poll:
            mock_poll.return_value = layout

            await pipeline.tick()

            callback.assert_called_once()
            call_arg = callback.call_args[0][0]
            assert isinstance(call_arg, LayoutUpdate)

    @pytest.mark.asyncio
    async def test_tick_callback_error_handled(self):
        """Test tick handles callback errors gracefully."""
        mock_client = self._create_mock_client()
        pipeline = RenderPipeline(mock_client)

        error_callback = AsyncMock(side_effect=Exception("callback error"))
        success_callback = AsyncMock()
        pipeline.on_update(error_callback)
        pipeline.on_update(success_callback)

        layout = LayoutData(windows=[])

        with patch.object(
            pipeline._poller, "poll_layout", new_callable=AsyncMock
        ) as mock_poll:
            mock_poll.return_value = layout

            # Should not raise
            await pipeline.tick()

            # Second callback should still be called
            success_callback.assert_called_once()

    @pytest.mark.asyncio
    async def test_tick_cleans_up_closed_panes(self):
        """Test tick cleans up closed panes."""
        mock_client = self._create_mock_client()
        pipeline = RenderPipeline(mock_client)

        # Initial layout with two panes
        pane1 = PaneInfo(
            pane_id="pane-1", name="zsh", index=0, x=0, y=0, width=50, height=50
        )
        pane2 = PaneInfo(
            pane_id="pane-2", name="vim", index=1, x=50, y=0, width=50, height=50
        )
        tab = TabInfo(tab_id="tab-1", name="Tab1", panes=[pane1, pane2])
        window = WindowInfo(window_id="win-1", name="Window1", x=0, y=0, width=800, height=600, tabs=[tab])
        layout1 = LayoutData(windows=[window])

        with patch.object(
            pipeline._poller, "poll_layout", new_callable=AsyncMock
        ) as mock_poll:
            mock_poll.return_value = layout1

            with patch.object(
                pipeline._poller, "get_pane_content", new_callable=AsyncMock
            ) as mock_content:
                mock_content.return_value = "content"

                with patch.object(
                    pipeline._poller, "get_job_metadata", new_callable=AsyncMock
                ) as mock_job:
                    mock_job.return_value = None

                    # First tick - both panes
                    await pipeline.tick()

                    assert pipeline.cache.get_pane_state("pane-1") is not None
                    assert pipeline.cache.get_pane_state("pane-2") is not None

        # Now layout with only pane-1
        tab2 = TabInfo(tab_id="tab-1", name="Tab1", panes=[pane1])
        window2 = WindowInfo(window_id="win-1", name="Window1", x=0, y=0, width=800, height=600, tabs=[tab2])
        layout2 = LayoutData(windows=[window2])

        with patch.object(
            pipeline._poller, "poll_layout", new_callable=AsyncMock
        ) as mock_poll:
            mock_poll.return_value = layout2

            with patch.object(
                pipeline._poller, "get_pane_content", new_callable=AsyncMock
            ) as mock_content:
                mock_content.return_value = "content"

                with patch.object(
                    pipeline._poller, "get_job_metadata", new_callable=AsyncMock
                ) as mock_job:
                    mock_job.return_value = None

                    # Second tick - pane-2 should be cleaned up
                    await pipeline.tick()

                    assert pipeline.cache.get_pane_state("pane-1") is not None
                    assert pipeline.cache.get_pane_state("pane-2") is None

    def test_stop(self):
        """Test stop method."""
        mock_client = self._create_mock_client()
        pipeline = RenderPipeline(mock_client)

        pipeline._running = True
        pipeline.stop()

        assert pipeline._running is False

    def test_get_pane_content(self):
        """Test getting cached pane content."""
        mock_client = self._create_mock_client()
        pipeline = RenderPipeline(mock_client)

        # No content initially
        assert pipeline.get_pane_content("pane-1") is None

        # Add content to cache
        pipeline.cache.update_pane_state(
            pane_id="pane-1",
            name="zsh",
            content="hello world",
            content_hash="hash1",
            cleaned_content="hello world",
        )

        assert pipeline.get_pane_content("pane-1") == "hello world"

    def test_get_job_metadata(self):
        """Test getting cached job metadata."""
        mock_client = self._create_mock_client()
        pipeline = RenderPipeline(mock_client)

        # No metadata initially
        assert pipeline.get_job_metadata("pane-1") is None

        # Add state with job metadata
        mock_job = MagicMock()
        pipeline.cache.update_pane_state(
            pane_id="pane-1",
            name="zsh",
            content="hello",
            content_hash="hash1",
            cleaned_content="hello",
            job=mock_job,
        )

        assert pipeline.get_job_metadata("pane-1") == mock_job
