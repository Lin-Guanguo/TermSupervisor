# TermSupervisor

Monitor iTerm2 pane content changes with a real-time web dashboard.

![TermSupervisor + iTerm2](docs/image.jpg)
*Left: iTerm2 with multiple panes | Right: TermSupervisor dashboard mirroring the layout in real-time*

## Features

- **Real-time dashboard**: Mirrors the full iTerm2 layout with SVG rendering and per-pane status overlays.
- **Layout controls**: Adjustable tabs-per-row (1–6), hidden-tab dropdowns, context menu rename/hide, and inline “+ Tab” with layout presets.
- **State pipeline**: HookManager → StateManager (per-pane ActorQueue) → PaneStateMachine → Pane display (delay + notification suppression) with Timer driving LONG_RUNNING and delayed clears.
- **Content change detection**: 1s polling → ContentCleaner → PaneChangeQueue throttling; refresh on ≥5 changed lines or 10s timeout and emit `content.changed` for WAITING→RUNNING fallback.
- **Notifications**: Floating panel with status colors; focus-aware suppression for <3s tasks or focused panes.

## Architecture

```
Signal Sources (shell | claude-code | iterm focus | frontend click | timer.check | content.changed)
        │
        ▼
┌──────────────────────────┐
│       HookManager        │ normalize + metrics + enqueue
└──────────┬───────────────┘
           ▼
┌──────────────────────────┐
│      StateManager        │ per-pane ActorQueue + cleanup
└──────────┬───────────────┘
           ▼
┌────────────────┐     ┌────────────────┐
│PaneStateMachine│     │      Pane      │
│rules/history   │     │delay + notify  │
└────────────────┘     │suppression     │
        ▲              └──────┬─────────┘
        │                     │
   Timer.tick (LONG_RUNNING)  │ Timer.delay (DONE/FAILED→IDLE)
        └──────────────┬──────┘
                       ▼
      Status callback → WebSocket/UI
```

- `runtime/bootstrap.py` creates a single Timer + HookManager + Sources/Receiver; Timer ticks every 1s for LONG_RUNNING and Pane delay tasks.
- Layout/content path: `TermSupervisor` polls iTerm2 → ContentCleaner → PaneChangeQueue (≥5 lines or 10s) → layout snapshot + `content.changed` to HookManager; WebServer pushes layout + pane statuses via WebSocket.
- Hook sources: Shell PromptMonitor, Claude Code HTTP hook, iTerm focus debounce (2s); frontend actions use JSON messages on `/ws`.

### State Machine

6 states with explicit source isolation (no SOURCE_PRIORITY; rules use from_source):

| State | Trigger Events | Color | Visual Effect |
|-------|---------------|-------|---------------|
| IDLE | `idle_prompt`, `SessionEnd`, focus/click | - | Hidden |
| RUNNING | `command_start`, `PreToolUse`, `SessionStart` | Blue | Rotating border |
| LONG_RUNNING | RUNNING > 60s | Dark blue | Rotating border |
| WAITING_APPROVAL | `Notification:permission_prompt` | Yellow | Blinking |
| DONE | `command_end`(exit=0), `Stop` | Green | Blinking |
| FAILED | `command_end`(exit≠0) | Red | Blinking |

### Content Change Detection

```
1s Polling → ContentCleaner → PaneChangeQueue → SVG Refresh + content.changed → HookManager
                  │                  │
                  │                  ├── Refresh: ≥5 lines changed or 10s timeout
                  │                  └── Queue push: ≥20 lines changed
                  │
                  └── Unicode whitelist: letters, digits, CJK only
                      (filters ANSI, spinners, progress bars, punctuation)
```

## Project Structure

```
src/termsupervisor/
├── config.py               # All configuration constants
├── telemetry.py            # Logger + in-memory metrics facade
├── timer.py                # Interval/delay scheduler
├── supervisor.py           # Polling + content.changed emission + layout mirror
├── runtime/
│   └── bootstrap.py        # Centralized component construction
├── pane/
│   ├── manager.py          # StateManager (per-pane ActorQueue, LONG_RUNNING)
│   ├── state_machine.py    # Transition processing + history
│   ├── transitions.py      # Rule table (WAITING→RUNNING, etc.)
│   ├── pane.py             # Display (delay, notification suppression)
│   ├── queue.py            # ActorQueue with generation/backpressure
│   └── predicates.py, types.py
├── hooks/
│   ├── manager.py          # HookManager facade (normalize/enqueue)
│   ├── receiver.py         # HTTP /api/hook endpoint
│   └── sources/            # Shell, Claude Code, iTerm focus debounce, PromptMonitor
│       └── prompt_monitor.py   # iTerm2 PromptMonitor wrapper
├── analysis/               # ContentCleaner + change_queue (content throttle DTOs)
│   └── change_queue.py     # PaneChangeQueue, PaneHistory, PaneChange, ChangeRecord
├── iterm/                  # Layout traversal + client helpers + layout models
│   └── models.py           # LayoutData, WindowInfo, TabInfo, PaneInfo, PaneSnapshot
├── render/                 # SVG renderer
├── web/                    # FastAPI + WebSocket handlers
└── templates/index.html    # Frontend (vanilla JS)
```

