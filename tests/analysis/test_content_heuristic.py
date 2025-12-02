"""Tests for ContentHeuristicAnalyzer

Covers:
- REPL prompts (>>>, In [1]:, Pdb, Gemini>)
- Press-enter/menu prompts
- Spinners
- Markdown-question flicker
- Newline/burst gating
- Prompt silence gate
- Debounce
- Idle re-emit
"""

import pytest
from datetime import datetime
from unittest.mock import MagicMock, AsyncMock

from termsupervisor.analysis.content_heuristic import (
    ContentHeuristicAnalyzer,
    HeuristicResult,
    HeuristicPaneState,
)
from termsupervisor.analysis.change_queue import PaneChangeQueue, ChangeRecord
from termsupervisor.hooks.prompt_monitor import PromptMonitorStatus
from termsupervisor.pane.types import TaskStatus
from termsupervisor import config


@pytest.fixture
def analyzer():
    """Create a fresh analyzer instance"""
    return ContentHeuristicAnalyzer()


@pytest.fixture
def prompt_status_inactive():
    """PromptMonitor status: integration not active"""
    return PromptMonitorStatus(integration_active=False, last_prompt_event_at=None)


@pytest.fixture
def prompt_status_silent():
    """PromptMonitor status: active but silent > T_prompt_silence"""
    old_time = datetime.now().timestamp() - config.CONTENT_T_PROMPT_SILENCE - 10
    return PromptMonitorStatus(integration_active=True, last_prompt_event_at=old_time)


@pytest.fixture
def prompt_status_recent():
    """PromptMonitor status: active with recent event (blocks heuristics)"""
    recent_time = datetime.now().timestamp() - 1.0  # 1 second ago
    return PromptMonitorStatus(integration_active=True, last_prompt_event_at=recent_time)


def make_queue_with_content(content: str, session_id: str = "test-session") -> PaneChangeQueue:
    """Create a PaneChangeQueue with specific content"""
    queue = PaneChangeQueue(session_id)
    # Initialize queue with content
    queue.check_and_record(content)
    return queue


def make_queue_with_quiet(
    content: str,
    quiet_seconds: float,
    session_id: str = "test-session"
) -> PaneChangeQueue:
    """Create a queue with content that has been stable for quiet_seconds

    Simulates a scenario where content hasn't changed for quiet_seconds.
    Both records have the same hash, and timestamps are set to the past.
    """
    queue = PaneChangeQueue(session_id)
    queue.check_and_record(content)
    # Manually adjust timestamps to simulate quiet period
    now = datetime.now()
    old_time = datetime.fromtimestamp(now.timestamp() - quiet_seconds - 1)
    if queue._records:
        for record in queue._records:
            record.timestamp = old_time
            record.updated_at = old_time
            # Ensure raw_tail is set for pattern matching
            if not record.raw_tail:
                record.raw_tail = content
    # Set the dedicated quiet tracking timestamp
    queue._last_change_at = old_time
    return queue


class TestActivationGate:
    """Test tiered activation gate (whitelist + prompt silence)"""

    def test_whitelist_passes_gemini_job(self, analyzer, prompt_status_inactive):
        """job_name 'gemini' should pass whitelist"""
        assert analyzer._passes_whitelist("gemini", "zsh")
        assert analyzer._passes_whitelist("Gemini", "-zsh")

    def test_whitelist_passes_codex_job(self, analyzer, prompt_status_inactive):
        """job_name 'codex' should pass whitelist"""
        assert analyzer._passes_whitelist("codex", "bash")

    def test_whitelist_passes_title_fallback(self, analyzer, prompt_status_inactive):
        """Title should work as fallback when job_name is empty"""
        assert analyzer._passes_whitelist("", "gemini-session")
        assert analyzer._passes_whitelist("", "Codex CLI")

    def test_whitelist_rejects_shell_job(self, analyzer, prompt_status_inactive):
        """Shell process with generic title should not pass"""
        assert not analyzer._passes_whitelist("zsh", "-zsh")
        assert not analyzer._passes_whitelist("bash", "bash")

    def test_whitelist_python_in_job_whitelist(self, analyzer, prompt_status_inactive):
        """Python in job whitelist should pass when job_name matches"""
        # python is in JOB_WHITELIST but not PANE_WHITELIST
        assert analyzer._passes_whitelist("python", "zsh")

    def test_whitelist_node_in_job_whitelist(self, analyzer, prompt_status_inactive):
        """Node in job whitelist should pass"""
        assert analyzer._passes_whitelist("node", "bash")

    def test_prompt_silence_inactive(self, analyzer, prompt_status_inactive):
        """Inactive PromptMonitor should pass silence check"""
        now = datetime.now().timestamp()
        assert analyzer._passes_prompt_silence(prompt_status_inactive, now)

    def test_prompt_silence_old_event(self, analyzer, prompt_status_silent):
        """Old prompt event should pass silence check"""
        now = datetime.now().timestamp()
        assert analyzer._passes_prompt_silence(prompt_status_silent, now)

    def test_prompt_silence_recent_event(self, analyzer, prompt_status_recent):
        """Recent prompt event should block (tier 1 authority)"""
        now = datetime.now().timestamp()
        assert not analyzer._passes_prompt_silence(prompt_status_recent, now)

    def test_full_gate_passes_job(self, analyzer, prompt_status_silent):
        """Full gate should pass with whitelisted job_name"""
        now = datetime.now().timestamp()
        assert analyzer._passes_activation_gate("gemini", "zsh", prompt_status_silent, now)

    def test_full_gate_passes_title_fallback(self, analyzer, prompt_status_silent):
        """Full gate should pass with whitelisted title when job_name empty"""
        now = datetime.now().timestamp()
        assert analyzer._passes_activation_gate("", "gemini-cli", prompt_status_silent, now)

    def test_full_gate_blocks_non_whitelist(self, analyzer, prompt_status_silent):
        """Full gate should block non-whitelisted job+title"""
        now = datetime.now().timestamp()
        assert not analyzer._passes_activation_gate("zsh", "-zsh", prompt_status_silent, now)

    def test_full_gate_blocks_recent_prompt(self, analyzer, prompt_status_recent):
        """Full gate should block when PromptMonitor has recent events"""
        now = datetime.now().timestamp()
        assert not analyzer._passes_activation_gate("gemini", "gemini", prompt_status_recent, now)


