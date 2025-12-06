# Content Heuristic — Keyword-Gated Design (Canonical)

Last Updated: 2025-12-06

Canonical design for the keyword-gated content heuristic; supersedes the legacy content-heuristic document (removed).

## Goals

- Remove process-name gating, and legacy content heuristics; avoid cross-repr conflicts.
- Enter `heuristic` mode only after a keyword is seen; emit nothing outside `heuristic`.
- Inside `heuristic`, support pattern detectors (`esc to <target>`, `1Yes`) with code-aware guards, plus configurable keyword signals (appear/disappear) and status emissions (RUNNING/DONE).
- Keep the rest of the system neutral: suppress legacy heuristic events while `heuristic` is active.
- Evaluate keyword deltas (seen → missing, missing → seen), not just raw presence; drive status from keyword presence.

## Mode Model

- **Default:** Neutral; heuristics off.
- **Enter:** Detect keyword on the same text stream as heuristics (case-insensitive, standalone token with word boundaries). On first hit, set `heuristic_mode=True` and clear prior heuristic state. Keyword string is configurable (e.g., `CONTENT_HEURISTIC_KEYWORD`).
- **While in `heuristic`:** The following signals may fire for that pane:
  - **Detectors:** `esc to <target>` and `1Yes` pattern matches (emitting `heuristic_esc_to` / `heuristic_1yes`)
  - **Keyword signals:** appear/disappear events from `CONTENT_HEURISTIC_KEYWORDS` mapping
  - **Status signals:** `content.heuristic_status` with `{"status": "RUNNING"}` when any tracked keyword appears, `{"status": "DONE"}` when all disappear

  Legacy heuristic signals (RUNNING/DONE/WAITING/IDLE from the old analyzer) remain suppressed **for that pane only**.
- **Cadence:** Evaluation runs on every pane context fetch with a two-phase guard:
  1. **Exit checks run unconditionally** — exit keyword and timeout are evaluated every fetch, even when content is unchanged (so timeouts fire on idle panes).
  2. **Detectors/keyword/status evaluation** runs only when the content hash changes (resource guard). Per-pane dedupe/cooldown (default 2s) further prevents rapid re-emission for the same target.
- **Exit:** Per-pane exit when the tracked shell process ends (pane PID exit), the pane ID is replaced/closed, or a configured external hook signal requests exit. Optional exit keyword and inactivity timeout are supported but default to off (timeout=0 ⇒ no auto-exit).

### External exit signals (contract)

| Event id | Source | Required fields | Effect |
| --- | --- | --- | --- |
| `iterm.session_end` | iTerm client | `pane_id`, `pid` | Exit heuristic mode for that pane. |
| `frontend.close_pane` | Web frontend | `pane_id` | Exit heuristic mode for that pane. |
| `content.exit` | External hook | `pane_id` (optional `target`) | Exit heuristic mode for that pane; ignores missing pane_id. |

## Keyword Signal Model

- Configurable signal table (appear/disappear): map keyword → signal_on_appear, signal_on_disappear; case-insensitive matching (mapping keys are normalized to lowercase at init). Evaluate deltas between frames (present → absent, absent → present) instead of single-frame detection; baseline on entry is "absent," and disappear events are suppressed until the keyword has been seen once.
- Presence tracking is per pane; store last-seen timestamps to support debounce/cooldown and avoid cross-pane bleed-through. Keyword presence also drives heuristic status (RUNNING on presence, DONE on disappearance) with dedupe.
- Example defaults: none shipped; user config defines actions (or leaves empty for no-op).
- Legacy RUNNING/DONE/WAITING/IDLE heuristic signals remain suppressed while in `heuristic` mode (per-pane).

### Status signal contract

When keyword presence changes, the analyzer emits a status signal through HookManager:

| Signal | Payload | Trigger | State machine transition |
| --- | --- | --- | --- |
| `content.heuristic_status` | `{"status": "RUNNING"}` | Any tracked keyword appears | → `RUNNING` (from any status) |
| `content.heuristic_status` | `{"status": "DONE"}` | All tracked keywords disappear | → `DONE` (from `RUNNING`/`LONG_RUNNING` with source=content) |

### Config (Python constants in `config.py`)

Configuration is defined as Python constants in `src/termsupervisor/config.py`:

