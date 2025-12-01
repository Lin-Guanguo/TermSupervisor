# Content Heuristic for Long-Running Pane Recovery

Last Updated: 2025-12-01

## Context

- Problem: panes that start commands without a `command_end` hook (e.g., codex) stay RUNNING → LONG_RUNNING indefinitely; focus/click cannot clear them because the state table lacks RUNNING|LONG_RUNNING → IDLE on user events.
- Goal: add content-driven signals so we can safely move RUNNING/LONG_RUNNING to DONE or IDLE when output indicates completion—without requiring new hooks.

## Strategy (Tiered, Single Source of Truth)

- **Tier 1 (Authority): PromptMonitor.** If iTerm2 Shell Integration emits `command_start`/`command_end`, those events own the state; heuristics are suppressed.
- **Tier 2 (Fallback): Content heuristics.** Activate only when both are true:
  - Pane process/title is whitelisted (default: `{"gemini", "codex"}` to avoid regular shells).
  - PromptMonitor is either unavailable or silent for the pane (no prompt events for `T_prompt_silence`; expected for subprocesses like `python`, `ssh`, `codex`).
- **Suppression on resolution:** Once a pane reaches DONE or FAILED (by any source), heuristics stop until the pane re-enters RUNNING via an explicit start signal or `heuristic_run`.

## Regex Library (maintain here; add new anchors centrally)

- `CONTENT_PROMPT_ANCHOR_REGEX`: `(?:[$#%>] |❯|➜|>>>|\.\.\.|In \[\d+\]:|\(Pdb\)|[A-Za-z]+> )\s*$`  
  Covers standard shells, modern glyphs, Python/Node multi-line (`...`), IPython (`In [n]:`), PDB, and simple name-suffixed prompts (e.g., `Gemini> `).
- `CONTENT_INTERACTIVITY_REGEX`: `(?:\([yY]/[nN]\)|\[[yY]/[nN]\]|\?\s*$|:\s*$|Press .* to .*|Press Enter to continue\.?\s*$|Select.*:\s*$)`  
  Handles y/n, questions/colons, press-to-continue, and menu selections.
- `CONTENT_SPINNER_PATTERNS`: keep existing spinner/ellipsis set (e.g., `\.{3,}$`, `\|/-`, `%`, `ETA`, `MB/s`).

## Signals to Emit

- `content.heuristic_run`: lift IDLE → RUNNING when execution output is detected without a start hook.
- `content.heuristic_done`: prefer DONE when the tail resembles a prompt or explicit completion.
- `content.heuristic_idle`: fallback to IDLE when quiet without a strong completion marker.
- `content.heuristic_wait`: ambiguous quiet period showing progress or user-input prompts; mirrors WAITING_APPROVAL handling.

## Detection Matrix (quiet + anchors + newline gate)

Inputs: cleaned tail lines, timestamps, line-rate/newline count deltas, tail hash, last change time from `PaneChangeQueue` / `PaneHistory`.

| Signal | Trigger (all required) | Notes |
| :--- | :--- | :--- |
| `heuristic_run` | Activation gate passes; current state IDLE; newline count increased OR burst > 50 chars; line-rate over threshold; debounce window clear | Newline gate prevents firing on raw typing without Enter. |
| `heuristic_wait` | Activation gate passes; state RUNNING/LONG_RUNNING; quiet ≥ `T_quiet_wait` (~1s); tail matches spinner **or** interactivity regex (y/n, ?, :, press-to-continue/menu) | Uses WAITING fallback paths; does not require newline; brief Markdown question bursts may momentarily flicker WAITING but will revert on next frame. |
| `heuristic_done` | Activation gate passes; state RUNNING/LONG_RUNNING; quiet ≥ `T_quiet_done`; tail matches prompt anchor regex (see library) or completion tokens (`done`, `finished`, `success`, `exit code 0`, `ready`, `applied`, `updated`); not blocked by negative patterns | Anchored end-of-line focus covers REPL prompts (`>>>`, `...`, `In [n]:`, `Gemini>`, `Pdb`). |
| `heuristic_idle` | Activation gate passes; state RUNNING/LONG_RUNNING; quiet ≥ `T_quiet_idle`; no spinner/interactivity/prompt anchors; tail hash stable; debounce window clear | Periodic re-emit allowed every `CONTENT_HEURISTIC_REEMIT_IDLE_SEC` if unchanged. |