class TestPromptAnchors:
    """Test detection of REPL and shell prompts"""

    def test_python_repl_prompt(self, analyzer):
        """>>> should be detected as prompt anchor"""
        assert analyzer._matches_prompt_anchor(">>> ")
        assert analyzer._matches_prompt_anchor("result\n>>> ")

    def test_python_continuation(self, analyzer):
        """... should be detected as multi-line prompt"""
        assert analyzer._matches_prompt_anchor("... ")

    def test_ipython_prompt(self, analyzer):
        """In [n]: should be detected"""
        assert analyzer._matches_prompt_anchor("In [1]: ")
        assert analyzer._matches_prompt_anchor("In [42]: ")

    def test_pdb_prompt(self, analyzer):
        """(Pdb) should be detected"""
        assert analyzer._matches_prompt_anchor("(Pdb) ")

    def test_gemini_prompt(self, analyzer):
        """Gemini> should be detected"""
        assert analyzer._matches_prompt_anchor("Gemini> ")

    def test_shell_prompts(self, analyzer):
        """Standard shell prompts should be detected"""
        assert analyzer._matches_prompt_anchor("$ ")
        assert analyzer._matches_prompt_anchor("# ")
        assert analyzer._matches_prompt_anchor("% ")
        assert analyzer._matches_prompt_anchor("> ")

    def test_modern_shell_glyphs(self, analyzer):
        """Modern shell glyphs should be detected"""
        assert analyzer._matches_prompt_anchor("❯")
        assert analyzer._matches_prompt_anchor("➜")

    def test_non_prompt_not_detected(self, analyzer):
        """Regular text should not match prompt anchors"""
        assert not analyzer._matches_prompt_anchor("Hello world")
        # Note: "Processing..." matches ... pattern for Python continuation
        # This is expected behavior - ... at end is a valid Python prompt


class TestInteractivity:
    """Test detection of interactive prompts"""

    def test_yn_parentheses(self, analyzer):
        """(y/n) prompts should be detected"""
        assert analyzer._matches_interactivity("Continue? (y/n)")
        assert analyzer._matches_interactivity("Proceed? (Y/N)")

    def test_yn_brackets(self, analyzer):
        """[y/n] prompts should be detected"""
        assert analyzer._matches_interactivity("Overwrite? [y/n]")
        assert analyzer._matches_interactivity("Delete? [Y/N]")

    def test_question_mark(self, analyzer):
        """Lines ending with ? should be detected"""
        assert analyzer._matches_interactivity("Are you sure?")
        assert analyzer._matches_interactivity("What would you like to do? ")

    def test_press_enter(self, analyzer):
        """Press Enter prompts should be detected"""
        assert analyzer._matches_interactivity("Press Enter to continue")
        assert analyzer._matches_interactivity("Press Enter to continue.")
        assert analyzer._matches_interactivity("Press any key to continue...")

    def test_select_menu(self, analyzer):
        """Select menu prompts should be detected"""
        assert analyzer._matches_interactivity("Select an option:")
        assert analyzer._matches_interactivity("Select your choice: ")

    def test_colon_ending(self, analyzer):
        """Lines ending with : should be detected"""
        assert analyzer._matches_interactivity("Enter your name:")
        assert analyzer._matches_interactivity("Password: ")


class TestSpinners:
    """Test detection of spinner/progress patterns"""

    def test_trailing_ellipsis(self, analyzer):
        """Trailing ... should be detected as spinner"""
        assert analyzer._matches_spinner("Loading...")
        assert analyzer._matches_spinner("Processing....")

    def test_percentage(self, analyzer):
        """Percentage indicators should be detected"""
        assert analyzer._matches_spinner("50%")
        assert analyzer._matches_spinner("Downloading: 75%")

    def test_eta(self, analyzer):
        """ETA indicators should be detected"""
        assert analyzer._matches_spinner("ETA: 2m 30s")
        assert analyzer._matches_spinner("Time remaining: ETA 5:00")

    def test_transfer_rate(self, analyzer):
        """Transfer rate indicators should be detected"""
        assert analyzer._matches_spinner("1.5 MB/s")
        assert analyzer._matches_spinner("500 KB/s")

    def test_braille_spinner(self, analyzer):
        """Braille spinner characters should be detected"""
        assert analyzer._matches_spinner("Loading ⠋")
        assert analyzer._matches_spinner("⠙ Processing")


