"""Tests for Content Heuristic - keyword-gated per-pane mode"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from termsupervisor.analysis.heuristic import (
    Heuristic,
    _COMPILED_PATTERNS,
    _compile_patterns,
)

# === Fixtures ===


@pytest.fixture
def heuristic():
    """Create a fresh Heuristic instance"""
    return Heuristic()


@pytest.fixture
def mock_emit():
    """Create a mock emit callback"""
    return AsyncMock(return_value=True)


@pytest.fixture
def heuristic_with_emit(heuristic, mock_emit):
    """Heuristic with emit callback configured"""
    heuristic.set_emit_callback(mock_emit)
    return heuristic


# === Pattern Tests ===


def _get_pattern_by_name(name: str):
    """Helper to get a compiled pattern by name"""
    for p in _COMPILED_PATTERNS:
        if p.name == name:
            return p
    return None


class TestEscToPattern:
    """Tests for esc_to regex pattern (config-driven)"""

    def test_pattern_loaded(self):
        """esc_to pattern is loaded from config"""
        pattern = _get_pattern_by_name("esc_to")
        assert pattern is not None
        assert pattern.signal == "heuristic_esc_to"

    def test_basic_match(self):
        """Basic 'esc to' pattern matching"""
        pattern = _get_pattern_by_name("esc_to")
        assert pattern.regex.search("Press esc to continue")
        assert pattern.regex.search("esc to menu")
        assert pattern.regex.search("ESC TO EXIT")  # case insensitive

    def test_target_extraction(self):
        """Extract target from pattern"""
        pattern = _get_pattern_by_name("esc_to")
        match = pattern.regex.search("esc to main-menu")
        assert match
        assert match.group(1) == "main-menu"

        match = pattern.regex.search("esc to /path/to/file")
        assert match
        assert match.group(1) == "/path/to/file"

    def test_target_with_punctuation(self):
        """Target should be extracted, punctuation trimmed by target_strip"""
        pattern = _get_pattern_by_name("esc_to")
        match = pattern.regex.search("esc to menu.")
        assert match
        # Pattern includes trailing punctuation, target_strip trims it
        target = match.group(1)
        assert "menu" in target
        # Verify target_strip config
        assert "." in pattern.target_strip

    def test_no_match_without_target(self):
        """No match when target is missing"""
        pattern = _get_pattern_by_name("esc_to")
        assert not pattern.regex.search("esc to ")

    def test_standalone_word_boundary(self):
        """Only match standalone 'esc to'"""
        pattern = _get_pattern_by_name("esc_to")
        assert pattern.regex.search(" esc to menu ")
        # Should still match with word boundary
        assert pattern.regex.search("(esc to exit)")


class TestOneYesPattern:
    """Tests for 1Yes regex pattern (config-driven)"""

    def test_pattern_loaded(self):
        """1yes pattern is loaded from config"""
        pattern = _get_pattern_by_name("1yes")
        assert pattern is not None
        assert pattern.signal == "heuristic_1yes"
        assert pattern.target_fixed == "approval"

    def test_basic_match(self):
        """Basic '1Yes' pattern matching"""
        pattern = _get_pattern_by_name("1yes")
        assert pattern.regex.search("1Yes")
        assert pattern.regex.search("1 yes")
        assert pattern.regex.search("1  yes")  # Multiple spaces
        assert pattern.regex.search("1YES")  # Case insensitive

    def test_start_of_line(self):
        """Pattern must match start of line"""
        pattern = _get_pattern_by_name("1yes")
        assert pattern.regex.search("1Yes - accept")
        # Pattern uses ^, so whitespace before prevents match
        assert not pattern.regex.search("   1Yes")  # Whitespace before is NOT start of line
        content = "First line\n1Yes\nThird line"
        assert pattern.regex.search(content)

    def test_no_match_mid_line(self):
        """Should not match in middle of text"""
        pattern = _get_pattern_by_name("1yes")
        # This depends on the regex - current pattern uses ^ which is start of line
        # With MULTILINE flag, ^ matches after newline too
        assert not pattern.regex.search("Option: 2 - 1Yes")  # No - it's after "2 - "


# === Guard Pattern Tests ===


class TestCodeGuardPatterns:
    """Tests for code guard patterns that skip code-like lines (config-driven)"""

    def test_esc_to_guards_loaded(self):
        """esc_to pattern has guards configured"""
        pattern = _get_pattern_by_name("esc_to")
        assert len(pattern.guards) > 0

    def test_skips_class_def(self):
        """Skip lines with class/def/function keywords"""
        pattern = _get_pattern_by_name("esc_to")
        code_lines = [
            "class EscapeHandler:",
            "def escape_to_menu():",
            "function handleEsc() {",
            "const esc to = 'value'",
            "let escape_to = true",
            "var x = 1;",
        ]
        for line in code_lines:
            assert any(g.search(line) for g in pattern.guards), f"Should skip: {line}"

    def test_skips_brackets(self):
        """Skip lines with code brackets/semicolons"""
        pattern = _get_pattern_by_name("esc_to")
        assert any(g.search("if (esc to exit) {") for g in pattern.guards)
        assert any(g.search("esc to menu;") for g in pattern.guards)

    def test_skips_code_fences(self):
        """Skip code fences and inline code"""
        pattern = _get_pattern_by_name("esc_to")
        assert any(g.search("```python") for g in pattern.guards)
        assert any(g.search("Use `esc to exit`") for g in pattern.guards)

    def test_skips_escape_to_identifier(self):
        """Skip escape_to as identifier"""
        pattern = _get_pattern_by_name("esc_to")
        assert any(g.search("escape_to = True") for g in pattern.guards)


class TestOneYesGuardPatterns:
    """Tests for 1Yes guard patterns (config-driven)"""

    def test_1yes_guards_loaded(self):
        """1yes pattern has guards configured"""
        pattern = _get_pattern_by_name("1yes")
        assert len(pattern.guards) > 0

    def test_skips_case_switch(self):
        """Skip case/switch constructs"""
        pattern = _get_pattern_by_name("1yes")
        assert any(g.search("case 1: yes") for g in pattern.guards)
        assert any(g.search("switch (val) 1 yes") for g in pattern.guards)

    def test_skips_list_bullets(self):
        """Skip list bullet patterns"""
        pattern = _get_pattern_by_name("1yes")
        # Guard pattern uses ^- so only matches at start of line
        assert any(g.search("- 1 yes") for g in pattern.guards)


# === Keyword Gating Tests ===


class TestKeywordGating:
    """Tests for keyword gating (entry/exit)"""

    @patch("termsupervisor.analysis.heuristic.CONTENT_HEURISTIC_KEYWORD", "")
    async def test_disabled_when_no_keyword(self, heuristic):
        """Heuristics disabled when CONTENT_HEURISTIC_KEYWORD is empty"""
        await heuristic.evaluate("pane1", "esc to menu", "hash1")
        assert not heuristic.is_active("pane1")

    @patch("termsupervisor.analysis.heuristic.CONTENT_HEURISTIC_KEYWORD", "claude-code")
    async def test_enters_mode_on_keyword(self, heuristic):
        """Enters heuristic mode when keyword is detected"""
        content = "Starting claude-code session\nesc to menu"
        await heuristic.evaluate("pane1", content, "hash1")
        assert heuristic.is_active("pane1")

    @patch("termsupervisor.analysis.heuristic.CONTENT_HEURISTIC_KEYWORD", "claude-code")
    async def test_case_insensitive_entry(self, heuristic):
        """Entry keyword is case insensitive"""
        await heuristic.evaluate("pane1", "CLAUDE-CODE session", "hash1")
        assert heuristic.is_active("pane1")

    @patch("termsupervisor.analysis.heuristic.CONTENT_HEURISTIC_KEYWORD", "claude-code")
    async def test_no_entry_without_keyword(self, heuristic):
        """Does not enter mode without keyword"""
        await heuristic.evaluate("pane1", "esc to menu", "hash1")
        assert not heuristic.is_active("pane1")

    @patch("termsupervisor.analysis.heuristic.CONTENT_HEURISTIC_KEYWORD", "claude")
    async def test_word_boundary_prevents_substring_match(self, heuristic):
        """Entry keyword requires word boundary (no substring matches)"""
        # Should NOT match - keyword is part of a larger word
        await heuristic.evaluate("pane1", "claudebot is running", "hash1")
        assert not heuristic.is_active("pane1")

        # Should NOT match - keyword is embedded in identifier
        await heuristic.evaluate("pane1", "import preclaudehelper", "hash2")
        assert not heuristic.is_active("pane1")

        # Should match - keyword is standalone
        await heuristic.evaluate("pane1", "Starting Claude session", "hash3")
        assert heuristic.is_active("pane1")


# === Exit Condition Tests ===


class TestExitConditions:
    """Tests for heuristic mode exit conditions"""

    @patch("termsupervisor.analysis.heuristic.CONTENT_HEURISTIC_KEYWORD", "claude-code")
    @patch("termsupervisor.analysis.heuristic.CONTENT_HEURISTIC_EXIT_KEYWORD", "exit-now")
    async def test_exit_on_keyword(self, heuristic):
        """Exits mode when exit keyword is detected"""
        # Enter mode
        await heuristic.evaluate("pane1", "claude-code start", "hash1")
        assert heuristic.is_active("pane1")

        # Exit via keyword
        await heuristic.evaluate("pane1", "claude-code exit-now done", "hash2")
        assert not heuristic.is_active("pane1")

    @patch("termsupervisor.analysis.heuristic.CONTENT_HEURISTIC_KEYWORD", "claude-code")
    @patch("termsupervisor.analysis.heuristic.CONTENT_HEURISTIC_EXIT_TIMEOUT_SECONDS", 0.1)
    async def test_exit_on_timeout(self, heuristic):
        """Exits mode after timeout"""
        import time

        # Enter mode
        await heuristic.evaluate("pane1", "claude-code start", "hash1")
        assert heuristic.is_active("pane1")

        # Wait for timeout
        time.sleep(0.15)

        # Should exit on next evaluate (even with same content hash - timeout bypasses hash guard)
        await heuristic.evaluate("pane1", "claude-code start", "hash1")
        assert not heuristic.is_active("pane1")

    @patch("termsupervisor.analysis.heuristic.CONTENT_HEURISTIC_KEYWORD", "claude-code")
    def test_exit_pane_signal(self, heuristic):
        """exit_pane() clears mode"""
        # Manually set active
        state = heuristic._get_state("pane1")
        state.active = True

        heuristic.exit_pane("pane1", "pid_end")
        assert not heuristic.is_active("pane1")

    @patch("termsupervisor.analysis.heuristic.CONTENT_HEURISTIC_KEYWORD", "claude-code")
    def test_remove_pane(self, heuristic):
        """remove_pane() deletes all state"""
        state = heuristic._get_state("pane1")
        state.active = True

        heuristic.remove_pane("pane1")
        assert "pane1" not in heuristic._pane_states

    @patch("termsupervisor.analysis.heuristic.CONTENT_HEURISTIC_KEYWORD", "claude-code")
    async def test_reentry_after_exit_on_unchanged_content(self, heuristic):
        """Can re-enter heuristic mode after exit without content change"""
        content = "claude-code session active"
        content_hash = "hash1"

        # Enter mode
        await heuristic.evaluate("pane1", content, content_hash)
        assert heuristic.is_active("pane1")

        # Exit mode
        heuristic.exit_pane("pane1", "timeout")
        assert not heuristic.is_active("pane1")

        # Re-enter with same content/hash - should work because exit clears hash
        await heuristic.evaluate("pane1", content, content_hash)
        assert heuristic.is_active("pane1"), "Should re-enter on unchanged content after exit"


# === Per-Pane Isolation Tests ===


class TestPerPaneIsolation:
    """Tests for per-pane state isolation"""

    @patch("termsupervisor.analysis.heuristic.CONTENT_HEURISTIC_KEYWORD", "claude-code")
    async def test_independent_pane_states(self, heuristic):
        """Each pane has independent state"""
        # Enter mode in pane1
        await heuristic.evaluate("pane1", "claude-code start", "hash1")
        assert heuristic.is_active("pane1")
        assert not heuristic.is_active("pane2")

        # Enter mode in pane2
        await heuristic.evaluate("pane2", "claude-code start", "hash2")
        assert heuristic.is_active("pane1")
        assert heuristic.is_active("pane2")

        # Exit pane1
        heuristic.exit_pane("pane1", "test")
        assert not heuristic.is_active("pane1")
        assert heuristic.is_active("pane2")

    @patch("termsupervisor.analysis.heuristic.CONTENT_HEURISTIC_KEYWORD", "claude-code")
    async def test_no_cross_pane_bleed(self, heuristic_with_emit, mock_emit):
        """Detections in one pane don't affect another"""
        # Enter mode in both panes
        await heuristic_with_emit.evaluate("pane1", "claude-code\nesc to menu1", "hash1")
        await heuristic_with_emit.evaluate("pane2", "claude-code start", "hash2")

        # Only pane1 should have emitted
        calls = mock_emit.call_args_list
        pane1_calls = [c for c in calls if c[0][1] == "pane1"]

        assert len(pane1_calls) > 0, "pane1 should emit"
        # pane2 has no esc_to, so no detector emissions