Common suppressions: respect `CONTENT_NEGATIVE_PATTERNS` (e.g., spinners ending with `>`), per-signal debounce (`CONTENT_HEURISTIC_DEBOUNCE_SEC`), and stop firing after DONE/FAILED until reactivation.

## State Machine Rules

- RUNNING | LONG_RUNNING → DONE on `content.heuristic_done` (source `content`, keep `started_at`).
- RUNNING | LONG_RUNNING → IDLE on `content.heuristic_idle` (source `content`, reset `started_at`).
- RUNNING | LONG_RUNNING → WAITING_APPROVAL on `content.heuristic_wait` (source `content`, keep `started_at`); reuse WAITING fallbacks: `content.update` → RUNNING, `timer.waiting_fallback_running` → RUNNING, `timer.waiting_fallback_idle` → IDLE.
- IDLE → RUNNING on `content.heuristic_run` (source `content`, set `started_at`).

## Module Design

- Analyzer: `src/termsupervisor/analysis/content_heuristic.py`.
- Feeds on `PaneChangeQueue` output; tracks per-pane window (last N cleaned lines, last change timestamp, tail hash, newline deltas, line-rate).
- Requires PromptMonitor status per pane: `integration_active` and `last_prompt_event_at` to enforce the tiered gate (`T_prompt_silence`).
- Emits heuristic events through `HookManager.emit_event(...)`; tracks last-fired per pane for debounce; stops after DONE/FAILED until reactivated.
- Metrics: counters for fired/suppressed by signal + reason strings (visible via `make loghook`).

## Configuration Knobs (`config.py`)

- `CONTENT_HEURISTIC_ENABLED`
- `CONTENT_HEURISTIC_PANE_WHITELIST` (title-based whitelist, fallback when jobName empty)
- `CONTENT_HEURISTIC_JOB_WHITELIST` (jobName-based whitelist; default: `{"gemini", "codex", "copilot", "python", "node"}`)
- `CONTENT_HEURISTIC_PREFER_JOB_NAME` (prefer jobName over title when both available; default: `True`)
- `COMMAND_LINE_MAX_LENGTH` (max length before truncation in logs/events; default: `50`)
- `CONTENT_T_PROMPT_SILENCE` (silence window before heuristics can engage when PromptMonitor is nominally active)
- `CONTENT_T_QUIET_DONE`, `CONTENT_T_QUIET_IDLE`, `CONTENT_T_QUIET_WAIT`
- `CONTENT_HEURISTIC_DEBOUNCE_SEC`, `CONTENT_HEURISTIC_REEMIT_IDLE_SEC`
- `CONTENT_PROMPT_ANCHOR_REGEX`, `CONTENT_COMPLETION_TOKENS`, `CONTENT_NEGATIVE_PATTERNS`
- `CONTENT_INTERACTIVITY_REGEX`, `CONTENT_SPINNER_PATTERNS`
- `CONTENT_HEURISTIC_NEWLINE_GATE` (min newlines or burst size to allow `heuristic_run`)

## Testing Plan

- Unit: synthetic PaneChange sequences for prompt+quiet → DONE, burst+newline → RUNNING, spinner/input prompt → WAITING, quiet without anchors → IDLE, debounce and idle re-emit, negative-pattern suppression.
- Integration-lite: feed PaneChangeQueue with codex-like output while toggling PromptMonitor status to verify the tiered gate (no double-fire when prompts exist, heuristics engage when silent).

## Implementation Priorities

1. Surface PromptMonitor status and silence timer to the analyzer.
2. Add newline counting/burst detection to the PaneChange feed.
3. Implement the anchor/interactivity/spinner regex set and config knobs above.
4. Wire state transitions in `pane/transitions.py` and confirm WAITING fallbacks reuse the existing timers.

## Phased Implementation Plan

- **Phase 0: Config + Regex Surfaces**
  - Files: `src/termsupervisor/config.py` (defaults), `docs/content-heuristic.md` (already aligned).
  - Scope: add knobs (`CONTENT_PROMPT_ANCHOR_REGEX`, `CONTENT_INTERACTIVITY_REGEX`, `CONTENT_SPINNER_PATTERNS`, `CONTENT_HEURISTIC_PANE_WHITELIST`, `CONTENT_T_PROMPT_SILENCE`, newline gate/burst thresholds).
  - Acceptance: configs compile; no behavior change.