class TestCompletionTokens:
    """Test detection of completion tokens"""

    def test_done(self, analyzer):
        """'done' should be detected"""
        assert analyzer._matches_completion_token("done")
        assert analyzer._matches_completion_token("Done!")
        assert analyzer._matches_completion_token("Task done.")

    def test_finished(self, analyzer):
        """'finished' should be detected"""
        assert analyzer._matches_completion_token("finished")
        assert analyzer._matches_completion_token("Build finished successfully")

    def test_success(self, analyzer):
        """'success' should be detected"""
        assert analyzer._matches_completion_token("success")
        assert analyzer._matches_completion_token("SUCCESS")

    def test_complete(self, analyzer):
        """'complete/completed' should be detected"""
        assert analyzer._matches_completion_token("complete")
        assert analyzer._matches_completion_token("completed")
        assert analyzer._matches_completion_token("Installation completed")

    def test_exit_code_0(self, analyzer):
        """'exit code 0' should be detected"""
        assert analyzer._matches_completion_token("exit code 0")
        assert analyzer._matches_completion_token("Process exited with exit code 0")


class TestHeuristicRun:
    """Test heuristic_run signal (IDLE → RUNNING)"""

    def test_run_with_newlines(self, analyzer, prompt_status_silent):
        """Should emit heuristic_run when newlines detected"""
        queue = make_queue_with_content("line1")
        # Add more content to create newline delta
        queue.check_and_record("line1\nline2\nline3")

        result = analyzer.analyze(
            pane_id="test",
            pane_title="-zsh",
            current_status=TaskStatus.IDLE,
            current_source="shell",
            prompt_status=prompt_status_silent,
            queue=queue,
            job_name="gemini",
        )

        assert result.signal == "heuristic_run"

    def test_run_blocked_without_newlines(self, analyzer, prompt_status_silent):
        """Should not emit heuristic_run without newline delta"""
        queue = make_queue_with_content("same content")

        result = analyzer.analyze(
            pane_id="test",
            pane_title="-zsh",
            current_status=TaskStatus.IDLE,
            current_source="shell",
            prompt_status=prompt_status_silent,
            queue=queue,
            job_name="gemini",
        )

        assert result.signal is None
        assert "newline_gate" in result.reason


class TestHeuristicDone:
    """Test heuristic_done signal (RUNNING → DONE)"""

    def test_done_with_prompt_anchor(self, analyzer, prompt_status_silent):
        """Should emit heuristic_done when prompt anchor detected after quiet"""
        queue = make_queue_with_quiet("output\n>>> ", quiet_seconds=3.0)

        # Verify queue is set up correctly for quiet detection
        assert queue.get_quiet_duration() >= 3.0

        result = analyzer.analyze(
            pane_id="test",
            pane_title="-zsh",
            job_name="gemini",
            current_status=TaskStatus.RUNNING,
            current_source="content",
            prompt_status=prompt_status_silent,
            queue=queue,
        )

        assert result.signal == "heuristic_done", f"Expected heuristic_done, got {result}"

    def test_done_with_completion_token(self, analyzer, prompt_status_silent):
        """Should emit heuristic_done when completion token detected after quiet"""
        queue = make_queue_with_quiet("Task completed successfully", quiet_seconds=3.0)

        result = analyzer.analyze(
            pane_id="test",
            pane_title="-zsh",
            job_name="gemini",
            current_status=TaskStatus.RUNNING,
            current_source="content",
            prompt_status=prompt_status_silent,
            queue=queue,
        )

        assert result.signal == "heuristic_done", f"Expected heuristic_done, got {result}"


class TestHeuristicWait:
    """Test heuristic_wait signal (RUNNING → WAITING_APPROVAL)"""

    def test_wait_with_spinner(self, analyzer, prompt_status_silent):
        """Should emit heuristic_wait when spinner detected after brief quiet"""
        # Use a spinner pattern that doesn't conflict with prompt anchors
        queue = make_queue_with_quiet("Downloading 50%", quiet_seconds=2.0)

        result = analyzer.analyze(
            pane_id="test",
            pane_title="-zsh",
            job_name="gemini",
            current_status=TaskStatus.RUNNING,
            current_source="content",
            prompt_status=prompt_status_silent,
            queue=queue,
        )

        assert result.signal == "heuristic_wait", f"Expected heuristic_wait, got {result}"

    def test_wait_with_braille_spinner(self, analyzer, prompt_status_silent):
        """Should emit heuristic_wait when braille spinner detected"""
        queue = make_queue_with_quiet("Processing ⠋", quiet_seconds=2.0)

        result = analyzer.analyze(
            pane_id="test",
            pane_title="-zsh",
            job_name="gemini",
            current_status=TaskStatus.RUNNING,
            current_source="content",
            prompt_status=prompt_status_silent,
            queue=queue,
        )

        assert result.signal == "heuristic_wait", f"Expected heuristic_wait, got {result}"

    def test_wait_with_interactivity(self, analyzer, prompt_status_silent):
        """Should emit heuristic_wait when interactivity prompt detected"""
        queue = make_queue_with_quiet("Continue? (y/n)", quiet_seconds=2.0)

        result = analyzer.analyze(
            pane_id="test",
            pane_title="-zsh",
            job_name="gemini",
            current_status=TaskStatus.RUNNING,
            current_source="content",
            prompt_status=prompt_status_silent,
            queue=queue,
        )

        assert result.signal == "heuristic_wait", f"Expected heuristic_wait, got {result}"


