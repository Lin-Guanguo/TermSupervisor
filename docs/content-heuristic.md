# Content Heuristic for Long-Running Pane Recovery

Last Updated: 2025-12-02

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

## Implementation Status

- Shipped (Phases 0–5): config/regex surfaces, prompt-silence gate, newline + burst feed, tiered analyzer, heuristic transitions with WAITING fallbacks, and unit coverage in `tests/analysis/test_content_heuristic.py`.
- Job metadata capture is live: `jobName`/`jobPid`/`commandLine` are pulled each poll via `ITerm2Client.get_session_job_metadata`, stored on `PaneHistory`, and used by the analyzer; `commandLine` is redacted via token masking + `COMMAND_LINE_MAX_LENGTH`.
- **Stage 2 shipped**: Keyword-driven transitions for interrupt/approval patterns. Interrupt appearance → RUNNING, interrupt disappearance + quiet/anchor → DONE, approval appearance → WAITING_APPROVAL.
- Next active work: optional telemetry/UI surfacing remains open.

## Phase Checklist

- [x] Phase 0: Config + regex surfaces
- [x] Phase 1: PromptMonitor status plumbed to analyzer
- [x] Phase 2: Newline/burst enrichment on PaneChangeQueue
- [x] Phase 3: Tiered analyzer with debounce/idle re-emit + regex checks
- [x] Phase 4: Heuristic transitions wired with WAITING fallbacks
- [x] Phase 5: Integration-lite validation in tests
- [x] Phase 6: Stage 2 keyword transitions (interrupt/approval)
- [ ] Phase 7 (optional): UI/telemetry surfacing of heuristic counters/reasons

### Style/Modularity Notes

- Centralize regex/constants in `config.py`; no inline literals in analyzer.
- Keep helpers small (`_matches_prompt_anchor`, `_is_interactivity_tail`); add brief comments only for non-obvious gates (prompt silence, newline gate).
- Maintain type hints and ASCII; preserve existing architecture boundaries (analysis module emits to HookManager, not directly to state machine).

## JobName Integration (current status + follow-ups)

- Status: jobName/jobPid/commandLine/tty are fetched every poll via `ITerm2Client.get_session_job_metadata`; `_passes_whitelist` prefers jobName when present; `PaneHistory` stores redacted command lines for analyzer metrics.
- Follow-ups: treat jobName flips as gate triggers (pause/resume heuristics when leaving/entering whitelist); optionally surface jobName/commandLine metadata in telemetry/dashboard; keep redaction guardrails for any logging/UI.

## API Implementation Reference

`async_get_variable` is already used in code to fetch job metadata; snippet retained for convenience.

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

## Future Heuristic Extensions

To reduce misclassification for AI/CLI tools, layer these stateful patterns:

- **Interrupt prompt disappearance (Codex)**: track `"esc to interrupt"` presence; only emit DONE when it disappears *and* quiet ≥ `T_quiet_done` (or no new output for a short window) to avoid early flips when the line scrolls off-screen.
- **Interrupt-driven start/stop sequencing**: treat presence of `"esc to interrupt"` as RUNNING even without newline/burst; store `interrupt_seen_at` and only allow DONE after disappearance + quiet window or prompt anchor appears.
- **Spinner → prompt flip**: if a spinner is active and a prompt anchor appears within `T_quiet_done`, emit DONE even if quiet is short (prompt wins over spinner).
- **Keepalive plateau**: for steady spinner/ellipsis keepalives, if only spinner tokens arrive for > `T_stall`, emit WAITING instead of staying RUNNING; clear on any non-spinner line.
- **Markdown question flicker guard**: require interactivity matches (`?`, `:`) to persist for ≥ `T_quiet_wait`; ignore single-frame matches if new output arrives within 0.5s.
- **Foreground process flips**: when `jobName` changes from whitelisted to non-whitelisted mid-stream, pause heuristics until the next prompt-silence window to avoid cross-process state leaks.
- **Approval prompts (Codex/Gemini/LLMs)**: detect `"1. Yes"` (configurable; allow variants like `"1. Yes, allow once"` via pattern list) as WAITING_APPROVAL; auto-clear on next `content.update` or prompt anchor, mirroring existing WAITING fallbacks.

## Stage 2: Stateful Keyword Transitions (Shipped)

Status: **shipped**. Interrupt/approval keywords drive transitions only on appearance/disappearance, not continuous presence.

### Configuration

- `CONTENT_INTERRUPT_PATTERNS`: `["esc to interrupt", "esc to cancel", "press esc to stop"]`
- `CONTENT_APPROVAL_PATTERNS`: `["1\\. Yes", "1\\. Yes, allow", "[Y]es"]`
- `CONTENT_T_INTERRUPT_DONE`: defaults to `CONTENT_T_QUIET_DONE`

### Per-Pane State (`HeuristicPaneState`)

- `interrupt_seen_at`: timestamp when interrupt pattern first appeared.
- `interrupt_present`: whether interrupt is currently visible.
- `approval_seen_at`: timestamp when approval pattern first appeared.
- `approval_present`: whether approval is currently visible.

### Transition Rules

- **Interrupt appear** (not previously seen) → emit `heuristic_run` once (even without newline/burst).
- **Interrupt disappear** (was seen, now absent) → emit `heuristic_done` only if quiet ≥ `T_quiet_done` **or** prompt/completion anchor present.
- **Approval appear** (not previously seen) → emit `heuristic_wait` once.
- **Approval clear** → auto-clear on next `content.update` or prompt anchor (reuses WAITING fallbacks).
- Seen flags prevent re-emission while keyword persists; scroll-off without quiet does not trigger DONE.

### Signal Priority (RUNNING/LONG_RUNNING)

Evaluation order (first match wins):
1. DONE: prompt anchor or completion token (highest priority).
2. DONE: interrupt disappeared **and** (quiet ≥ `T_quiet_done` **or** prompt/completion anchor).
3. WAITING: approval keyword first appearance.
4. WAITING: spinner/interactivity tail with quiet ≥ `T_quiet_wait`.
5. IDLE: quiet ≥ `T_quiet_idle` + stable hash with no anchors/spinners/interactivity.

### Global Guards

- Negative patterns suppress all signals early.
- Per-signal debounce blocks rapid repeats.
- DONE/FAILED set `suppressed_until_reactivation`; no further heuristic signals until `heuristic_run`.
- Reactivation: `heuristic_run` fires on newline/burst **or** first appearance of interrupt keyword.
- Interrupt state cleared on DONE emission.

### Test Coverage

Tests in `tests/analysis/test_content_heuristic.py`:
- `TestInterruptPatterns`, `TestApprovalPatterns`: pattern matching.
- `TestInterruptAppearance`: RUNNING trigger without newline gate.
- `TestInterruptDisappearance`: DONE requires quiet or anchor; scroll-off without quiet does not DONE.
- `TestApprovalAppearance`: WAITING trigger; persistence no re-emit.
- `TestStage2Priority`: prompt anchor beats interrupt-based DONE; approval beats spinner.
- `TestStage2StateTracking`: per-pane isolation; state cleared on DONE.