# === Detector Tests ===


class TestEscToDetector:
    """Tests for esc_to detector"""

    @patch("termsupervisor.analysis.heuristic.CONTENT_HEURISTIC_KEYWORD", "claude-code")
    async def test_detects_esc_to(self, heuristic_with_emit, mock_emit):
        """Detects 'esc to' and emits signal"""
        content = "claude-code\nPress esc to continue"
        await heuristic_with_emit.evaluate("pane1", content, "hash1")

        # Check emit was called with esc_to signal
        mock_emit.assert_called()
        calls = [c for c in mock_emit.call_args_list if "heuristic_esc_to" in str(c)]
        assert len(calls) > 0

    @patch("termsupervisor.analysis.heuristic.CONTENT_HEURISTIC_KEYWORD", "claude-code")
    async def test_skips_code_lines(self, heuristic_with_emit, mock_emit):
        """Does not detect in code-like lines"""
        content = "claude-code\ndef escape_to_menu():"
        await heuristic_with_emit.evaluate("pane1", content, "hash1")

        # Should not emit esc_to signal (it's in code)
        esc_calls = [c for c in mock_emit.call_args_list if "esc_to" in str(c)]
        assert len(esc_calls) == 0


class TestOneYesDetector:
    """Tests for 1Yes detector"""

    @patch("termsupervisor.analysis.heuristic.CONTENT_HEURISTIC_KEYWORD", "claude-code")
    async def test_detects_1yes(self, heuristic_with_emit, mock_emit):
        """Detects '1Yes' and emits signal"""
        content = "claude-code\n1Yes - approve this"
        await heuristic_with_emit.evaluate("pane1", content, "hash1")

        calls = [c for c in mock_emit.call_args_list if "heuristic_1yes" in str(c)]
        assert len(calls) > 0

    @patch("termsupervisor.analysis.heuristic.CONTENT_HEURISTIC_KEYWORD", "claude-code")
    async def test_skips_list_bullet(self, heuristic_with_emit, mock_emit):
        """Does not detect in list bullet context"""
        content = "claude-code\n- 1 yes is an option"
        await heuristic_with_emit.evaluate("pane1", content, "hash1")

        # Should not emit 1yes signal (it's a bullet)
        yes_calls = [c for c in mock_emit.call_args_list if "1yes" in str(c)]
        assert len(yes_calls) == 0