class TestHeuristicIdle:
    """Test heuristic_idle signal (RUNNING → IDLE)"""

    def test_idle_after_extended_quiet(self, analyzer, prompt_status_silent):
        """Should emit heuristic_idle after extended quiet with stable hash"""
        queue = make_queue_with_quiet("some static output", quiet_seconds=10.0)

        result = analyzer.analyze(
            pane_id="test",
            pane_title="-zsh",
            job_name="gemini",
            current_status=TaskStatus.RUNNING,
            current_source="content",
            prompt_status=prompt_status_silent,
            queue=queue,
        )

        assert result.signal == "heuristic_idle"


def make_queue_with_newlines(
    initial_content: str,
    new_content: str,
    session_id: str = "test-session"
) -> PaneChangeQueue:
    """Create a queue with newline delta between base and tail"""
    queue = PaneChangeQueue(session_id)
    queue.check_and_record(initial_content)
    # Add second record with different content
    queue.check_and_record(new_content)
    return queue


class TestDebounce:
    """Test signal debouncing"""

    def test_debounce_blocks_rapid_signals(self, analyzer, prompt_status_silent):
        """Same signal within debounce window should be blocked"""
        # Create queue with newline delta to pass the gate
        queue = make_queue_with_newlines("line1", "line1\nline2\nline3")

        # First call should succeed
        result1 = analyzer.analyze(
            pane_id="test",
            pane_title="-zsh",
            job_name="gemini",
            current_status=TaskStatus.IDLE,
            current_source="shell",
            prompt_status=prompt_status_silent,
            queue=queue,
        )
        assert result1.signal == "heuristic_run", f"Expected heuristic_run, got {result1}"

        # Immediate second call should be debounced
        result2 = analyzer.analyze(
            pane_id="test",
            pane_title="-zsh",
            job_name="gemini",
            current_status=TaskStatus.IDLE,
            current_source="shell",
            prompt_status=prompt_status_silent,
            queue=queue,
        )
        assert result2.signal is None
        assert "debounce" in result2.reason


class TestSuppression:
    """Test suppression after DONE/FAILED

    Suppression only affects completion signals (done/wait/idle) when in RUNNING.
    heuristic_run from IDLE is NEVER suppressed - it's the reactivation signal.
    """

    def test_suppressed_completion_in_running(self, analyzer, prompt_status_silent):
        """Completion signals should be suppressed after resolution"""
        queue = make_queue_with_quiet(">>> ", quiet_seconds=3.0)

        # Emit heuristic_done (sets suppression)
        result1 = analyzer.analyze(
            pane_id="test",
            pane_title="-zsh",
            job_name="gemini",
            current_status=TaskStatus.RUNNING,
            current_source="content",
            prompt_status=prompt_status_silent,
            queue=queue,
        )
        assert result1.signal == "heuristic_done"

        # Clear debounce to allow another signal
        state = analyzer._get_pane_state("test")
        state.last_signal_at = 0.0

        # Still in RUNNING (transition not yet applied), try again
        # Should be suppressed because we already emitted done
        result2 = analyzer.analyze(
            pane_id="test",
            pane_title="-zsh",
            job_name="gemini",
            current_status=TaskStatus.RUNNING,
            current_source="content",
            prompt_status=prompt_status_silent,
            queue=queue,
        )
        assert result2.signal is None
        assert "suppressed" in result2.reason

    def test_run_not_suppressed_from_idle(self, analyzer, prompt_status_silent):
        """heuristic_run should NOT be suppressed - it's the reactivation signal"""
        queue = make_queue_with_quiet(">>> ", quiet_seconds=3.0)

        # Emit heuristic_done (sets suppression)
        result1 = analyzer.analyze(
            pane_id="test",
            pane_title="-zsh",
            job_name="gemini",
            current_status=TaskStatus.RUNNING,
            current_source="content",
            prompt_status=prompt_status_silent,
            queue=queue,
        )
        assert result1.signal == "heuristic_done"

        # Now in IDLE state with suppression active
        state = analyzer._get_pane_state("test")
        assert state.suppressed_until_reactivation is True
        state.last_signal_at = 0.0  # Clear debounce

        # Create queue with newlines to trigger heuristic_run
        queue2 = make_queue_with_newlines("line1", "line1\nline2\nline3")

        # heuristic_run from IDLE should NOT be suppressed
        result2 = analyzer.analyze(
            pane_id="test",
            pane_title="-zsh",
            job_name="gemini",
            current_status=TaskStatus.IDLE,  # Now idle
            current_source="content",
            prompt_status=prompt_status_silent,
            queue=queue2,
        )
        assert result2.signal == "heuristic_run", f"Expected heuristic_run, got {result2}"

        # Verify suppression is cleared after heuristic_run
        assert state.suppressed_until_reactivation is False, "Suppression should be cleared"

    def test_completion_signals_work_after_reactivation(self, analyzer, prompt_status_silent):
        """After heuristic_run, completion signals should work again"""
        # Setup: emit done to set suppression
        queue = make_queue_with_quiet(">>> ", quiet_seconds=3.0)
        result1 = analyzer.analyze(
            pane_id="test",
            pane_title="-zsh",
            job_name="gemini",
            current_status=TaskStatus.RUNNING,
            current_source="content",
            prompt_status=prompt_status_silent,
            queue=queue,
        )
        assert result1.signal == "heuristic_done"

        state = analyzer._get_pane_state("test")
        state.last_signal_at = 0.0  # Clear debounce

        # Reactivation: emit heuristic_run from IDLE
        queue2 = make_queue_with_newlines("line1", "line1\nline2\nline3")
        result2 = analyzer.analyze(
            pane_id="test",
            pane_title="-zsh",
            job_name="gemini",
            current_status=TaskStatus.IDLE,
            current_source="content",
            prompt_status=prompt_status_silent,
            queue=queue2,
        )
        assert result2.signal == "heuristic_run"

        state.last_signal_at = 0.0  # Clear debounce

        # Now in RUNNING again, completion signals should work
        queue3 = make_queue_with_quiet(">>> ", quiet_seconds=3.0)
        result3 = analyzer.analyze(
            pane_id="test",
            pane_title="-zsh",
            job_name="gemini",
            current_status=TaskStatus.RUNNING,
            current_source="content",
            prompt_status=prompt_status_silent,
            queue=queue3,
        )
        assert result3.signal == "heuristic_done", f"Expected heuristic_done after reactivation, got {result3}"


