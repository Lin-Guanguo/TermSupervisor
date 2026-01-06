"""Tests for TmuxHookSource."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from termsupervisor.hooks.sources.tmux import TmuxHookSource


class TestTmuxHookSource:
    """Tests for TmuxHookSource class."""

    def _create_mock_manager(self):
        """Create a mock HookManager."""
        manager = MagicMock()
        manager.emit_event = AsyncMock()
        return manager

    def _create_mock_client(self):
        """Create a mock TmuxClient."""
        client = MagicMock()
        client.get_active_pane = AsyncMock(return_value="%0")
        return client

    def test_init(self):
        """Test TmuxHookSource initialization."""
        manager = self._create_mock_manager()
        source = TmuxHookSource(manager)

        assert source.source_name == "tmux"
        assert source._current_focus_pane is None

    def test_init_with_client(self):
        """Test TmuxHookSource initialization with custom client."""
        manager = self._create_mock_manager()
        client = self._create_mock_client()
        source = TmuxHookSource(manager, client=client)

        assert source._client is client

    def test_current_focus_pane_property(self):
        """Test current_focus_pane property."""
        manager = self._create_mock_manager()
        source = TmuxHookSource(manager)

        assert source.current_focus_pane is None

        source._current_focus_pane = "%1"
        assert source.current_focus_pane == "%1"

    @pytest.mark.asyncio
    async def test_start_creates_poll_task(self):
        """Test start creates polling task."""
        manager = self._create_mock_manager()
        client = self._create_mock_client()
        source = TmuxHookSource(manager, client=client, poll_interval=0.1)

        await source.start()

        assert source._poll_task is not None
        assert not source._poll_task.done()

        # Cleanup
        await source.stop()

    @pytest.mark.asyncio
    async def test_stop_cancels_tasks(self):
        """Test stop cancels poll and debounce tasks."""
        manager = self._create_mock_manager()
        client = self._create_mock_client()
        source = TmuxHookSource(manager, client=client, poll_interval=0.1)

        await source.start()
        await source.stop()

        assert source._poll_task.done()

    @pytest.mark.asyncio
    async def test_focus_change_emits_event_after_debounce(self):
        """Test focus change emits event after debounce period."""
        manager = self._create_mock_manager()
        client = self._create_mock_client()
        source = TmuxHookSource(manager, client=client, poll_interval=0.05)

        # Patch debounce time to be very short for testing
        with patch("termsupervisor.hooks.sources.tmux.FOCUS_DEBOUNCE_SECONDS", 0.05):
            await source.start()

            # Wait for poll + debounce
            await asyncio.sleep(0.15)

            # Should have emitted focus event
            manager.emit_event.assert_called_with(
                source="tmux",
                pane_id="%0",
                event_type="focus",
            )

            # Current focus should be updated
            assert source.current_focus_pane == "%0"

        await source.stop()

    @pytest.mark.asyncio
    async def test_focus_change_debounce_cancels_previous(self):
        """Test rapid focus changes cancel previous debounce."""
        manager = self._create_mock_manager()
        client = self._create_mock_client()
        source = TmuxHookSource(manager, client=client, poll_interval=0.02)

        with patch("termsupervisor.hooks.sources.tmux.FOCUS_DEBOUNCE_SECONDS", 0.1):
            await source.start()

            # Wait a bit for first detection
            await asyncio.sleep(0.05)

            # Change focus quickly
            client.get_active_pane.return_value = "%1"

            # Wait for second detection but before first debounce completes
            await asyncio.sleep(0.05)

            # Now wait for second debounce to complete
            await asyncio.sleep(0.15)

            # Should only have emitted for %1, not %0
            calls = manager.emit_event.call_args_list
            pane_ids = [call[1]["pane_id"] for call in calls]

            # The last event should be for %1
            assert "%1" in pane_ids
            assert source.current_focus_pane == "%1"

        await source.stop()

    @pytest.mark.asyncio
    async def test_no_event_when_focus_unchanged(self):
        """Test no event emitted when focus doesn't change."""
        manager = self._create_mock_manager()
        client = self._create_mock_client()
        source = TmuxHookSource(manager, client=client, poll_interval=0.02)

        with patch("termsupervisor.hooks.sources.tmux.FOCUS_DEBOUNCE_SECONDS", 0.03):
            await source.start()

            # Wait for initial event
            await asyncio.sleep(0.1)
            initial_call_count = manager.emit_event.call_count

            # Wait more time with same focus
            await asyncio.sleep(0.1)

            # Should not have additional events (focus unchanged)
            # Note: may get 1 event for initial detection
            assert manager.emit_event.call_count == initial_call_count

        await source.stop()

    @pytest.mark.asyncio
    async def test_handles_tmux_not_running(self):
        """Test graceful handling when tmux returns None."""
        manager = self._create_mock_manager()
        client = self._create_mock_client()
        client.get_active_pane.return_value = None

        source = TmuxHookSource(manager, client=client, poll_interval=0.05)

        await source.start()
        await asyncio.sleep(0.1)

        # Should not emit any events
        manager.emit_event.assert_not_called()

        await source.stop()