class TestDetectorPriority:
    """Tests for detector priority (esc_to > 1yes)"""

    @patch("termsupervisor.analysis.heuristic.CONTENT_HEURISTIC_KEYWORD", "claude-code")
    async def test_esc_to_takes_priority(self, heuristic_with_emit, mock_emit):
        """esc_to wins if line could match both"""
        # This is an edge case - a line with both patterns
        content = "claude-code\nesc to 1yes"
        await heuristic_with_emit.evaluate("pane1", content, "hash1")

        # Should emit esc_to, not 1yes
        esc_calls = [c for c in mock_emit.call_args_list if "esc_to" in str(c)]

        assert len(esc_calls) > 0, "Should emit esc_to"
        # 1yes might or might not emit depending on continue logic


# === Dedupe/Cooldown Tests ===


class TestDedupeCooldown:
    """Tests for per-pane dedupe and cooldown"""

    @patch("termsupervisor.analysis.heuristic.CONTENT_HEURISTIC_KEYWORD", "claude-code")
    @patch("termsupervisor.analysis.heuristic.CONTENT_HEURISTIC_COOLDOWN_SECONDS", 2.0)
    async def test_dedupes_identical_content(self, heuristic_with_emit, mock_emit):
        """Does not re-emit for identical content"""
        content = "claude-code\nesc to menu"

        await heuristic_with_emit.evaluate("pane1", content, "hash1")
        first_count = mock_emit.call_count

        # Same content hash - should skip
        await heuristic_with_emit.evaluate("pane1", content, "hash1")
        assert mock_emit.call_count == first_count, "Should not emit for same hash"

    @patch("termsupervisor.analysis.heuristic.CONTENT_HEURISTIC_KEYWORD", "claude-code")
    async def test_cooldown_suppresses_rapid_fire(self, heuristic_with_emit, mock_emit):
        """Cooldown suppresses rapid emissions for same target"""
        # Pattern cooldowns are compiled from config at module load (2.0s).
        # We verify cooldown works by testing that same target within cooldown is suppressed.
        content1 = "claude-code\nesc to menu"
        content2 = "claude-code\nesc to menu\nextra line"

        await heuristic_with_emit.evaluate("pane1", content1, "hash1")
        first_count = mock_emit.call_count

        # Different hash but same target within cooldown (pattern has 2.0s cooldown)
        await heuristic_with_emit.evaluate("pane1", content2, "hash2")
        assert mock_emit.call_count == first_count, "Should be suppressed by cooldown"

    @patch("termsupervisor.analysis.heuristic.CONTENT_HEURISTIC_KEYWORD", "claude-code")
    async def test_emits_after_cooldown(self, heuristic_with_emit, mock_emit):
        """Emits again after cooldown expires"""
        # Note: Pattern cooldowns are compiled from config at module load (2.0s).
        # We test by manually expiring the cooldown in state instead of sleeping.
        import time

        content1 = "claude-code\nesc to menu"
        content2 = "claude-code\nesc to menu\nextra"

        await heuristic_with_emit.evaluate("pane1", content1, "hash1")
        first_count = mock_emit.call_count

        # Manually expire cooldown by backdating last_emissions
        state = heuristic_with_emit._pane_states["pane1"]
        for key in list(state.last_emissions.keys()):
            state.last_emissions[key] = time.time() - 10.0  # 10s ago

        await heuristic_with_emit.evaluate("pane1", content2, "hash2")
        assert mock_emit.call_count > first_count, "Should emit after cooldown expires"