class TestGateBlocking:
    """Test that gate properly blocks heuristics"""

    def test_blocked_by_recent_prompt(self, analyzer, prompt_status_recent):
        """Recent PromptMonitor event should block all heuristics"""
        queue = make_queue_with_content("line1\nline2\nline3")

        result = analyzer.analyze(
            pane_id="test",
            pane_title="-zsh",
            job_name="gemini",
            current_status=TaskStatus.IDLE,
            current_source="shell",
            prompt_status=prompt_status_recent,
            queue=queue,
        )

        assert result.signal is None
        assert "gate_failed" in result.reason

    def test_blocked_by_whitelist(self, analyzer, prompt_status_silent):
        """Non-whitelisted pane should block all heuristics"""
        queue = make_queue_with_content("line1\nline2\nline3")

        result = analyzer.analyze(
            pane_id="test",
            pane_title="-zsh",
            current_status=TaskStatus.IDLE,
            current_source="shell",
            prompt_status=prompt_status_silent,
            queue=queue,
            job_name="zsh",  # Not in whitelist
        )

        assert result.signal is None
        assert "gate_failed" in result.reason


class TestNegativePatterns:
    """Test negative pattern suppression"""

    def test_spinner_followed_by_prompt_char_suppressed(self, analyzer, prompt_status_silent):
        """Spinner followed by > should be suppressed"""
        queue = make_queue_with_quiet("⠋>", quiet_seconds=3.0)

        result = analyzer.analyze(
            pane_id="test",
            pane_title="-zsh",
            job_name="gemini",
            current_status=TaskStatus.RUNNING,
            current_source="content",
            prompt_status=prompt_status_silent,
            queue=queue,
        )

        assert result.signal is None
        assert "negative_pattern" in result.reason


# === Stage 2: Keyword-driven transitions ===


class TestInterruptPatterns:
    """Test Stage 2 interrupt keyword detection"""

    def test_matches_esc_to_interrupt(self, analyzer):
        """'esc to interrupt' should match interrupt pattern"""
        assert analyzer._matches_interrupt("Press esc to interrupt")
        assert analyzer._matches_interrupt("esc to interrupt")
        assert analyzer._matches_interrupt("ESC TO INTERRUPT")

    def test_matches_esc_to_cancel(self, analyzer):
        """'esc to cancel' should match interrupt pattern"""
        assert analyzer._matches_interrupt("esc to cancel")
        assert analyzer._matches_interrupt("Press esc to cancel the operation")

    def test_matches_press_esc_to_stop(self, analyzer):
        """'press esc to stop' should match interrupt pattern"""
        assert analyzer._matches_interrupt("press esc to stop")

    def test_non_interrupt_not_detected(self, analyzer):
        """Regular text should not match interrupt patterns"""
        assert not analyzer._matches_interrupt("Hello world")
        assert not analyzer._matches_interrupt("Processing...")
        assert not analyzer._matches_interrupt("Press Enter to continue")


class TestApprovalPatterns:
    """Test Stage 2 approval keyword detection"""

    def test_matches_1_yes(self, analyzer):
        """'1. Yes' should match approval pattern"""
        assert analyzer._matches_approval("1. Yes")
        assert analyzer._matches_approval("1.Yes")
        assert analyzer._matches_approval("1.  Yes")

    def test_matches_1_yes_allow(self, analyzer):
        """'1. Yes, allow' should match approval pattern"""
        assert analyzer._matches_approval("1. Yes, allow once")
        assert analyzer._matches_approval("1. Yes allow")

    def test_matches_bracket_yes(self, analyzer):
        """'[Y]es' should match approval pattern"""
        assert analyzer._matches_approval("[Y]es")

    def test_non_approval_not_detected(self, analyzer):
        """Regular text should not match approval patterns"""
        assert not analyzer._matches_approval("Hello world")
        assert not analyzer._matches_approval("Yes")
        assert not analyzer._matches_approval("2. No")


