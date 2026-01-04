"""Tests for render/types.py"""

from datetime import datetime

import pytest

from termsupervisor.render.types import ContentSnapshot, PaneState, LayoutUpdate
from termsupervisor.adapters.iterm2.models import LayoutData


class TestContentSnapshot:
    """Tests for ContentSnapshot dataclass."""

    def test_create_snapshot(self):
        """Test creating a content snapshot."""
        snapshot = ContentSnapshot(
            pane_id="pane-1",
            content="hello world",
            content_hash="abc123",
            cleaned_content="hello world",
        )
        assert snapshot.pane_id == "pane-1"
        assert snapshot.content == "hello world"
        assert snapshot.content_hash == "abc123"
        assert snapshot.cleaned_content == "hello world"
        assert isinstance(snapshot.timestamp, datetime)

    def test_snapshot_with_custom_timestamp(self):
        """Test creating a snapshot with custom timestamp."""
        ts = datetime(2025, 1, 1, 12, 0, 0)
        snapshot = ContentSnapshot(
            pane_id="pane-1",
            content="test",
            content_hash="hash",
            cleaned_content="test",
            timestamp=ts,
        )
        assert snapshot.timestamp == ts


class TestPaneState:
    """Tests for PaneState dataclass."""

    def test_create_pane_state(self):
        """Test creating a pane state."""
        snapshot = ContentSnapshot(
            pane_id="pane-1",
            content="hello",
            content_hash="hash1",
            cleaned_content="hello",
        )
        state = PaneState(
            pane_id="pane-1",
            name="zsh",
            current=snapshot,
        )
        assert state.pane_id == "pane-1"
        assert state.name == "zsh"
        assert state.current == snapshot
        assert state.last_render is None
        assert state.last_render_at is None
        assert state.job is None
        assert state.is_waiting is False

    def test_pane_state_with_last_render(self):
        """Test pane state with last render info."""
        current = ContentSnapshot(
            pane_id="pane-1",
            content="current",
            content_hash="h1",
            cleaned_content="current",
        )
        last = ContentSnapshot(
            pane_id="pane-1",
            content="last",
            content_hash="h2",
            cleaned_content="last",
        )
        render_time = datetime(2025, 1, 1, 12, 0, 0)
        state = PaneState(
            pane_id="pane-1",
            name="zsh",
            current=current,
            last_render=last,
            last_render_at=render_time,
        )
        assert state.last_render == last
        assert state.last_render_at == render_time

    def test_pane_state_waiting_flag(self):
        """Test pane state with is_waiting flag."""
        snapshot = ContentSnapshot(
            pane_id="pane-1",
            content="test",
            content_hash="hash",
            cleaned_content="test",
        )
        state = PaneState(
            pane_id="pane-1",
            name="zsh",
            current=snapshot,
            is_waiting=True,
        )
        assert state.is_waiting is True


class TestLayoutUpdate:
    """Tests for LayoutUpdate dataclass."""

    def test_create_layout_update(self):
        """Test creating a layout update."""
        layout = LayoutData()
        update = LayoutUpdate(layout=layout)
        assert update.layout == layout
        assert update.updated_panes == []
        assert update.pane_states == {}

    def test_layout_update_with_updated_panes(self):
        """Test layout update with updated panes list."""
        layout = LayoutData()
        update = LayoutUpdate(
            layout=layout,
            updated_panes=["pane-1", "pane-2"],
        )
        assert update.updated_panes == ["pane-1", "pane-2"]

    def test_layout_update_with_pane_states(self):
        """Test layout update with pane states."""
        layout = LayoutData()
        snapshot = ContentSnapshot(
            pane_id="pane-1",
            content="test",
            content_hash="hash",
            cleaned_content="test",
        )
        state = PaneState(pane_id="pane-1", name="zsh", current=snapshot)
        update = LayoutUpdate(
            layout=layout,
            pane_states={"pane-1": state},
        )
        assert "pane-1" in update.pane_states
        assert update.pane_states["pane-1"] == state