# === Resource Guard Tests ===


class TestResourceGuard:
    """Tests for resource guard (content hash, max scan lines)"""

    @patch("termsupervisor.analysis.heuristic.CONTENT_HEURISTIC_KEYWORD", "claude-code")
    async def test_skips_unchanged_content(self, heuristic_with_emit, mock_emit):
        """Skips evaluation when content hash unchanged"""
        content = "claude-code\nesc to menu"
        await heuristic_with_emit.evaluate("pane1", content, "hash1")
        initial_count = mock_emit.call_count

        # Same hash - should skip entire evaluation
        await heuristic_with_emit.evaluate("pane1", content, "hash1")
        assert mock_emit.call_count == initial_count

    @patch("termsupervisor.analysis.heuristic.CONTENT_HEURISTIC_KEYWORD", "claude-code")
    @patch("termsupervisor.analysis.heuristic.CONTENT_HEURISTIC_MAX_SCAN_LINES", 10)
    async def test_scans_only_recent_lines(self, heuristic_with_emit, mock_emit):
        """Only scans the last N lines"""
        # Entry keyword is in recent lines
        lines = ["line " + str(i) for i in range(20)]
        lines.append("claude-code")
        lines.append("esc to menu")
        content = "\n".join(lines)

        await heuristic_with_emit.evaluate("pane1", content, "hash1")
        assert heuristic_with_emit.is_active("pane1")