- **Phase 1: PromptMonitor Signal Plumb**
  - Files: `src/termsupervisor/hooks/manager.py`, `src/termsupervisor/hooks/sources/prompt_monitor.py`, `src/termsupervisor/analysis/content_heuristic.py` (input structs), `src/termsupervisor/pane/types.py`.
  - Scope: expose per-pane `integration_active` and `last_prompt_event_at` to the analyzer; typing only.
  - Acceptance: analyzer can read prompt status; existing behavior intact.

- **Phase 2: PaneChange Feed Enrichment**
  - Files: `src/termsupervisor/analysis/change_queue.py`, `src/termsupervisor/analysis/content_heuristic.py`.
  - Scope: add newline counts and burst length to PaneChange payloads; keep cleaned tail/hash; maintain O(1) per update.
  - Acceptance: metadata present; regression tests (if any) still pass.

- **Phase 3: Content Heuristic Analyzer (Tiered Gate)**
  - Files: `src/termsupervisor/analysis/content_heuristic.py`, `src/termsupervisor/runtime/bootstrap.py`.
  - Scope: implement activation gate (whitelist + prompt silence), debounce, idle re-emit, regex checks; emit events via HookManager.
  - Acceptance: unit tests cover run/done/idle/wait, debounce, prompt-silence gating.

- **Phase 4: State Machine Wiring**
  - Files: `src/termsupervisor/pane/transitions.py`, `src/termsupervisor/pane/state_machine.py` (if needed), `tests/`.
  - Scope: add heuristic_* transitions; ensure WAITING fallbacks reuse existing timers; preserve started_at rules.
  - Acceptance: transition tests pass; no regressions for existing signals.

- **Phase 5: Integration-Lite Validation**
  - Files: `tests/analysis/test_content_heuristic.py` (or similar), fixtures under `tests/fixtures/`.
  - Scope: Gemini/Codex transcripts (REPL prompts, press-enter/menu, streaming, Markdown question flicker) to validate gates and outputs.
  - Acceptance: tests green; logs show reason strings where expected.

- **Phase 6: Optional UI/Telemetry Surfacing**
  - Files: `src/termsupervisor/telemetry.py`, `templates/index.html`, `src/termsupervisor/web/app.py`.
  - Scope: expose counters/reasons; optional dashboard badge for heuristic clears.
  - Acceptance: non-blocking; only if needed.

### Style/Modularity Notes

- Centralize regex/constants in `config.py`; no inline literals in analyzer.
- Keep helpers small (`_matches_prompt_anchor`, `_is_interactivity_tail`); add brief comments only for non-obvious gates (prompt silence, newline gate).
- Maintain type hints and ASCII; preserve existing architecture boundaries (analysis module emits to HookManager, not directly to state machine).

## Further Optimization Plan (iTerm2 Variables Integration)

Context: iTerm2 exposes per-session variables (`jobName`, `jobPid`, `commandLine`, `pid`, `tty`). We currently gate heuristics by pane title; jobName would give precise foreground process IDs (gemini/codex/python REPL).

- **Data capture**: Extend layout traversal/client to fetch `jobName`, `jobPid`, and `commandLine` for each session on every poll; store alongside pane_id. Keep optional to avoid failures on missing variables.
- **Heuristic gate**: Prefer `jobName` (lowercased) for whitelist matching; fall back to pane title. Allow combined match: title OR jobName in `CONTENT_HEURISTIC_PANE_WHITELIST`.
- **State cache**: Add jobName/commandLine to `PaneHistory` (or a sidecar map) so analyzer always sees the latest foreground process without waiting for title changes.
- **Content context**: Attach `jobName`/`commandLine` to emitted heuristic events (metadata) for debugging/telemetry and potential dashboard display (why this pane cleared).
- **Change detection**: Track jobName changes as a signal; when jobName flips from non-whitelisted → whitelisted, force a heuristic gate re-evaluation; when it leaves the whitelist, consider pausing heuristics for that pane.
- **Safety**: Cap commandLine length; redact obvious secrets (token-like patterns); do not log full command lines in debug unless masked.
- **Testing**: Add fixture/mocks for sessions with jobName transitions (zsh → python → gemini) to ensure gates follow foreground process changes; confirm heuristics engage when prompt-silent and jobName hits the whitelist.