```python
# Entry keyword: non-empty string enables heuristic mode; empty disables
CONTENT_HEURISTIC_KEYWORD = ""  # e.g., "go/heuristic" or "claude-code"

# Optional exit keyword (empty => disabled)
CONTENT_HEURISTIC_EXIT_KEYWORD = ""

# Optional exit timeout in seconds (0 => no auto-exit)
CONTENT_HEURISTIC_EXIT_TIMEOUT_SECONDS = 0

# Dedupe/cooldown: suppress duplicate emissions for same (pane, detector, target)
CONTENT_HEURISTIC_COOLDOWN_SECONDS = 2.0

# Resource guard: max lines to scan for heuristic patterns
CONTENT_HEURISTIC_MAX_SCAN_LINES = 200

# Keyword signal mapping: {keyword: {on_appear, on_disappear}}
CONTENT_HEURISTIC_KEYWORDS: dict[str, dict[str, str]] = {
    # Example:
    # "thinking": {"on_appear": "content.thinking", "on_disappear": "content.thinking_done"},
}

# Pattern detectors: list of pattern definitions
# Each pattern has: name, regex, signal, guards (optional), target_group (optional), cooldown (optional)
# Patterns are evaluated in order; first match on a line wins (use for priority)
# Empty list disables pattern detection
CONTENT_HEURISTIC_PATTERNS: list[dict[str, object]] = [
    {
        "name": "esc_to",
        "regex": r"\besc to ([\w./:-]{1,64})\b",
        "regex_flags": ["IGNORECASE"],
        "signal": "heuristic_esc_to",
        "target_group": 1,  # Capture group for target extraction
        "target_strip": ".,;:!?",  # Characters to strip from target
        "guards": [  # Lines matching any guard are skipped
            r"\b(class|def|function|const|let|var)\b",
            r"[{}();]",
            r"\bescape_to\b",
            r"^```|`[^`]+`",
        ],
        "cooldown": 2.0,
    },
    {
        "name": "1yes",
        "regex": r"^1\s*yes",
        "regex_flags": ["IGNORECASE", "MULTILINE"],
        "signal": "heuristic_1yes",
        "target": "approval",  # Fixed target value (no capture group)
        "guards": [
            r"\b(class|def|function|const|let|var)\b",
            r"[{}();]",
            r"\bescape_to\b",
            r"^```|`[^`]+`",
            r"\b(case|switch|enum|return)\b",
            r"^-\s+1\s*yes",
        ],
        "cooldown": 2.0,
    },
]
```

**Config notes**
- `CONTENT_HEURISTIC_KEYWORD` empty ⇒ heuristic mode disabled even if mappings exist.
- Mapping keys are normalized to lowercase at init; detection is case-insensitive.
- Multiple keywords can be active per pane; RUNNING is set if any are present, DONE when all mapped keywords are absent.
- No env/pyproject loader exists; edit `config.py` directly or override via import.

## Pattern Detectors (config-driven)

Pattern detectors are defined in `CONTENT_HEURISTIC_PATTERNS`. Each pattern has:

| Field | Type | Description |
| --- | --- | --- |
| `name` | string | Unique identifier for the pattern |
| `regex` | string | Regular expression to match |
| `regex_flags` | list | Optional flags: `IGNORECASE`, `MULTILINE` |
| `signal` | string | Signal name to emit on match |
| `guards` | list | Regex patterns that skip code-like lines |
| `target_group` | int | Capture group for target extraction (optional) |
| `target` | string | Fixed target value if no capture group (optional) |
| `target_strip` | string | Characters to strip from extracted target (optional) |
| `cooldown` | float | Per-pattern cooldown in seconds (default: `CONTENT_HEURISTIC_COOLDOWN_SECONDS`) |

**Evaluation order:** Patterns are evaluated in config order; first match on a line wins. This provides priority control (e.g., `esc_to` before `1yes`).

**Empty config:** `CONTENT_HEURISTIC_PATTERNS = []` disables all pattern detection.

### Default patterns

Two patterns are shipped by default:

- **`esc_to`**: Matches `esc to <target>` with code guards; emits `heuristic_esc_to`
- **`1yes`**: Matches `1Yes` / `1 yes` at line start; emits `heuristic_1yes` with fixed target `approval`

## Implementation Summary

The heuristic analyzer is implemented in `src/termsupervisor/analysis/heuristic.py` as the `Heuristic` class, wired into `HookManager`.

### Evaluation order (per fetch)

1. **Exit checks (unconditional)** — If heuristic mode is active, check exit keyword and timeout before the content hash guard. This ensures timeouts fire even on idle panes with unchanged content.
2. **Resource guard** — If content hash is unchanged since last fetch, skip remaining evaluation.
3. **Entry check** — If not active, check for entry keyword (word-boundary match).
4. **Detectors** — Scan recent lines (last `CONTENT_HEURISTIC_MAX_SCAN_LINES`) for configured patterns.
5. **Keyword presence** — Evaluate appear/disappear deltas for configured keywords.
6. **Status emission** — Emit `content.heuristic_status` on RUNNING/DONE flips.

### Cooldown

Dedupe key: `(detector, target_hash)` per pane. Each pattern can specify its own cooldown; default is `CONTENT_HEURISTIC_COOLDOWN_SECONDS` (2s).

### Telemetry

Metrics emitted (in-memory counters via `telemetry.metrics`):
- `heuristic.signal_emitted{signal, pane_id}` — detector signal fired
- `heuristic.signal_suppressed{reason, pane_id}` — suppressed by cooldown
- `heuristic.status_change{status}` — RUNNING/DONE status flip

Rate limiting is handled by the cooldown mechanism only (no additional per-minute caps).

## Migration Notes

- Legacy content heuristic document has been removed; this file is the sole source of truth.
- Default shipping stance: `CONTENT_HEURISTIC_KEYWORD` empty ⇒ `heuristic` disabled, no behavior change until configured.

## Refactor Execution Guide (project-wide)

All stages complete as of 2025-12-06.

- **Stage 1: Tooling & policy** ✓
- **Stage 2: Remove legacy heuristics** ✓
- **Stage 3: Config simplification** ✓
- **Stage 4: Implement keyword-gated heuristic** ✓
- **Stage 5: Type/structure hardening** ✓
- **Stage 6: Tests & verification** ✓ (221 tests passing)