def make_queue_with_content_and_quiet(
    content: str,
    quiet_seconds: float,
    session_id: str = "test-session"
) -> PaneChangeQueue:
    """Create a queue with content that has been stable for quiet_seconds"""
    queue = PaneChangeQueue(session_id)
    queue.check_and_record(content)
    now = datetime.now()
    old_time = datetime.fromtimestamp(now.timestamp() - quiet_seconds - 1)
    if queue._records:
        for record in queue._records:
            record.timestamp = old_time
            record.updated_at = old_time
            if not record.raw_tail:
                record.raw_tail = content
    queue._last_change_at = old_time
    return queue


class TestInterruptAppearance:
    """Test Stage 2: interrupt appearance triggers RUNNING"""

    def test_interrupt_appearance_triggers_run_from_idle(self, analyzer, prompt_status_silent):
        """Interrupt appearance should trigger heuristic_run from IDLE (no newline needed)"""
        # First analyze without interrupt (sets baseline)
        queue1 = make_queue_with_content("Starting task...")
        analyzer.analyze(
            pane_id="test",
            pane_title="-zsh",
            job_name="gemini",
            current_status=TaskStatus.IDLE,
            current_source="content",
            prompt_status=prompt_status_silent,
            queue=queue1,
        )

        # Now analyze with interrupt appearing (same pane)
        queue2 = make_queue_with_content("Working... esc to interrupt")
        result = analyzer.analyze(
            pane_id="test",
            pane_title="-zsh",
            job_name="gemini",
            current_status=TaskStatus.IDLE,
            current_source="content",
            prompt_status=prompt_status_silent,
            queue=queue2,
        )

        assert result.signal == "heuristic_run"
        assert "interrupt_appeared" in result.reason

    def test_interrupt_persistence_no_reemit(self, analyzer, prompt_status_silent):
        """Interrupt persisting should NOT re-emit heuristic_run"""
        # First appearance
        queue1 = make_queue_with_content("Working... esc to interrupt")
        result1 = analyzer.analyze(
            pane_id="test",
            pane_title="-zsh",
            job_name="gemini",
            current_status=TaskStatus.IDLE,
            current_source="content",
            prompt_status=prompt_status_silent,
            queue=queue1,
        )
        assert result1.signal == "heuristic_run"

        # Clear debounce
        state = analyzer._get_pane_state("test")
        state.last_signal_at = 0.0

        # Same content (interrupt still present)
        queue2 = make_queue_with_content("Working... esc to interrupt")
        result2 = analyzer.analyze(
            pane_id="test",
            pane_title="-zsh",
            job_name="gemini",
            current_status=TaskStatus.IDLE,
            current_source="content",
            prompt_status=prompt_status_silent,
            queue=queue2,
        )
        # Should not emit again (interrupt_present was already True)
        assert result2.signal is None or "newline_gate" in result2.reason


class TestInterruptDisappearance:
    """Test Stage 2: interrupt disappearance triggers DONE (with conditions)"""

    def test_interrupt_disappear_with_quiet_triggers_done(self, analyzer, prompt_status_silent):
        """Interrupt disappearing with sufficient quiet should trigger DONE"""
        # Setup: interrupt present, state RUNNING
        queue1 = make_queue_with_content("Working... esc to interrupt")
        analyzer.analyze(
            pane_id="test",
            pane_title="-zsh",
            job_name="gemini",
            current_status=TaskStatus.RUNNING,
            current_source="content",
            prompt_status=prompt_status_silent,
            queue=queue1,
        )

        # Mark state as interrupt_present
        state = analyzer._get_pane_state("test")
        state.interrupt_present = True
        state.last_signal_at = 0.0  # Clear debounce

        # Interrupt disappears with quiet (use content without completion tokens)
        queue2 = make_queue_with_content_and_quiet("All operations stopped", quiet_seconds=3.0)
        result = analyzer.analyze(
            pane_id="test",
            pane_title="-zsh",
            job_name="gemini",
            current_status=TaskStatus.RUNNING,
            current_source="content",
            prompt_status=prompt_status_silent,
            queue=queue2,
        )

        assert result.signal == "heuristic_done"
        assert "interrupt_disappeared" in result.reason

    def test_interrupt_disappear_without_quiet_no_done(self, analyzer, prompt_status_silent):
        """Interrupt disappearing WITHOUT quiet should NOT trigger DONE"""
        # Setup: mark interrupt as present
        state = analyzer._get_pane_state("test")
        state.interrupt_present = True
        state.last_signal_at = 0.0

        # Interrupt disappears but no quiet (content just changed)
        queue = make_queue_with_content("New output line")  # No quiet simulation
        result = analyzer.analyze(
            pane_id="test",
            pane_title="-zsh",
            job_name="gemini",
            current_status=TaskStatus.RUNNING,
            current_source="content",
            prompt_status=prompt_status_silent,
            queue=queue,
        )

        assert result.signal is None
        assert "interrupt_disappeared_no_quiet" in result.reason

    def test_interrupt_disappear_with_prompt_anchor_triggers_done(self, analyzer, prompt_status_silent):
        """Interrupt disappearing with prompt anchor should trigger DONE (no quiet needed)"""
        # Setup: mark interrupt as present
        state = analyzer._get_pane_state("test")
        state.interrupt_present = True
        state.last_signal_at = 0.0

        # Interrupt disappears, prompt anchor present (no quiet)
        queue = make_queue_with_content(">>> ")
        result = analyzer.analyze(
            pane_id="test",
            pane_title="-zsh",
            job_name="gemini",
            current_status=TaskStatus.RUNNING,
            current_source="content",
            prompt_status=prompt_status_silent,
            queue=queue,
        )

        assert result.signal == "heuristic_done"
        assert "interrupt_disappeared" in result.reason


