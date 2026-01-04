"""Tests for render/detector.py"""

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from termsupervisor.render.detector import ChangeDetector


class TestChangeDetector:
    """Tests for ChangeDetector class."""

    def test_initial_state(self):
        """Test initial detector state."""
        detector = ChangeDetector()
        assert detector._refresh_lines > 0
        assert detector._waiting_refresh_lines > 0
        assert detector._flush_timeout > 0

    def test_custom_thresholds(self):
        """Test detector with custom thresholds."""
        detector = ChangeDetector(
            refresh_lines=10,
            waiting_refresh_lines=2,
            flush_timeout=30.0,
        )
        assert detector._refresh_lines == 10
        assert detector._waiting_refresh_lines == 2
        assert detector._flush_timeout == 30.0

    def test_should_refresh_first_render(self):
        """Test that first render always triggers refresh."""
        detector = ChangeDetector()
        result = detector.should_refresh("pane-1", "hello world")
        assert result is True

    def test_should_refresh_no_change(self):
        """Test no refresh when content hasn't changed."""
        detector = ChangeDetector()

        # First render
        detector.should_refresh("pane-1", "hello world")
        detector.mark_rendered("pane-1", "hello world")

        # Same content
        result = detector.should_refresh("pane-1", "hello world")
        assert result is False

    def test_should_refresh_small_change(self):
        """Test no refresh for small changes below threshold."""
        detector = ChangeDetector(refresh_lines=5)

        # First render
        detector.should_refresh("pane-1", "line1\nline2\nline3")
        detector.mark_rendered("pane-1", "line1\nline2\nline3")

        # Small change (1 line)
        result = detector.should_refresh("pane-1", "line1\nline2\nline3\nline4")
        assert result is False

    def test_should_refresh_large_change(self):
        """Test refresh triggered for large changes."""
        detector = ChangeDetector(refresh_lines=3)

        # First render
        detector.should_refresh("pane-1", "line1\nline2")
        detector.mark_rendered("pane-1", "line1\nline2")

        # Large change (5 lines added)
        result = detector.should_refresh(
            "pane-1", "line1\nline2\nline3\nline4\nline5\nline6\nline7"
        )
        assert result is True

    def test_should_refresh_waiting_state_lower_threshold(self):
        """Test lower threshold when in WAITING state."""
        detector = ChangeDetector(refresh_lines=5, waiting_refresh_lines=1)

        # First render
        detector.should_refresh("pane-1", "line1\nline2")
        detector.mark_rendered("pane-1", "line1\nline2")

        # Small change (1 line) - not enough for normal, but enough for WAITING
        result_normal = detector.should_refresh("pane-1", "line1\nline2\nline3")
        assert result_normal is False

        result_waiting = detector.should_refresh(
            "pane-1", "line1\nline2\nline3", is_waiting=True
        )
        assert result_waiting is True

    def test_should_refresh_timeout_fallback(self):
        """Test refresh triggered by timeout with small changes."""
        detector = ChangeDetector(refresh_lines=10, flush_timeout=5.0)

        # First render
        detector.should_refresh("pane-1", "line1")
        detector.mark_rendered("pane-1", "line1")

        # Small change with timeout
        with patch(
            "termsupervisor.render.detector.datetime"
        ) as mock_datetime:
            # Simulate time passing
            old_time = datetime.now()
            new_time = old_time + timedelta(seconds=10)
            mock_datetime.now.return_value = new_time

            # Also need to set _last_render_time to old time
            detector._last_render_time["pane-1"] = old_time

            result = detector.should_refresh("pane-1", "line1\nline2")
            assert result is True

    def test_mark_rendered(self):
        """Test marking a pane as rendered."""
        detector = ChangeDetector()

        detector.mark_rendered("pane-1", "hello world")

        assert "pane-1" in detector._last_render_content
        assert detector._last_render_content["pane-1"] == "hello world"
        assert "pane-1" in detector._last_render_time

    def test_remove_pane(self):
        """Test removing pane detection state."""
        detector = ChangeDetector()

        # Add state
        detector.should_refresh("pane-1", "test")
        detector.mark_rendered("pane-1", "test")

        assert "pane-1" in detector._last_render_content
        assert "pane-1" in detector._last_render_time

        # Remove
        detector.remove_pane("pane-1")

        assert "pane-1" not in detector._last_render_content
        assert "pane-1" not in detector._last_render_time

    def test_remove_nonexistent_pane(self):
        """Test removing nonexistent pane doesn't raise."""
        detector = ChangeDetector()
        detector.remove_pane("nonexistent")  # Should not raise

    def test_get_last_render_content(self):
        """Test getting last render content."""
        detector = ChangeDetector()

        assert detector.get_last_render_content("pane-1") is None

        detector.mark_rendered("pane-1", "hello")
        assert detector.get_last_render_content("pane-1") == "hello"

    def test_get_last_render_time(self):
        """Test getting last render time."""
        detector = ChangeDetector()

        assert detector.get_last_render_time("pane-1") is None

        detector.mark_rendered("pane-1", "hello")
        time = detector.get_last_render_time("pane-1")
        assert time is not None
        assert isinstance(time, datetime)

    def test_multiple_panes(self):
        """Test tracking multiple panes independently."""
        detector = ChangeDetector(refresh_lines=3)

        # First pane
        detector.should_refresh("pane-1", "a")
        detector.mark_rendered("pane-1", "a")

        # Second pane (first render triggers refresh)
        result = detector.should_refresh("pane-2", "b")
        assert result is True

        detector.mark_rendered("pane-2", "b")

        # Each pane tracks separately
        assert detector.get_last_render_content("pane-1") == "a"
        assert detector.get_last_render_content("pane-2") == "b"
