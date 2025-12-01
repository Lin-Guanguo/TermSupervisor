"""Content Heuristic Analyzer

Tiered content-driven state recovery for panes without shell integration.

Activation gate (Tier 2 fallback):
- Pane process/title matches whitelist (gemini, codex, etc.)
- PromptMonitor has been silent for T_prompt_silence

Signals emitted:
- content.heuristic_run: IDLE → RUNNING (output detected without start hook)
- content.heuristic_done: RUNNING → DONE (prompt anchor or completion token)
- content.heuristic_wait: RUNNING → WAITING_APPROVAL (spinner or interactivity)
- content.heuristic_idle: RUNNING → IDLE (quiet, no anchors)
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Callable, Awaitable

from .. import config
from ..telemetry import get_logger, metrics
from ..pane.types import TaskStatus

if TYPE_CHECKING:
    from .change_queue import PaneChangeQueue
    from ..hooks.prompt_monitor import PromptMonitorStatus

logger = get_logger(__name__)

# Compile regex patterns once at module load
_PROMPT_ANCHOR_RE = re.compile(config.CONTENT_PROMPT_ANCHOR_REGEX)
_INTERACTIVITY_RE = re.compile(config.CONTENT_INTERACTIVITY_REGEX)
_SPINNER_RES = [re.compile(p) for p in config.CONTENT_SPINNER_PATTERNS]
_NEGATIVE_RES = [re.compile(p) for p in config.CONTENT_NEGATIVE_PATTERNS]
_COMPLETION_TOKENS = [t.lower() for t in config.CONTENT_COMPLETION_TOKENS]


@dataclass
class HeuristicPaneState:
    """Per-pane heuristic state tracking"""
    last_signal: str = ""  # Last emitted signal type
    last_signal_at: float = 0.0  # Timestamp of last emission
    last_idle_emit_at: float = 0.0  # For periodic idle re-emit
    suppressed_until_reactivation: bool = False  # After DONE/FAILED


@dataclass
class HeuristicResult:
    """Result of heuristic analysis"""
    signal: str | None = None  # Signal to emit, or None
    reason: str = ""  # Human-readable reason


class ContentHeuristicAnalyzer:
    """Content-driven heuristic analyzer

    Processes PaneChangeQueue data to emit state signals when shell
    integration is unavailable or silent.
    """

    def __init__(self):
        self._pane_states: dict[str, HeuristicPaneState] = {}
        # Emit callback: (source, pane_id, event_type, data) -> Awaitable
        self._emit_callback: Callable[[str, str, str, dict], Awaitable[bool]] | None = None

    def set_emit_callback(
        self,
        callback: Callable[[str, str, str, dict], Awaitable[bool]]
    ) -> None:
        """Set callback for emitting events (typically HookManager.emit_event)"""
        self._emit_callback = callback

    def _get_pane_state(self, pane_id: str) -> HeuristicPaneState:
        """Get or create per-pane state"""
        if pane_id not in self._pane_states:
            self._pane_states[pane_id] = HeuristicPaneState()
        return self._pane_states[pane_id]

    # === Activation Gate ===

    def _passes_whitelist(
        self,
        job_name: str,
        pane_title: str,
    ) -> bool:
        """Check if job_name or pane_title matches whitelist

        Prefers job_name (foreground process) when CONTENT_HEURISTIC_PREFER_JOB_NAME
        is enabled and job_name is non-empty; falls back to pane_title.
        """
        # Prefer job_name when configured and available
        if config.CONTENT_HEURISTIC_PREFER_JOB_NAME and job_name:
            job_lower = job_name.lower()
            if any(w.lower() in job_lower for w in config.CONTENT_HEURISTIC_JOB_WHITELIST):
                return True

        # Fallback to pane title
        title_lower = pane_title.lower()
        return any(w.lower() in title_lower for w in config.CONTENT_HEURISTIC_PANE_WHITELIST)

    def _passes_prompt_silence(
        self,
        prompt_status: "PromptMonitorStatus",
        now: float,
    ) -> bool:
        """Check if PromptMonitor has been silent long enough

        Returns True if:
        - Integration is not active, OR
        - Last prompt event was > T_prompt_silence ago
        """
        if not prompt_status.integration_active:
            return True
        if prompt_status.last_prompt_event_at is None:
            return True
        silence_duration = now - prompt_status.last_prompt_event_at
        return silence_duration >= config.CONTENT_T_PROMPT_SILENCE

    def _passes_activation_gate(
        self,
        job_name: str,
        pane_title: str,
        prompt_status: "PromptMonitorStatus",
        now: float,
    ) -> bool:
        """Combined activation gate: whitelist + prompt silence"""
        if not config.CONTENT_HEURISTIC_ENABLED:
            return False
        if not self._passes_whitelist(job_name, pane_title):
            return False
        if not self._passes_prompt_silence(prompt_status, now):
            return False
        return True

    # === Pattern Matchers ===

    def _matches_prompt_anchor(self, line: str) -> bool:
        """Check if line ends with a prompt anchor"""
        return bool(_PROMPT_ANCHOR_RE.search(line))

    def _matches_interactivity(self, line: str) -> bool:
        """Check if line contains interactivity pattern (y/n, ?, etc.)"""
        return bool(_INTERACTIVITY_RE.search(line))

    def _matches_spinner(self, line: str) -> bool:
        """Check if line contains spinner/progress pattern"""
        return any(r.search(line) for r in _SPINNER_RES)

    def _matches_negative(self, line: str) -> bool:
        """Check if line matches negative pattern (suppress signal)"""
        return any(r.search(line) for r in _NEGATIVE_RES)

    def _matches_completion_token(self, line: str) -> bool:
        """Check if line contains completion token"""
        line_lower = line.lower()
        return any(token in line_lower for token in _COMPLETION_TOKENS)

    # === Signal Detection ===

    def _check_debounce(
        self,
        state: HeuristicPaneState,
        signal: str,
        now: float,
    ) -> bool:
        """Check if signal is within debounce window"""
        if state.last_signal != signal:
            return False  # Different signal, no debounce
        elapsed = now - state.last_signal_at
        return elapsed < config.CONTENT_HEURISTIC_DEBOUNCE_SEC

    def _should_reemit_idle(self, state: HeuristicPaneState, now: float) -> bool:
        """Check if idle should be re-emitted (periodic refresh)"""
        if state.last_idle_emit_at == 0.0:
            return True
        elapsed = now - state.last_idle_emit_at
        return elapsed >= config.CONTENT_HEURISTIC_REEMIT_IDLE_SEC

    def analyze(
        self,
        pane_id: str,
        pane_title: str,
        current_status: TaskStatus,
        current_source: str,
        prompt_status: "PromptMonitorStatus",
        queue: "PaneChangeQueue",
        job_name: str = "",
    ) -> HeuristicResult:
        """Analyze pane content and determine if a signal should be emitted

        Args:
            pane_id: Pane identifier
            pane_title: Pane title/process name (fallback for whitelist)
            current_status: Current pane state
            current_source: Current state source
            prompt_status: PromptMonitor status for this pane
            queue: PaneChangeQueue with content history
            job_name: Foreground process name from iTerm2 (preferred for whitelist)

        Returns:
            HeuristicResult with signal to emit (or None)
        """
        now = datetime.now().timestamp()
        state = self._get_pane_state(pane_id)

        # Check activation gate (prefer job_name, fallback to title)
        if not self._passes_activation_gate(job_name, pane_title, prompt_status, now):
            return HeuristicResult(reason="gate_failed")

        # Get content metrics
        tail_lines = queue.get_tail_lines(5)
        quiet_duration = queue.get_quiet_duration()
        newline_delta = queue.get_newline_delta()
        burst_length = queue.get_burst_length()
        hash_stable = queue.is_hash_stable()

        # Get last line for pattern matching
        last_line = tail_lines[-1] if tail_lines else ""

        # Check negative patterns (suppress all signals)
        if self._matches_negative(last_line):
            return HeuristicResult(reason="negative_pattern")

        # === Signal detection by current state ===

        if current_status == TaskStatus.IDLE:
            # heuristic_run is NEVER suppressed - it's the reactivation signal
            # This allows hook-less panes to re-enter RUNNING after idle/done
            return self._detect_run(
                state, now, newline_delta, burst_length, last_line
            )

        elif current_status in {TaskStatus.RUNNING, TaskStatus.LONG_RUNNING}:
            # Check suppression for completion signals only
            if state.suppressed_until_reactivation:
                return HeuristicResult(reason="suppressed_after_resolution")
            # Check for heuristic_done, heuristic_wait, or heuristic_idle
            return self._detect_completion(
                state, now, quiet_duration, hash_stable, last_line
            )

        # For other states (DONE, FAILED, WAITING), check if we should clear suppression
        # on next RUNNING entry (handled by explicit start hooks or heuristic_run)
        return HeuristicResult(reason="no_signal")

    def _detect_run(
        self,
        state: HeuristicPaneState,
        now: float,
        newline_delta: int,
        burst_length: int,
        last_line: str,
    ) -> HeuristicResult:
        """Detect heuristic_run: IDLE → RUNNING"""
        # Newline gate: must have new output (not just typing)
        has_newlines = newline_delta >= config.CONTENT_HEURISTIC_MIN_NEWLINES
        has_burst = burst_length >= config.CONTENT_HEURISTIC_MIN_BURST_CHARS

        if not (has_newlines or has_burst):
            return HeuristicResult(reason="newline_gate")

        # Debounce check
        if self._check_debounce(state, "heuristic_run", now):
            return HeuristicResult(reason="debounce")

        # Emit heuristic_run - this is the reactivation signal
        # Clear suppression so completion signals can fire again
        state.suppressed_until_reactivation = False
        state.last_signal = "heuristic_run"
        state.last_signal_at = now
        return HeuristicResult(
            signal="heuristic_run",
            reason=f"newlines={newline_delta} burst={burst_length}"
        )

    def _detect_completion(
        self,
        state: HeuristicPaneState,
        now: float,
        quiet_duration: float,
        hash_stable: bool,
        last_line: str,
    ) -> HeuristicResult:
        """Detect completion signals: done, wait, or idle"""

        # === heuristic_done: prompt anchor or completion token ===
        if quiet_duration >= config.CONTENT_T_QUIET_DONE:
            if self._matches_prompt_anchor(last_line) or self._matches_completion_token(last_line):
                if self._check_debounce(state, "heuristic_done", now):
                    return HeuristicResult(reason="debounce")
                state.last_signal = "heuristic_done"
                state.last_signal_at = now
                state.suppressed_until_reactivation = True
                return HeuristicResult(
                    signal="heuristic_done",
                    reason=f"prompt_anchor quiet={quiet_duration:.1f}s"
                )

        # === heuristic_wait: spinner or interactivity ===
        if quiet_duration >= config.CONTENT_T_QUIET_WAIT:
            if self._matches_spinner(last_line) or self._matches_interactivity(last_line):
                if self._check_debounce(state, "heuristic_wait", now):
                    return HeuristicResult(reason="debounce")
                state.last_signal = "heuristic_wait"
                state.last_signal_at = now
                return HeuristicResult(
                    signal="heuristic_wait",
                    reason=f"spinner/interactivity quiet={quiet_duration:.1f}s"
                )

        # === heuristic_idle: quiet with stable hash, no patterns ===
        if quiet_duration >= config.CONTENT_T_QUIET_IDLE:
            if hash_stable:
                # Don't emit if matches any active pattern
                if self._matches_spinner(last_line):
                    return HeuristicResult(reason="spinner_active")
                if self._matches_interactivity(last_line):
                    return HeuristicResult(reason="interactivity_active")
                if self._matches_prompt_anchor(last_line):
                    # Should have been caught by heuristic_done
                    return HeuristicResult(reason="prompt_anchor_should_be_done")

                # Check debounce and re-emit interval
                if self._check_debounce(state, "heuristic_idle", now):
                    return HeuristicResult(reason="debounce")
                if not self._should_reemit_idle(state, now):
                    return HeuristicResult(reason="idle_reemit_throttle")

                state.last_signal = "heuristic_idle"
                state.last_signal_at = now
                state.last_idle_emit_at = now
                state.suppressed_until_reactivation = True
                return HeuristicResult(
                    signal="heuristic_idle",
                    reason=f"quiet_stable quiet={quiet_duration:.1f}s"
                )

        return HeuristicResult(reason="no_completion_signal")

    async def process_and_emit(
        self,
        pane_id: str,
        pane_title: str,
        current_status: TaskStatus,
        current_source: str,
        prompt_status: "PromptMonitorStatus",
        queue: "PaneChangeQueue",
        job_name: str = "",
        command_line: str = "",
    ) -> bool:
        """Analyze and emit signal if appropriate

        Returns:
            True if signal was emitted
        """
        result = self.analyze(
            pane_id, pane_title, current_status, current_source,
            prompt_status, queue, job_name
        )

        if result.signal and self._emit_callback:
            logger.debug(
                f"[Heuristic] {pane_id[:8]} emit={result.signal} "
                f"job={job_name or 'N/A'} reason={result.reason}"
            )
            metrics.inc(
                "heuristic.signal_emitted",
                labels={"signal": result.signal, "job": job_name or "unknown"}
            )
            await self._emit_callback(
                "content",
                pane_id,
                result.signal,
                {
                    "reason": result.reason,
                    "job_name": job_name,
                    "command_line": command_line,  # Already redacted by caller
                }
            )
            return True

        if result.reason:
            logger.debug(
                f"[Heuristic] {pane_id[:8]} suppressed reason={result.reason}"
            )
            metrics.inc(
                "heuristic.suppressed",
                labels={"reason": result.reason}
            )

        return False

    def clear_pane(self, pane_id: str) -> None:
        """Clear state for a pane (on pane close)"""
        self._pane_states.pop(pane_id, None)

    def mark_done_or_failed(self, pane_id: str) -> None:
        """Mark pane as resolved (suppress until reactivation)"""
        state = self._get_pane_state(pane_id)
        state.suppressed_until_reactivation = True