class TestApprovalAppearance:
    """Test Stage 2: approval appearance triggers WAITING"""

    def test_approval_appearance_triggers_wait(self, analyzer, prompt_status_silent):
        """Approval pattern appearing should trigger heuristic_wait"""
        # First analyze without approval
        queue1 = make_queue_with_content("Processing...")
        analyzer.analyze(
            pane_id="test",
            pane_title="-zsh",
            job_name="gemini",
            current_status=TaskStatus.RUNNING,
            current_source="content",
            prompt_status=prompt_status_silent,
            queue=queue1,
        )

        state = analyzer._get_pane_state("test")
        state.last_signal_at = 0.0

        # Now with approval appearing
        queue2 = make_queue_with_content("Do you want to proceed?\n1. Yes\n2. No")
        result = analyzer.analyze(
            pane_id="test",
            pane_title="-zsh",
            job_name="gemini",
            current_status=TaskStatus.RUNNING,
            current_source="content",
            prompt_status=prompt_status_silent,
            queue=queue2,
        )

        assert result.signal == "heuristic_wait"
        assert "approval_appeared" in result.reason

    def test_approval_persistence_no_reemit(self, analyzer, prompt_status_silent):
        """Approval persisting should NOT re-emit heuristic_wait"""
        # First appearance
        queue1 = make_queue_with_content("1. Yes\n2. No")
        result1 = analyzer.analyze(
            pane_id="test",
            pane_title="-zsh",
            job_name="gemini",
            current_status=TaskStatus.RUNNING,
            current_source="content",
            prompt_status=prompt_status_silent,
            queue=queue1,
        )
        assert result1.signal == "heuristic_wait"

        # Clear debounce
        state = analyzer._get_pane_state("test")
        state.last_signal_at = 0.0

        # Same content (approval still present)
        queue2 = make_queue_with_content("1. Yes\n2. No")
        result2 = analyzer.analyze(
            pane_id="test",
            pane_title="-zsh",
            job_name="gemini",
            current_status=TaskStatus.RUNNING,
            current_source="content",
            prompt_status=prompt_status_silent,
            queue=queue2,
        )
        # Should not emit again (approval_present was already True)
        assert result2.signal is None


class TestStage2Priority:
    """Test Stage 2 signal priority ordering"""

    def test_prompt_anchor_beats_interrupt_disappear(self, analyzer, prompt_status_silent):
        """Prompt anchor DONE should have higher priority than interrupt disappear DONE"""
        # Setup: interrupt was present
        state = analyzer._get_pane_state("test")
        state.interrupt_present = True
        state.last_signal_at = 0.0

        # Both conditions met: prompt anchor AND interrupt disappeared
        queue = make_queue_with_content_and_quiet(">>> ", quiet_seconds=3.0)
        result = analyzer.analyze(
            pane_id="test",
            pane_title="-zsh",
            job_name="gemini",
            current_status=TaskStatus.RUNNING,
            current_source="content",
            prompt_status=prompt_status_silent,
            queue=queue,
        )

        assert result.signal == "heuristic_done"
        # Should mention prompt_anchor, not interrupt_disappeared
        assert "prompt_anchor" in result.reason

    def test_approval_beats_spinner(self, analyzer, prompt_status_silent):
        """Approval appearance should have higher priority than spinner WAIT"""
        # First analyze to set baseline (use content without "..." which is a prompt anchor)
        queue1 = make_queue_with_content("Processing task")
        analyzer.analyze(
            pane_id="test",
            pane_title="-zsh",
            job_name="gemini",
            current_status=TaskStatus.RUNNING,
            current_source="content",
            prompt_status=prompt_status_silent,
            queue=queue1,
        )

        state = analyzer._get_pane_state("test")
        state.last_signal_at = 0.0

        # Both approval AND spinner present (use percentage spinner, not "...")
        queue2 = make_queue_with_content_and_quiet("1. Yes\n50%", quiet_seconds=2.0)
        result = analyzer.analyze(
            pane_id="test",
            pane_title="-zsh",
            job_name="gemini",
            current_status=TaskStatus.RUNNING,
            current_source="content",
            prompt_status=prompt_status_silent,
            queue=queue2,
        )

        assert result.signal == "heuristic_wait"
        # Should be from approval, not spinner
        assert "approval_appeared" in result.reason