## API Implementation Reference

To implement the data capture described above, use the `async_get_variable` API on the `iterm2.Session` object.

### Required Variables

| Variable | Description | Requirement |
| :--- | :--- | :--- |
| `jobName` | Name of current **foreground** process (e.g., `vim`, `python`). Primary signal. | **Requires Shell Integration** |
| `jobPid` | PID of current **foreground** job. | **Requires Shell Integration** |
| `commandLine` | Full command line arguments. **Treat as sensitive**. | **Requires Shell Integration** |
| `tty` | Path to local TTY device. | Always available |

### Implementation Snippet

Use `asyncio.gather` to minimize polling latency:

```python
async def get_session_context(session: iterm2.Session) -> dict:
    """Fetch execution context (requires iTerm2 Shell Integration for job fields)."""
    try:
        # Fetch in parallel; return_exceptions=True handles missing variables gracefully
        results = await asyncio.gather(
            session.async_get_variable("jobName"),
            session.async_get_variable("jobPid"),
            session.async_get_variable("commandLine"),
            session.async_get_variable("tty"),
            return_exceptions=True
        )
        
        # Unpack and sanitize
        job_name, job_pid, cmd_line, tty = results
        
        return {
            "job_name": job_name if isinstance(job_name, str) else "",
            "job_pid": int(job_pid) if isinstance(job_pid, str) and job_pid.isdigit() else None,
            "command_line": cmd_line if isinstance(cmd_line, str) else "", # Redact in logs
            "tty": tty if isinstance(tty, str) else ""
        }
    except Exception:
        return {}
```

## Execution Plan (jobName-based Gating Upgrade)

Goal: switch heuristic activation from pane title matching to foreground process variables (`jobName`/`jobPid`/`commandLine`) provided by iTerm2 Shell Integration, while keeping title as a fallback.

1) Variable Capture
- Files: `src/termsupervisor/iterm/layout.py` (or a dedicated helper), `src/termsupervisor/iterm/client.py`.
- Fetch per-session vars every poll via `async_get_variable`: `jobName` (primary), `jobPid`, `commandLine` (redact when logging), `tty`.
- Use `asyncio.gather(..., return_exceptions=True)`; treat missing vars as empty; cast `jobPid` to int when possible.

2) Propagate to Runtime State
- Files: `src/termsupervisor/iterm/models.py`, `src/termsupervisor/supervisor.py`, `src/termsupervisor/analysis/change_queue.py` (if storing alongside content), `src/termsupervisor/pane/types.py` (pane metadata), `src/termsupervisor/analysis/content_heuristic.py`.
- Add `job_name` (and optionally `command_line`, `job_pid`) to pane metadata cached in `PaneHistory` (or a sidecar map) and pass to the analyzer each poll. Keep pane title as fallback.

3) Gate Logic Update
- Files: `src/termsupervisor/analysis/content_heuristic.py`, `src/termsupervisor/config.py`.
- Update `_passes_whitelist` to prefer `jobName` (lowercased) when present; fallback to pane title. Consider adding an optional `CONTENT_HEURISTIC_JOB_WHITELIST` (defaults to the same set) and a toggle to require jobName when available.

4) Event/Telemetry Context
- Files: `src/termsupervisor/analysis/content_heuristic.py`, `src/termsupervisor/telemetry.py`.
- Attach `jobName` (and redacted `commandLine`) to emitted heuristic events/metrics for debugging; avoid logging full command lines.

5) Tests
- Files: `tests/analysis/test_content_heuristic.py` (or new fixtures), possibly `tests/fixtures/`.
- Add cases for jobName transitions (zsh → python → gemini) and verify gate opens when jobName hits whitelist even if title is generic; ensure fallback works when jobName is missing; confirm safety (no crashes on missing variables).

6) Optional Dashboard Surfacing
- Files: `templates/index.html`, `src/termsupervisor/web/app.py`.
- Optionally display current `jobName`/`commandLine` (redacted) in pane tooltips or debug overlay to aid users in understanding heuristic decisions.
