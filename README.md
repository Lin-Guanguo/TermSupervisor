# TermSupervisor

Monitor iTerm2 pane content changes with a real-time web dashboard.

![TermSupervisor + iTerm2](docs/image.jpg)
*Left: iTerm2 with multiple panes | Right: TermSupervisor dashboard mirroring the layout in real-time*

## Features

- **Real-time Web Dashboard**: Visualizes your entire iTerm2 environment with SVG terminal rendering.
- **Unified Layout**: Displays all windows/tabs in a responsive grid (1-6 tabs per row).
- **Content Change Detection**: 1s polling + ContentCleaner + PaneChangeQueue throttling; emits `content.changed` for WAITING→RUNNING fallback.
- **State Pipeline**: HookManager → StateManager (per-pane ActorQueue) → PaneStateMachine (rules/history) → Pane display (delay + notification suppression) with Timer for LONG_RUNNING + delayed clears.
- **Visual Notifications**: Bottom floating panel with status-based colors; active pane highlight.
- **Interactive**: Click to activate pane, right-click to rename/hide.

## Architecture

```
Signal Sources (shell | claude-code | iterm focus | timer | content.changed)
        │
        ▼
┌──────────────────────────┐
│       HookManager        │ normalize generation/time, enqueue
└───────────┬──────────────┘
            ▼
┌──────────────────────────┐
│      StateManager        │ per-pane ActorQueue, LONG_RUNNING tick
└──────┬───────────┬──────┘
       │           │
       ▼           ▼
┌────────────────┐ ┌────────────────┐
│ PaneStateMachine│ │     Pane       │
│ rules/history   │ │ display delay/ │
│ state_id/pred   │ │ notification   │
└────────────────┘ └────────────────┘
            │                │
            └─────Timer──────┘ (interval + delay tasks)
                     │
                     ▼
                WebSocket/UI
```

- Timer (`timer.py`) ticks every 1s to send `timer.check` and drive delayed display tasks.
- Content path: Supervisor polls iTerm2 → ContentCleaner → PaneChangeQueue throttle; on refresh emits `content.changed` to HookManager and updates layout snapshots.
- Hook sources: Shell PromptMonitor, Claude Code HTTP hook, iTerm focus debounce (2s).

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
│   ├── persistence.py      # Versioned checksum save/load (v2)
│   └── predicates.py, types.py
├── hooks/
│   ├── manager.py          # HookManager facade (normalize/enqueue)
│   ├── receiver.py         # HTTP /api/hook endpoint
│   └── sources/            # Shell, Claude Code, iTerm focus debounce, PromptMonitor
│       └── prompt_monitor.py   # iTerm2 PromptMonitor wrapper
├── analysis/               # ContentCleaner + compatibility analyzer
├── iterm/                  # Layout traversal + client helpers
├── render/                 # SVG renderer
├── web/                    # FastAPI + WebSocket handlers
└── templates/index.html    # Frontend (vanilla JS)
```

## Docs

- Current architecture: `docs/state-architecture-current.md`
- Design source: `mnema/state-architecture/`

## Current Status Notes

- New state architecture is live (HookManager + StateManager + PaneStateMachine + Pane + Timer).
- `supervisor.py` still uses PaneChangeQueue/analyzer for content throttle; a dedicated content hook source is still pending.
- Persistence (v2, checksum) is implemented but not invoked; restart resets state/history.
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

## Configuration

Edit `src/termsupervisor/config.py`:

```python
import os
from pathlib import Path

# === Polling ===
POLL_INTERVAL = 1.0                    # seconds

# === PaneChangeQueue ===
QUEUE_REFRESH_LINES = 5                # SVG refresh threshold
QUEUE_NEW_RECORD_LINES = 20            # Queue push threshold
QUEUE_FLUSH_TIMEOUT = 10.0             # Fallback refresh (seconds)
QUEUE_MAX_SIZE = 256
QUEUE_HIGH_WATERMARK = 0.75            # Debug watermark

# === Timer ===
TIMER_TICK_INTERVAL = 1.0              # Timer tick interval (seconds)

# === State Machine / Display ===
LONG_RUNNING_THRESHOLD_SECONDS = 60.0  # RUNNING → LONG_RUNNING
STATE_HISTORY_MAX_LENGTH = 30          # History entries per pane
STATE_HISTORY_PERSIST_LENGTH = 5       # History persisted
DISPLAY_DELAY_SECONDS = 5.0            # DONE/FAILED → IDLE display delay
NOTIFICATION_MIN_DURATION_SECONDS = 3.0  # Suppress short-task notifications

# === Focus ===
FOCUS_DEBOUNCE_SECONDS = 2.0           # iTerm focus debounce

# === Persistence ===
PERSIST_FILE = Path(os.path.expanduser("~/.termsupervisor/state.json"))
PERSIST_VERSION = 2
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
| `make test` | Run pytest |
| `make clean` | Clean logs and cache |

## Development

```bash
make test         # Run tests
make loghook      # Monitor events while developing
```