class TestStage2StateTracking:
    """Test Stage 2 per-pane state tracking"""

    def test_interrupt_state_cleared_on_done(self, analyzer, prompt_status_silent):
        """Interrupt tracking should be cleared when DONE is emitted"""
        # Setup: interrupt present
        state = analyzer._get_pane_state("test")
        state.interrupt_present = True
        state.interrupt_seen_at = datetime.now().timestamp()
        state.last_signal_at = 0.0

        # Trigger DONE via interrupt disappear
        queue = make_queue_with_content_and_quiet("Task done", quiet_seconds=3.0)
        result = analyzer.analyze(
            pane_id="test",
            pane_title="-zsh",
            job_name="gemini",
            current_status=TaskStatus.RUNNING,
            current_source="content",
            prompt_status=prompt_status_silent,
            queue=queue,
        )

        assert result.signal == "heuristic_done"
        # State should be cleared
        assert state.interrupt_present is False
        assert state.interrupt_seen_at is None

    def test_separate_pane_states(self, analyzer, prompt_status_silent):
        """Different panes should have independent state tracking"""
        # Pane A: interrupt present
        queue_a = make_queue_with_content("Pane A: esc to interrupt")
        analyzer.analyze(
            pane_id="pane-a",
            pane_title="-zsh",
            job_name="gemini",
            current_status=TaskStatus.IDLE,
            current_source="content",
            prompt_status=prompt_status_silent,
            queue=queue_a,
        )

        # Pane B: no interrupt
        queue_b = make_queue_with_content("Pane B: normal output")
        queue_b.check_and_record("Pane B: normal output\nmore lines")
        analyzer.analyze(
            pane_id="pane-b",
            pane_title="-zsh",
            job_name="gemini",
            current_status=TaskStatus.IDLE,
            current_source="content",
            prompt_status=prompt_status_silent,
            queue=queue_b,
        )

        state_a = analyzer._get_pane_state("pane-a")
        state_b = analyzer._get_pane_state("pane-b")

        assert state_a.interrupt_present is True
        assert state_b.interrupt_present is False


class TestJobNameTransitions:
    """Test jobName-based gating (zsh -> python -> gemini transitions)"""

    def test_job_transition_zsh_to_gemini(self, analyzer, prompt_status_silent):
        """Gate should open when job transitions from zsh to gemini"""
        queue = make_queue_with_content("line1")
        queue.check_and_record("line1\nline2\nline3")

        # With zsh job, gate should fail
        result_zsh = analyzer.analyze(
            pane_id="test",
            pane_title="-zsh",
            current_status=TaskStatus.IDLE,
            current_source="shell",
            prompt_status=prompt_status_silent,
            queue=queue,
            job_name="zsh",
        )
        assert result_zsh.signal is None
        assert "gate_failed" in result_zsh.reason

        # With gemini job, gate should pass
        result_gemini = analyzer.analyze(
            pane_id="test",
            pane_title="-zsh",
            current_status=TaskStatus.IDLE,
            current_source="shell",
            prompt_status=prompt_status_silent,
            queue=queue,
            job_name="gemini",
        )
        assert result_gemini.signal == "heuristic_run"

    def test_job_transition_python_passes(self, analyzer, prompt_status_silent):
        """python in JOB_WHITELIST should pass gate"""
        queue = make_queue_with_content("line1")
        queue.check_and_record("line1\nline2\nline3")

        result = analyzer.analyze(
            pane_id="test",
            pane_title="-zsh",
            current_status=TaskStatus.IDLE,
            current_source="shell",
            prompt_status=prompt_status_silent,
            queue=queue,
            job_name="python",
        )
        assert result.signal == "heuristic_run"

    def test_job_transition_node_passes(self, analyzer, prompt_status_silent):
        """node in JOB_WHITELIST should pass gate"""
        queue = make_queue_with_content("line1")
        queue.check_and_record("line1\nline2\nline3")

        result = analyzer.analyze(
            pane_id="test",
            pane_title="-zsh",
            current_status=TaskStatus.IDLE,
            current_source="shell",
            prompt_status=prompt_status_silent,
            queue=queue,
            job_name="node",
        )
        assert result.signal == "heuristic_run"

    def test_missing_job_name_fallback_to_title(self, analyzer, prompt_status_silent):
        """Empty job_name should fallback to pane_title for whitelist"""
        queue = make_queue_with_content("line1")
        queue.check_and_record("line1\nline2\nline3")

        # Empty job_name with gemini in title
        result = analyzer.analyze(
            pane_id="test",
            pane_title="gemini-cli",
            current_status=TaskStatus.IDLE,
            current_source="shell",
            prompt_status=prompt_status_silent,
            queue=queue,
            job_name="",
        )
        assert result.signal == "heuristic_run"

    def test_missing_job_name_no_match(self, analyzer, prompt_status_silent):
        """Empty job_name with generic title should fail gate"""
        queue = make_queue_with_content("line1")
        queue.check_and_record("line1\nline2\nline3")

        result = analyzer.analyze(
            pane_id="test",
            pane_title="-zsh",
            current_status=TaskStatus.IDLE,
            current_source="shell",
            prompt_status=prompt_status_silent,
            queue=queue,
            job_name="",
        )
        assert result.signal is None
        assert "gate_failed" in result.reason

    def test_no_crash_on_none_values(self, analyzer, prompt_status_silent):
        """Analyzer should handle edge cases without crashing"""
        queue = make_queue_with_content("content")

        # Empty strings should not crash
        result = analyzer.analyze(
            pane_id="test",
            pane_title="",
            current_status=TaskStatus.IDLE,
            current_source="shell",
            prompt_status=prompt_status_silent,
            queue=queue,
            job_name="",
        )
        # Should fail gate gracefully
        assert result.signal is None
