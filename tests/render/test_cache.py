"""Tests for render/cache.py"""

from datetime import datetime

import pytest

from termsupervisor.render.cache import LayoutCache
from termsupervisor.adapters.iterm2.models import (
    LayoutData,
    WindowInfo,
    TabInfo,
    PaneInfo,
)


class TestLayoutCache:
    """Tests for LayoutCache class."""

    def test_initial_state(self):
        """Test initial cache state."""
        cache = LayoutCache()
        assert isinstance(cache.layout, LayoutData)
        assert cache.layout.windows == []
        assert cache.pane_states == {}

    def test_update_layout(self):
        """Test updating layout data."""
        cache = LayoutCache()
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

        cache.update_layout(layout)
        assert cache.layout == layout
        assert len(cache.layout.windows) == 1

    def test_update_pane_state(self):
        """Test updating pane state."""
        cache = LayoutCache()
        state = cache.update_pane_state(
            pane_id="pane-1",
            name="zsh",
            content="hello",
            content_hash="hash1",
            cleaned_content="hello",
        )

        assert state.pane_id == "pane-1"
        assert state.name == "zsh"
        assert state.current.content == "hello"
        assert state.current.content_hash == "hash1"
        assert state.is_waiting is False

    def test_update_pane_state_existing(self):
        """Test updating existing pane state."""
        cache = LayoutCache()

        # First update
        cache.update_pane_state(
            pane_id="pane-1",
            name="zsh",
            content="first",
            content_hash="h1",
            cleaned_content="first",
        )

        # Second update
        state = cache.update_pane_state(
            pane_id="pane-1",
            name="bash",
            content="second",
            content_hash="h2",
            cleaned_content="second",
        )

        assert state.name == "bash"
        assert state.current.content == "second"
        assert state.current.content_hash == "h2"

    def test_update_pane_state_with_waiting(self):
        """Test updating pane state with is_waiting flag."""
        cache = LayoutCache()
        state = cache.update_pane_state(
            pane_id="pane-1",
            name="zsh",
            content="hello",
            content_hash="hash1",
            cleaned_content="hello",
            is_waiting=True,
        )
        assert state.is_waiting is True

    def test_mark_rendered(self):
        """Test marking a pane as rendered."""
        cache = LayoutCache()

        # Create pane state first
        cache.update_pane_state(
            pane_id="pane-1",
            name="zsh",
            content="hello",
            content_hash="hash1",
            cleaned_content="hello",
        )

        # Mark as rendered
        cache.mark_rendered("pane-1")

        state = cache.get_pane_state("pane-1")
        assert state is not None
        assert state.last_render is not None
        assert state.last_render.content == "hello"
        assert state.last_render_at is not None

    def test_mark_rendered_nonexistent_pane(self):
        """Test marking nonexistent pane as rendered does nothing."""
        cache = LayoutCache()
        cache.mark_rendered("nonexistent")  # Should not raise

    def test_get_pane_state_nonexistent(self):
        """Test getting nonexistent pane state returns None."""
        cache = LayoutCache()
        assert cache.get_pane_state("nonexistent") is None

    def test_remove_pane(self):
        """Test removing a pane."""
        cache = LayoutCache()

        cache.update_pane_state(
            pane_id="pane-1",
            name="zsh",
            content="test",
            content_hash="h1",
            cleaned_content="test",
        )

        assert cache.get_pane_state("pane-1") is not None

        cache.remove_pane("pane-1")

        assert cache.get_pane_state("pane-1") is None

    def test_get_current_pane_ids(self):
        """Test getting current pane IDs from layout."""
        cache = LayoutCache()

        pane1 = PaneInfo(
            pane_id="pane-1", name="zsh", index=0, x=0, y=0, width=50, height=50
        )
        pane2 = PaneInfo(
            pane_id="pane-2", name="vim", index=1, x=50, y=0, width=50, height=50
        )
        tab = TabInfo(tab_id="tab-1", name="Tab1", panes=[pane1, pane2])
        window = WindowInfo(window_id="win-1", name="Window1", x=0, y=0, width=800, height=600, tabs=[tab])
        layout = LayoutData(windows=[window])

        cache.update_layout(layout)

        pane_ids = cache.get_current_pane_ids()
        assert pane_ids == {"pane-1", "pane-2"}

    def test_cleanup_closed_panes(self):
        """Test cleaning up closed panes."""
        cache = LayoutCache()

        # Add pane states for two panes
        cache.update_pane_state(
            pane_id="pane-1",
            name="zsh",
            content="test1",
            content_hash="h1",
            cleaned_content="test1",
        )
        cache.update_pane_state(
            pane_id="pane-2",
            name="vim",
            content="test2",
            content_hash="h2",
            cleaned_content="test2",
        )

        # Update layout with only pane-1
        pane1 = PaneInfo(
            pane_id="pane-1", name="zsh", index=0, x=0, y=0, width=100, height=50
        )
        tab = TabInfo(tab_id="tab-1", name="Tab1", panes=[pane1])
        window = WindowInfo(window_id="win-1", name="Window1", x=0, y=0, width=800, height=600, tabs=[tab])
        layout = LayoutData(windows=[window])
        cache.update_layout(layout)

        # Cleanup should remove pane-2
        closed = cache.cleanup_closed_panes()
        assert closed == ["pane-2"]
        assert cache.get_pane_state("pane-1") is not None
        assert cache.get_pane_state("pane-2") is None

    def test_cleanup_closed_panes_none_closed(self):
        """Test cleanup when no panes are closed."""
        cache = LayoutCache()

        cache.update_pane_state(
            pane_id="pane-1",
            name="zsh",
            content="test",
            content_hash="h1",
            cleaned_content="test",
        )

        pane1 = PaneInfo(
            pane_id="pane-1", name="zsh", index=0, x=0, y=0, width=100, height=50
        )
        tab = TabInfo(tab_id="tab-1", name="Tab1", panes=[pane1])
        window = WindowInfo(window_id="win-1", name="Window1", x=0, y=0, width=800, height=600, tabs=[tab])
        layout = LayoutData(windows=[window])
        cache.update_layout(layout)

        closed = cache.cleanup_closed_panes()
        assert closed == []