## Docs

- Current architecture: `docs/state-architecture.md`
- Design source: `mnema/state-architecture/`
- Hook refactor notes: `docs/hook-manager-refactor.md`

## Current Status Notes

- runtime/bootstrap builds the single Timer + HookManager + Sources stack; per-pane ActorQueue + generation gating are active.
- WebSocket handler is JSON-only (`activate/rename/create_tab`); status changes broadcast from HookManager callback.
- `supervisor.py` still uses PaneChangeQueue for content throttle; a dedicated content hook source is still pending.
- State is in-memory only; restart resets all state/history.
- Telemetry metrics are in-memory only (no Prometheus/StatsD sink yet).

## Install

```bash
uv sync
```

## Usage

**Prerequisite:** Enable Python API in iTerm2
- iTerm2 → Settings → General → Magic → Enable Python API

### Web Dashboard

```bash
make run          # Start in background
make stop         # Stop server
make rerun        # Restart

make viewlog      # View full log
make taillog      # Follow log
make loghook      # Monitor hook events only
make logerr       # Monitor errors only
```

Open http://localhost:8765

### Debugging State Pipeline

- New: `GET /api/debug/state/{session_id}?max_history=30&max_pending_events=10` (FastAPI). Returns status machine snapshot (status/source/state_id/description), display state, queue snapshot (depth, drops, pending signals), WAITING fallback info, recent history with failure reasons (`stale_generation`, `no_rule_matched`, `predicate_failed`), and current content hash. Use to see why a signal did or didn’t transition.
- Existing: `make loghook` to watch hook events, `make logerr` for errors, `make taillog` for server.log.
- Existing: In REPL/backend, `hook_manager.print_history(<pane_id>)` or `hook_manager.get_history(<pane_id>)` for recent transitions; `hook_manager.print_all_states()` to see tracked panes.

## Configuration

Edit `src/termsupervisor/config.py`:

```python
import os

# === Polling / Debug ===
POLL_INTERVAL = 1.0
EXCLUDE_NAMES = ["supervisor"]
DEBUG = True

# === User label ===
USER_NAME_VAR = "user.name"

# === Cleaner ===
CLEANER_MIN_CHANGED_LINES = 3
CLEANER_SIMILARITY_THRESHOLD = 0.9
CLEANER_DEBOUNCE_SECONDS = 5.0

# === Screen sampling ===
SCREEN_LAST_N_LINES = 30
MIN_CHANGED_LINES = 5

# === Actor queue ===
QUEUE_MAX_SIZE = 256
QUEUE_HIGH_WATERMARK = 0.75

# === Timer ===
TIMER_TICK_INTERVAL = 1.0

# === State / Display ===
LONG_RUNNING_THRESHOLD_SECONDS = 60.0
STATE_HISTORY_MAX_LENGTH = 30
DISPLAY_DELAY_SECONDS = 5.0
NOTIFICATION_MIN_DURATION_SECONDS = 3.0
FOCUS_DEBOUNCE_SECONDS = 2.0

# === PaneChangeQueue ===
QUEUE_REFRESH_LINES = 5
QUEUE_NEW_RECORD_LINES = 20
QUEUE_FLUSH_TIMEOUT = 10.0

# === Logging / Metrics ===
LOG_LEVEL = os.environ.get("TERMSUPERVISOR_LOG_LEVEL", "INFO")
LOG_MAX_CMD_LEN = 120
MASK_COMMANDS = False
METRICS_ENABLED = True
```

## Claude Code Integration

1. Copy `hooks/claude-code/settings.json` to Claude Code hooks directory
2. Events sent to `POST /api/hook`:
   - `SessionStart`, `SessionEnd`
   - `PreToolUse`, `PostToolUse`, `SubagentStop`
   - `Stop` (task complete)
   - `Notification:permission_prompt`, `Notification:idle_prompt`

See `hooks/claude-code/README.md` for details.

## Makefile Commands

| Command | Description |
|---------|-------------|
| `make run` | Start in background |
| `make stop` | Stop server |
| `make rerun` | Restart (stop + run) |
| `make viewlog` | View full log |
| `make taillog` | Follow log |
| `make loghook` | Monitor hook events |
| `make logerr` | Monitor errors |
| `make debug-states` | List all pane debug snapshots |
| `make debug-state ID=<pane_id>` | View single pane state/queue details |
| `make test` | Run pytest |
| `make clean` | Clean logs and cache |

## Development

```bash
make test         # Run tests
make loghook      # Monitor events while developing
```
