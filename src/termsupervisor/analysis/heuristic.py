"""Content Heuristic - Keyword-gated mode with per-pane tracking

Design:
- Entry: Activate when CONTENT_HEURISTIC_KEYWORD seen in pane content
- While active: Evaluate config-driven pattern detectors (CONTENT_HEURISTIC_PATTERNS)
- Status: RUNNING when tracked keywords present, DONE when all disappear
- Exit: pane close, PID end, external exit signal, or optional timeout/keyword

Cadence: Exit checks run unconditionally; detectors gated by content hash change.
Per-pane dedupe/cooldown prevents rapid re-emission for same target.
"""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..config import (
    CONTENT_HEURISTIC_COOLDOWN_SECONDS,
    CONTENT_HEURISTIC_EXIT_KEYWORD,
    CONTENT_HEURISTIC_EXIT_TIMEOUT_SECONDS,
    CONTENT_HEURISTIC_KEYWORD,
    CONTENT_HEURISTIC_KEYWORDS,
    CONTENT_HEURISTIC_MAX_SCAN_LINES,
    CONTENT_HEURISTIC_PATTERNS,
)
from ..telemetry import get_logger, metrics

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine
    from typing import Any

logger = get_logger(__name__)


@dataclass
class CompiledPattern:
    """Compiled pattern detector from config"""

    name: str
    regex: re.Pattern[str]
    signal: str
    guards: list[re.Pattern[str]]
    target_group: int | None  # Capture group for target extraction
    target_fixed: str | None  # Fixed target value (no capture group)
    target_strip: str  # Characters to strip from target
    cooldown: float


@dataclass
class PaneHeuristicState:
    """Per-pane heuristic state"""

    active: bool = False
    entered_at: float = 0.0
    last_content_hash: str = ""
    # Keyword presence tracking
    keywords_seen: set[str] = field(default_factory=set)
    current_keywords: set[str] = field(default_factory=set)
    # Status tracking
    status_is_running: bool = False
    # Cooldown tracking: key -> last_emit_time
    last_emissions: dict[str, float] = field(default_factory=dict)


def _compile_patterns(configs: list[dict[str, object]]) -> list[CompiledPattern]:
    """Compile pattern configurations into CompiledPattern objects"""
    patterns: list[CompiledPattern] = []

    for cfg in configs:
        name = str(cfg.get("name", "unnamed"))
        regex_str = str(cfg.get("regex", ""))
        if not regex_str:
            logger.warning(f"[Heuristic] Pattern '{name}' has no regex, skipping")
            continue

        # Parse regex flags
        flags = 0
        flag_names = cfg.get("regex_flags", [])
        if flag_names and not isinstance(flag_names, list):
            logger.warning(
                f"[Heuristic] Pattern '{name}' regex_flags is not a list, ignoring"
            )
            flag_names = []
        if isinstance(flag_names, list):
            for flag_name in flag_names:
                if flag_name == "IGNORECASE":
                    flags |= re.IGNORECASE
                elif flag_name == "MULTILINE":
                    flags |= re.MULTILINE

        try:
            regex = re.compile(regex_str, flags)
        except re.error as e:
            logger.warning(f"[Heuristic] Pattern '{name}' regex error: {e}, skipping")
            continue

        # Compile guard patterns
        guards: list[re.Pattern[str]] = []
        guard_strs = cfg.get("guards", [])
        if guard_strs and not isinstance(guard_strs, list):
            logger.warning(
                f"[Heuristic] Pattern '{name}' guards is not a list, ignoring"
            )
            guard_strs = []
        if isinstance(guard_strs, list):
            for guard_str in guard_strs:
                try:
                    guards.append(re.compile(str(guard_str), re.IGNORECASE))
                except re.error as e:
                    logger.warning(f"[Heuristic] Pattern '{name}' guard error: {e}, skipping guard")

        # Extract target config
        target_group_raw = cfg.get("target_group")
        target_fixed_raw = cfg.get("target")
        target_strip = str(cfg.get("target_strip", ""))

        # Parse cooldown with safe fallback
        cooldown = CONTENT_HEURISTIC_COOLDOWN_SECONDS
        cooldown_raw = cfg.get("cooldown")
        if cooldown_raw is not None:
            try:
                cooldown = float(str(cooldown_raw))
            except ValueError:
                logger.warning(
                    f"[Heuristic] Pattern '{name}' invalid cooldown '{cooldown_raw}', "
                    f"using default {CONTENT_HEURISTIC_COOLDOWN_SECONDS}s"
                )

        # Parse target_group with safe fallback
        target_group: int | None = None
        if target_group_raw is not None:
            try:
                target_group = int(str(target_group_raw))
            except ValueError:
                logger.warning(
                    f"[Heuristic] Pattern '{name}' invalid target_group '{target_group_raw}', ignoring"
                )

        patterns.append(
            CompiledPattern(
                name=name,
                regex=regex,
                signal=str(cfg.get("signal", f"heuristic_{name}")),
                guards=guards,
                target_group=target_group,
                target_fixed=str(target_fixed_raw) if target_fixed_raw is not None else None,
                target_strip=target_strip,
                cooldown=cooldown,
            )
        )

    return patterns