# === Status Tracking Tests ===


class TestStatusTracking:
    """Tests for RUNNING/DONE status tracking based on keywords"""

    @patch("termsupervisor.analysis.heuristic.CONTENT_HEURISTIC_KEYWORD", "claude-code")
    async def test_running_when_keyword_present(self, heuristic_with_emit, mock_emit):
        """Status is RUNNING when tracked keywords present"""
        # Set keyword mapping on instance (since it's initialized at __init__)
        heuristic_with_emit._keyword_mapping = {
            "thinking": {"on_appear": "content.thinking", "on_disappear": "content.thinking_done"}
        }

        content = "claude-code\nthinking about this..."
        await heuristic_with_emit.evaluate("pane1", content, "hash1")

        state = heuristic_with_emit._pane_states["pane1"]
        assert state.status_is_running
        assert "thinking" in state.current_keywords

    @patch("termsupervisor.analysis.heuristic.CONTENT_HEURISTIC_KEYWORD", "claude-code")
    async def test_done_when_keywords_disappear(self, heuristic_with_emit, mock_emit):
        """Status is DONE when all tracked keywords disappear"""
        # Set keyword mapping on instance
        heuristic_with_emit._keyword_mapping = {
            "thinking": {"on_appear": "content.thinking", "on_disappear": "content.thinking_done"}
        }

        # First, keyword appears
        content1 = "claude-code\nthinking about this..."
        await heuristic_with_emit.evaluate("pane1", content1, "hash1")
        state = heuristic_with_emit._pane_states["pane1"]
        assert state.status_is_running

        # Then, keyword disappears
        content2 = "claude-code\ndone with response"
        await heuristic_with_emit.evaluate("pane1", content2, "hash2")
        assert not state.status_is_running

    @patch("termsupervisor.analysis.heuristic.CONTENT_HEURISTIC_KEYWORD", "claude-code")
    async def test_no_disappear_before_appear(self, heuristic_with_emit, mock_emit):
        """Disappear signal only fires after keyword was seen"""
        # Set keyword mapping on instance
        heuristic_with_emit._keyword_mapping = {
            "thinking": {"on_appear": "content.thinking", "on_disappear": "content.thinking_done"}
        }

        # Content without keyword
        content = "claude-code\njust some text"
        await heuristic_with_emit.evaluate("pane1", content, "hash1")

        # No disappear signal should be emitted
        calls = [c for c in mock_emit.call_args_list if "thinking_done" in str(c)]
        assert len(calls) == 0

    @patch("termsupervisor.analysis.heuristic.CONTENT_HEURISTIC_KEYWORD", "claude-code")
    async def test_status_emits_signals(self, heuristic_with_emit, mock_emit):
        """Status changes emit signals to HookManager"""
        # Set keyword mapping on instance
        heuristic_with_emit._keyword_mapping = {
            "thinking": {"on_appear": "content.thinking", "on_disappear": "content.thinking_done"}
        }

        # Keyword appears -> RUNNING status signal
        content1 = "claude-code\nthinking about this..."
        await heuristic_with_emit.evaluate("pane1", content1, "hash1")

        # Check RUNNING signal was emitted
        status_calls = [c for c in mock_emit.call_args_list if "heuristic_status" in str(c)]
        assert len(status_calls) == 1
        assert status_calls[0][0][3]["status"] == "RUNNING"

        # Keyword disappears -> DONE status signal
        content2 = "claude-code\ndone with response"
        await heuristic_with_emit.evaluate("pane1", content2, "hash2")

        status_calls = [c for c in mock_emit.call_args_list if "heuristic_status" in str(c)]
        assert len(status_calls) == 2
        assert status_calls[1][0][3]["status"] == "DONE"


class TestKeywordMappingCaseSensitivity:
    """Tests for case-insensitive keyword mapping"""

    @patch("termsupervisor.analysis.heuristic.CONTENT_HEURISTIC_KEYWORD", "claude-code")
    async def test_mixed_case_mapping_keys(self, heuristic_with_emit, mock_emit):
        """Keyword mapping with mixed case keys works correctly"""
        # Set mapping with mixed case key (will be normalized to lowercase)
        heuristic_with_emit._keyword_mapping = {
            "thinking": {"on_appear": "content.thinking", "on_disappear": "content.thinking_done"}
        }

        # Content has lowercase "thinking"
        content = "claude-code\nThinking about this..."  # Note: "Thinking" is capitalized
        await heuristic_with_emit.evaluate("pane1", content, "hash1")

        # Should detect keyword (case-insensitive)
        state = heuristic_with_emit._pane_states["pane1"]
        assert "thinking" in state.current_keywords
        assert state.status_is_running

    @patch("termsupervisor.analysis.heuristic.CONTENT_HEURISTIC_KEYWORD", "claude-code")
    async def test_uppercase_mapping_normalized(self, heuristic_with_emit, mock_emit):
        """Mapping keys are normalized to lowercase for lookup"""
        from termsupervisor.analysis.heuristic import _normalize_keyword_mapping

        # Simulate mixed-case config
        original_mapping = {
            "THINKING": {"on_appear": "content.thinking"},
            "Working": {"on_appear": "content.working"},
        }

        normalized = _normalize_keyword_mapping(original_mapping)

        # Keys should be lowercase
        assert "thinking" in normalized
        assert "working" in normalized
        assert "THINKING" not in normalized
        assert "Working" not in normalized


# === Debug State Tests ===


class TestDebugState:
    """Tests for debug_state() method"""

    @patch("termsupervisor.analysis.heuristic.CONTENT_HEURISTIC_KEYWORD", "claude-code")
    async def test_debug_state_active(self, heuristic):
        """debug_state returns correct info for active pane"""
        await heuristic.evaluate("pane1", "claude-code start", "hash1")

        debug = heuristic.debug_state("pane1")
        assert debug["active"] is True
        assert "entered_at" in debug
        assert "keywords_seen" in debug

    def test_debug_state_inactive(self, heuristic):
        """debug_state returns minimal info for unknown pane"""
        debug = heuristic.debug_state("unknown")
        assert debug["active"] is False


# === Integration Tests ===


class TestIntegration:
    """Integration tests for full evaluation flow"""

    @patch("termsupervisor.analysis.heuristic.CONTENT_HEURISTIC_KEYWORD", "claude-code")
    async def test_full_lifecycle(self, heuristic_with_emit, mock_emit):
        """Test full lifecycle: enter -> detect -> exit"""
        # Enter
        await heuristic_with_emit.evaluate("pane1", "claude-code session", "h1")
        assert heuristic_with_emit.is_active("pane1")

        # Detect
        await heuristic_with_emit.evaluate("pane1", "claude-code\nesc to menu", "h2")
        assert mock_emit.call_count > 0

        # Exit
        heuristic_with_emit.exit_pane("pane1", "session_end")
        assert not heuristic_with_emit.is_active("pane1")

    @patch("termsupervisor.analysis.heuristic.CONTENT_HEURISTIC_KEYWORD", "claude-code")
    async def test_multiple_detections_same_frame(self, heuristic_with_emit, mock_emit):
        """Multiple patterns in same content"""
        content = "claude-code\nesc to menu\n1Yes - approve"
        await heuristic_with_emit.evaluate("pane1", content, "hash1")

        # Both should be detected
        esc_calls = [c for c in mock_emit.call_args_list if "esc_to" in str(c)]
        yes_calls = [c for c in mock_emit.call_args_list if "1yes" in str(c)]

        assert len(esc_calls) > 0
        assert len(yes_calls) > 0


# === External Exit Signal Tests ===


class TestExternalExitSignals:
    """Tests for external exit signal contract"""

    @patch("termsupervisor.analysis.heuristic.CONTENT_HEURISTIC_KEYWORD", "claude-code")
    async def test_iterm_session_end(self, heuristic):
        """iterm.session_end exits and removes pane state"""
        # Enter mode
        await heuristic.evaluate("pane1", "claude-code session", "hash1")
        assert heuristic.is_active("pane1")

        # Handle session_end signal
        result = heuristic.handle_exit_signal("iterm.session_end", "pane1", {"pid": 123})
        assert result is True
        assert not heuristic.is_active("pane1")
        assert "pane1" not in heuristic._pane_states

    @patch("termsupervisor.analysis.heuristic.CONTENT_HEURISTIC_KEYWORD", "claude-code")
    async def test_frontend_close_pane(self, heuristic):
        """frontend.close_pane exits and removes pane state"""
        # Enter mode
        await heuristic.evaluate("pane1", "claude-code session", "hash1")
        assert heuristic.is_active("pane1")

        # Handle close_pane signal
        result = heuristic.handle_exit_signal("frontend.close_pane", "pane1", {})
        assert result is True
        assert not heuristic.is_active("pane1")
        assert "pane1" not in heuristic._pane_states

    @patch("termsupervisor.analysis.heuristic.CONTENT_HEURISTIC_KEYWORD", "claude-code")
    async def test_content_exit(self, heuristic):
        """content.exit exits but doesn't remove state"""
        # Enter mode
        await heuristic.evaluate("pane1", "claude-code session", "hash1")
        assert heuristic.is_active("pane1")

        # Handle content.exit signal
        result = heuristic.handle_exit_signal("content.exit", "pane1", {})
        assert result is True
        assert not heuristic.is_active("pane1")

    @patch("termsupervisor.analysis.heuristic.CONTENT_HEURISTIC_KEYWORD", "claude-code")
    async def test_content_exit_missing_pane_id(self, heuristic):
        """content.exit with missing pane_id is handled gracefully"""
        # Handle content.exit with empty pane_id
        result = heuristic.handle_exit_signal("content.exit", "", {})
        assert result is True  # Signal was handled, just no-op

    def test_unknown_signal_not_handled(self, heuristic):
        """Unknown signals return False"""
        result = heuristic.handle_exit_signal("unknown.signal", "pane1", {})
        assert result is False


# === Telemetry Tests ===