# Compile patterns from config at module load
_COMPILED_PATTERNS: list[CompiledPattern] = _compile_patterns(CONTENT_HEURISTIC_PATTERNS)


def _normalize_keyword_mapping(
    mapping: dict[str, dict[str, str]],
) -> dict[str, dict[str, str]]:
    """Normalize keyword mapping keys to lowercase for case-insensitive lookup"""
    return {k.lower(): v for k, v in mapping.items()}


class Heuristic:
    """Content Heuristic analyzer

    Per-pane keyword-gated mode with RUNNING/DONE status tracking.
    """

    def __init__(self) -> None:
        self._pane_states: dict[str, PaneHeuristicState] = {}
        self._emit_callback: (
            Callable[[str, str, str, dict[str, Any], bool], Coroutine[Any, Any, bool]] | None
        ) = None
        # Normalize keyword mapping to lowercase keys at init
        self._keyword_mapping: dict[str, dict[str, str]] = _normalize_keyword_mapping(
            CONTENT_HEURISTIC_KEYWORDS
        )

    def set_emit_callback(
        self,
        callback: Callable[[str, str, str, dict[str, Any], bool], Coroutine[Any, Any, bool]],
    ) -> None:
        """Set the callback for emitting signals to HookManager"""
        self._emit_callback = callback

    def _get_state(self, pane_id: str) -> PaneHeuristicState:
        """Get or create state for a pane"""
        if pane_id not in self._pane_states:
            self._pane_states[pane_id] = PaneHeuristicState()
        return self._pane_states[pane_id]

    def is_active(self, pane_id: str) -> bool:
        """Check if heuristic mode is active for a pane"""
        state = self._pane_states.get(pane_id)
        return state.active if state else False

    def exit_pane(self, pane_id: str, reason: str = "exit_signal") -> None:
        """Exit heuristic mode for a pane

        Called on pane close, PID end, or external exit signal.
        Clears last_content_hash to allow re-entry on unchanged content.
        """
        if pane_id in self._pane_states:
            state = self._pane_states[pane_id]
            if state.active:
                logger.info(f"[Heuristic] Exiting mode for pane {pane_id[:8]}: {reason}")
                state.active = False
                state.last_content_hash = ""  # Allow re-entry without content change
                state.keywords_seen.clear()
                state.current_keywords.clear()
                state.status_is_running = False
                state.last_emissions.clear()

    def remove_pane(self, pane_id: str) -> None:
        """Remove all state for a pane (on pane close)"""
        if pane_id in self._pane_states:
            del self._pane_states[pane_id]
            logger.debug(f"[Heuristic] Removed state for pane {pane_id[:8]}")

    def handle_exit_signal(self, event_id: str, pane_id: str, data: dict[str, Any]) -> bool:
        """Handle external exit signals per contract

        External exit signals (contract):
        | Event id             | Source         | Required fields              | Effect                                    |
        | -------------------- | -------------- | ---------------------------- | ----------------------------------------- |
        | iterm.session_end    | iTerm client   | pane_id, pid                 | Exit heuristic mode for that pane.        |
        | frontend.close_pane  | Web frontend   | pane_id                      | Exit heuristic mode for that pane.        |
        | content.exit         | External hook  | pane_id (optional target)    | Exit heuristic mode; ignores missing pane_id. |

        Args:
            event_id: The event identifier (e.g., "iterm.session_end")
            pane_id: The pane identifier
            data: Event data dict

        Returns:
            True if the signal was handled, False otherwise
        """
        if event_id == "iterm.session_end":
            # iTerm session ended - exit and remove pane
            self.exit_pane(pane_id, "session_end")
            self.remove_pane(pane_id)
            return True
        elif event_id == "frontend.close_pane":
            # Frontend closed pane
            self.exit_pane(pane_id, "frontend_close")
            self.remove_pane(pane_id)
            return True
        elif event_id == "content.exit":
            # External hook signal - ignores missing pane_id
            if pane_id:
                self.exit_pane(pane_id, "external_exit")
            return True
        return False

    async def evaluate(self, pane_id: str, content: str, content_hash: str) -> None:
        """Evaluate heuristics for a pane

        Called on every pane context fetch. Uses content_hash for resource guard.

        Args:
            pane_id: Pane identifier
            content: Raw pane content
            content_hash: Hash of cleaned content (for change detection)
        """
        # Feature disabled if no keyword configured
        if not CONTENT_HEURISTIC_KEYWORD:
            return

        state = self._get_state(pane_id)
        now = time.time()

        # Check exit conditions BEFORE content hash guard (timeout must fire even on idle panes)
        if state.active:
            # Limit scan to recent lines for exit keyword check
            lines = content.split("\n")
            scan_lines = lines[-CONTENT_HEURISTIC_MAX_SCAN_LINES:]
            scan_content = "\n".join(scan_lines)
            if self._check_exit(state, scan_content, now):
                self.exit_pane(pane_id, "exit_condition")
                return

        # Resource guard: skip remaining evaluation if content unchanged
        if content_hash == state.last_content_hash:
            return
        state.last_content_hash = content_hash

        # Limit scan to recent lines
        lines = content.split("\n")
        scan_lines = lines[-CONTENT_HEURISTIC_MAX_SCAN_LINES:]
        scan_content = "\n".join(scan_lines)

        # Check for entry keyword if not active
        if not state.active:
            if self._check_entry_keyword(scan_content):
                state.active = True
                state.entered_at = now
                state.keywords_seen.clear()
                state.current_keywords.clear()
                state.status_is_running = False
                logger.info(f"[Heuristic] Entered mode for pane {pane_id[:8]}")

        if not state.active:
            return

        # Evaluate detectors and keyword presence
        await self._evaluate_detectors(pane_id, state, scan_lines, now)
        await self._evaluate_keywords(pane_id, state, scan_content, now)
        await self._evaluate_status(pane_id, state, now)

    def _check_entry_keyword(self, content: str) -> bool:
        """Check if entry keyword is present as a standalone token (word boundary)"""
        keyword = CONTENT_HEURISTIC_KEYWORD
        # Use word boundary matching to avoid spurious activation on substrings
        pattern = re.compile(r"\b" + re.escape(keyword) + r"\b", re.IGNORECASE)
        return pattern.search(content) is not None

    def _check_exit(self, state: PaneHeuristicState, content: str, now: float) -> bool:
        """Check exit conditions"""
        # Exit keyword
        if CONTENT_HEURISTIC_EXIT_KEYWORD:
            if CONTENT_HEURISTIC_EXIT_KEYWORD.lower() in content.lower():
                return True

        # Exit timeout
        if CONTENT_HEURISTIC_EXIT_TIMEOUT_SECONDS > 0:
            elapsed = now - state.entered_at
            if elapsed >= CONTENT_HEURISTIC_EXIT_TIMEOUT_SECONDS:
                return True

        return False

    async def _evaluate_detectors(
        self,
        pane_id: str,
        state: PaneHeuristicState,
        lines: list[str],
        now: float,
    ) -> None:
        """Evaluate pattern detectors from config

        Patterns are evaluated in order; first match on a line wins (for priority).
        Empty config disables pattern detection.
        """
        if not _COMPILED_PATTERNS:
            return

        for line in lines:
            # Try each pattern in order (first match wins)
            for pattern in _COMPILED_PATTERNS:
                # Check guards first
                if self._is_guarded(line, pattern.guards):
                    continue

                match = pattern.regex.search(line)
                if match:
                    # Extract target
                    if pattern.target_group is not None:
                        try:
                            target = match.group(pattern.target_group)
                            if pattern.target_strip:
                                target = target.rstrip(pattern.target_strip)
                        except IndexError:
                            target = pattern.target_fixed or ""
                    else:
                        target = pattern.target_fixed or ""

                    await self._emit_detector(
                        pane_id, state, pattern.name, pattern.signal, target, pattern.cooldown, now
                    )
                    break  # First match wins, move to next line

    def _is_guarded(self, line: str, guards: list[re.Pattern[str]]) -> bool:
        """Check if line matches any guard pattern"""
        for guard in guards:
            if guard.search(line):
                return True
        return False

    async def _emit_detector(
        self,
        pane_id: str,
        state: PaneHeuristicState,
        detector: str,
        signal_name: str,
        target: str,
        cooldown: float,
        now: float,
    ) -> None:
        """Emit detector signal with cooldown"""
        # Create cooldown key: (pane_id, detector, target_hash) per spec
        target_hash = hashlib.md5(target.encode()).hexdigest()[:8]
        key = f"{detector}:{target_hash}"

        # Check cooldown (per-pattern cooldown from config)
        last_emit = state.last_emissions.get(key, 0)
        if now - last_emit < cooldown:
            # Track suppressed signals per telemetry contract
            metrics.inc(
                "heuristic.signal_suppressed",
                {"reason": "cooldown", "pane_id": pane_id},
            )
            return

        state.last_emissions[key] = now

        # Emit signal if callback configured
        if self._emit_callback:
            logger.debug(f"[Heuristic] Emit {signal_name} for {pane_id[:8]}: {target}")
            # Track emitted signals per telemetry contract
            metrics.inc(
                "heuristic.signal_emitted",
                {"signal": signal_name, "pane_id": pane_id},
            )
            await self._emit_callback(
                "content",
                pane_id,
                signal_name,
                {"target": target, "detector": detector},
                False,  # log=False
            )

    async def _evaluate_keywords(
        self,
        pane_id: str,
        state: PaneHeuristicState,
        content: str,
        now: float,
    ) -> None:
        """Evaluate keyword presence and emit appear/disappear signals"""
        if not self._keyword_mapping:
            return

        content_lower = content.lower()
        new_keywords: set[str] = set()

        # Use normalized mapping keys (already lowercase)
        for keyword_lower in self._keyword_mapping:
            if keyword_lower in content_lower:
                new_keywords.add(keyword_lower)

        # Detect appear/disappear deltas
        appeared = new_keywords - state.current_keywords
        disappeared = state.current_keywords - new_keywords

        # Emit appear signals
        for keyword in appeared:
            state.keywords_seen.add(keyword)
            mapping = self._keyword_mapping.get(keyword, {})
            on_appear = mapping.get("on_appear")
            if on_appear and self._emit_callback:
                await self._emit_callback(
                    "content",
                    pane_id,
                    on_appear.replace("content.", ""),
                    {"keyword": keyword},
                    False,
                )

        # Emit disappear signals (only if previously seen)
        for keyword in disappeared:
            if keyword in state.keywords_seen:
                mapping = self._keyword_mapping.get(keyword, {})
                on_disappear = mapping.get("on_disappear")
                if on_disappear and self._emit_callback:
                    await self._emit_callback(
                        "content",
                        pane_id,
                        on_disappear.replace("content.", ""),
                        {"keyword": keyword},
                        False,
                    )

        state.current_keywords = new_keywords

    async def _evaluate_status(
        self,
        pane_id: str,
        state: PaneHeuristicState,
        now: float,
    ) -> None:
        """Evaluate RUNNING/DONE status based on keyword presence

        Per spec: RUNNING when any tracked keyword is present, DONE when all disappear.
        Dedupe so RUNNING/DONE fire only on presence flips.
        """
        # Status is RUNNING if any configured keywords are present
        has_keywords = bool(state.current_keywords)

        if has_keywords and not state.status_is_running:
            # Transition to RUNNING
            state.status_is_running = True
            logger.debug(f"[Heuristic] Status RUNNING for {pane_id[:8]}")
            # Track status change per telemetry contract
            metrics.inc("heuristic.status_change", {"status": "RUNNING"})
            # Emit status signal to HookManager
            if self._emit_callback:
                await self._emit_callback(
                    "content",
                    pane_id,
                    "heuristic_status",
                    {"status": "RUNNING"},
                    False,
                )

        elif not has_keywords and state.status_is_running:
            # Transition to DONE (only if we've seen keywords before)
            if state.keywords_seen:
                state.status_is_running = False
                logger.debug(f"[Heuristic] Status DONE for {pane_id[:8]}")
                # Track status change per telemetry contract
                metrics.inc("heuristic.status_change", {"status": "DONE"})
                # Emit status signal to HookManager
                if self._emit_callback:
                    await self._emit_callback(
                        "content",
                        pane_id,
                        "heuristic_status",
                        {"status": "DONE"},
                        False,
                    )

    def debug_state(self, pane_id: str) -> dict[str, Any]:
        """Get debug state for a pane"""
        state = self._pane_states.get(pane_id)
        if not state:
            return {"active": False}

        return {
            "active": state.active,
            "entered_at": state.entered_at,
            "keywords_seen": list(state.keywords_seen),
            "current_keywords": list(state.current_keywords),
            "status_is_running": state.status_is_running,
            "emission_count": len(state.last_emissions),
        }