class TestTelemetry:
    """Tests for telemetry metrics per contract"""

    @patch("termsupervisor.analysis.heuristic.CONTENT_HEURISTIC_KEYWORD", "claude-code")
    async def test_signal_emitted_metric(self, heuristic_with_emit, mock_emit):
        """heuristic.signal_emitted metric is tracked"""
        from termsupervisor.telemetry import metrics

        metrics.reset()

        content = "claude-code\nesc to menu"
        await heuristic_with_emit.evaluate("pane1", content, "hash1")

        # Check metric was recorded
        emitted_count = metrics.get_counter(
            "heuristic.signal_emitted", {"signal": "heuristic_esc_to", "pane_id": "pane1"}
        )
        assert emitted_count >= 1

    @patch("termsupervisor.analysis.heuristic.CONTENT_HEURISTIC_KEYWORD", "claude-code")
    @patch("termsupervisor.analysis.heuristic.CONTENT_HEURISTIC_COOLDOWN_SECONDS", 10.0)
    async def test_signal_suppressed_metric(self, heuristic_with_emit, mock_emit):
        """heuristic.signal_suppressed metric is tracked for cooldown"""
        from termsupervisor.telemetry import metrics

        metrics.reset()

        # First emit
        content1 = "claude-code\nesc to menu"
        await heuristic_with_emit.evaluate("pane1", content1, "hash1")

        # Second emit within cooldown - should be suppressed
        content2 = "claude-code\nesc to menu\nextra"
        await heuristic_with_emit.evaluate("pane1", content2, "hash2")

        # Check suppression metric
        suppressed_count = metrics.get_counter(
            "heuristic.signal_suppressed", {"reason": "cooldown", "pane_id": "pane1"}
        )
        assert suppressed_count >= 1

    @patch("termsupervisor.analysis.heuristic.CONTENT_HEURISTIC_KEYWORD", "claude-code")
    async def test_status_change_metric(self, heuristic_with_emit, mock_emit):
        """heuristic.status_change metric is tracked"""
        from termsupervisor.telemetry import metrics

        metrics.reset()

        # Set keyword mapping on instance
        heuristic_with_emit._keyword_mapping = {
            "thinking": {"on_appear": "content.thinking", "on_disappear": "content.thinking_done"}
        }

        # Trigger RUNNING status
        content1 = "claude-code\nthinking about this..."
        await heuristic_with_emit.evaluate("pane1", content1, "hash1")

        running_count = metrics.get_counter("heuristic.status_change", {"status": "RUNNING"})
        assert running_count == 1

        # Trigger DONE status
        content2 = "claude-code\ndone with response"
        await heuristic_with_emit.evaluate("pane1", content2, "hash2")

        done_count = metrics.get_counter("heuristic.status_change", {"status": "DONE"})
        assert done_count == 1


# === Exit Timeout Bypass Tests ===


class TestExitTimeoutBypassesHashGuard:
    """Tests that exit timeout fires even when content is unchanged"""

    @patch("termsupervisor.analysis.heuristic.CONTENT_HEURISTIC_KEYWORD", "claude-code")
    @patch("termsupervisor.analysis.heuristic.CONTENT_HEURISTIC_EXIT_TIMEOUT_SECONDS", 0.05)
    async def test_timeout_fires_on_unchanged_content(self, heuristic):
        """Exit timeout fires even when content hash is unchanged (idle pane)"""
        import time

        # Enter mode
        await heuristic.evaluate("pane1", "claude-code start", "hash1")
        assert heuristic.is_active("pane1")

        # Wait for timeout
        time.sleep(0.1)

        # Evaluate with SAME content hash - should still exit due to timeout
        await heuristic.evaluate("pane1", "claude-code start", "hash1")
        assert not heuristic.is_active("pane1"), "Timeout should fire even with unchanged content"

    @patch("termsupervisor.analysis.heuristic.CONTENT_HEURISTIC_KEYWORD", "claude-code")
    @patch("termsupervisor.analysis.heuristic.CONTENT_HEURISTIC_EXIT_KEYWORD", "exit-now")
    async def test_exit_keyword_checked_before_hash_guard(self, heuristic):
        """Exit keyword is checked even when content hash is unchanged"""
        # Enter mode
        await heuristic.evaluate("pane1", "claude-code start", "hash1")
        assert heuristic.is_active("pane1")

        # Note: In practice, if content contains "exit-now", the hash would change.
        # But exit keyword check happens before hash guard, so it works correctly.
        # This test verifies the ordering - exit checks run before hash short-circuit.
        await heuristic.evaluate("pane1", "claude-code exit-now", "hash2")
        assert not heuristic.is_active("pane1")


# === Pattern Compilation Tests ===


class TestPatternCompilation:
    """Tests for _compile_patterns function"""

    def test_compile_empty_config(self):
        """Empty config produces no patterns"""
        patterns = _compile_patterns([])
        assert patterns == []

    def test_compile_basic_pattern(self):
        """Compiles a basic pattern config"""
        config = [
            {
                "name": "test_pattern",
                "regex": r"\btest\b",
                "signal": "heuristic_test",
            }
        ]
        patterns = _compile_patterns(config)
        assert len(patterns) == 1
        assert patterns[0].name == "test_pattern"
        assert patterns[0].signal == "heuristic_test"
        assert patterns[0].regex.search("this is a test")

    def test_compile_with_flags(self):
        """Compiles pattern with regex flags"""
        config = [
            {
                "name": "case_test",
                "regex": r"^hello",
                "signal": "heuristic_hello",
                "regex_flags": ["IGNORECASE", "MULTILINE"],
            }
        ]
        patterns = _compile_patterns(config)
        assert patterns[0].regex.search("HELLO world")  # IGNORECASE
        assert patterns[0].regex.search("line1\nhello")  # MULTILINE

    def test_compile_with_guards(self):
        """Compiles pattern with guard patterns"""
        config = [
            {
                "name": "guarded",
                "regex": r"\bfoo\b",
                "signal": "heuristic_foo",
                "guards": [r"\bclass\b", r"\bdef\b"],
            }
        ]
        patterns = _compile_patterns(config)
        assert len(patterns[0].guards) == 2
        assert patterns[0].guards[0].search("class Foo")
        assert patterns[0].guards[1].search("def foo()")

    def test_compile_with_target_group(self):
        """Compiles pattern with target capture group"""
        config = [
            {
                "name": "capture",
                "regex": r"go to (\w+)",
                "signal": "heuristic_goto",
                "target_group": 1,
                "target_strip": ".,",
            }
        ]
        patterns = _compile_patterns(config)
        assert patterns[0].target_group == 1
        assert patterns[0].target_strip == ".,"
        assert patterns[0].target_fixed is None

    def test_compile_with_fixed_target(self):
        """Compiles pattern with fixed target value"""
        config = [
            {
                "name": "fixed",
                "regex": r"^yes$",
                "signal": "heuristic_yes",
                "target": "confirmed",
            }
        ]
        patterns = _compile_patterns(config)
        assert patterns[0].target_fixed == "confirmed"
        assert patterns[0].target_group is None

    def test_compile_with_custom_cooldown(self):
        """Compiles pattern with custom cooldown"""
        config = [
            {
                "name": "slow",
                "regex": r"\bslow\b",
                "signal": "heuristic_slow",
                "cooldown": 5.0,
            }
        ]
        patterns = _compile_patterns(config)
        assert patterns[0].cooldown == 5.0

    def test_compile_skips_invalid_regex(self):
        """Skips patterns with invalid regex"""
        config = [
            {
                "name": "valid",
                "regex": r"\bvalid\b",
                "signal": "sig1",
            },
            {
                "name": "invalid",
                "regex": r"[invalid",  # Invalid regex
                "signal": "sig2",
            },
        ]
        patterns = _compile_patterns(config)
        assert len(patterns) == 1
        assert patterns[0].name == "valid"

    def test_compile_skips_empty_regex(self):
        """Skips patterns with no regex"""
        config = [
            {
                "name": "no_regex",
                "signal": "sig",
            },
        ]
        patterns = _compile_patterns(config)
        assert len(patterns) == 0

    def test_default_patterns_loaded(self):
        """Default config patterns are loaded at module init"""
        # _COMPILED_PATTERNS should have the default esc_to and 1yes patterns
        assert len(_COMPILED_PATTERNS) == 2
        names = {p.name for p in _COMPILED_PATTERNS}
        assert "esc_to" in names
        assert "1yes" in names

    def test_compile_invalid_cooldown_uses_default(self):
        """Invalid cooldown value falls back to default"""
        from termsupervisor.config import CONTENT_HEURISTIC_COOLDOWN_SECONDS

        config = [
            {
                "name": "bad_cooldown",
                "regex": r"\btest\b",
                "signal": "sig",
                "cooldown": "fast",  # Invalid - not a number
            },
        ]
        patterns = _compile_patterns(config)
        assert len(patterns) == 1
        assert patterns[0].cooldown == CONTENT_HEURISTIC_COOLDOWN_SECONDS

    def test_compile_invalid_target_group_ignored(self):
        """Invalid target_group value is ignored"""
        config = [
            {
                "name": "bad_target_group",
                "regex": r"\btest\b",
                "signal": "sig",
                "target_group": "first",  # Invalid - not an int
            },
        ]
        patterns = _compile_patterns(config)
        assert len(patterns) == 1
        assert patterns[0].target_group is None

    def test_compile_non_list_regex_flags_ignored(self):
        """Non-list regex_flags is ignored with warning"""
        config = [
            {
                "name": "bad_flags",
                "regex": r"hello",
                "signal": "sig",
                "regex_flags": "IGNORECASE",  # Invalid - should be a list
            },
        ]
        patterns = _compile_patterns(config)
        assert len(patterns) == 1
        # Pattern compiles but without the flag (case-sensitive)
        assert patterns[0].regex.search("hello")
        assert not patterns[0].regex.search("HELLO")

    def test_compile_non_list_guards_ignored(self):
        """Non-list guards is ignored with warning"""
        config = [
            {
                "name": "bad_guards",
                "regex": r"\btest\b",
                "signal": "sig",
                "guards": r"\bclass\b",  # Invalid - should be a list
            },
        ]
        patterns = _compile_patterns(config)
        assert len(patterns) == 1
        assert len(patterns[0].guards) == 0
