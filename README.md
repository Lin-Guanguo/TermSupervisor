# TermSupervisor

Monitor iTerm2 pane content changes with a real-time web dashboard.

![TermSupervisor + iTerm2](docs/image.jpg)
*Left: iTerm2 with multiple panes | Right: TermSupervisor dashboard mirroring the layout in real-time*

## Features

- **Real-time Web Dashboard**: Visualizes your entire iTerm2 environment with SVG terminal rendering
- **Unified Layout**: Displays all Windows and Tabs in a responsive grid (1-6 tabs per row)
- **Content Change Detection**: 1s polling with smart throttling via PaneChangeQueue
- **State Machine**: 6 states driven by Shell PromptMonitor + Claude Code HTTP hooks
- **Visual Notifications**: Bottom floating notification panel with status-based colors
- **Active Pane Highlight**: Orange border for currently focused pane
- **Interactive**: Click to activate pane, right-click to rename/hide

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Signal Sources                               │
├─────────────┬─────────────┬─────────────┬─────────────┬─────────────┤
│    Shell    │ Claude Code │   Render    │    iTerm    │  Frontend   │
│PromptMonitor│  HTTP Hook  │ PaneQueue   │FocusMonitor │  WebSocket  │
└──────┬──────┴──────┬──────┴──────┬──────┴──────┬──────┴──────┬──────┘
       │             │             │             │             │
       └─────────────┴─────────────┴─────────────┴─────────────┘
                                   │
                                   ▼
                        ┌─────────────────────┐
                        │     HookEvent       │
                        │  source.event_type  │
                        └──────────┬──────────┘
                                   │
                                   ▼
                        ┌─────────────────────┐
                        │   EventProcessor    │
                        │   + StateMachine    │
                        └──────────┬──────────┘
                                   │
                                   ▼
                        ┌─────────────────────┐
                        │     StateStore      │
                        │  + WebSocket Broadcast
                        └─────────────────────┘
```

### State Machine

6 states with source priority (claude-code:10 > shell:1 > timer:0):

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
1s Polling → ContentCleaner → PaneChangeQueue → SVG Refresh
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
├── models.py           # PaneInfo, ChangeRecord, PaneChangeQueue
├── config.py           # All configuration constants
├── supervisor.py       # 1s polling loop with PaneChangeQueue
├── iterm/
│   ├── client.py       # iTerm2 API (activate, rename)
│   └── layout.py       # Layout traversal
├── web/
│   ├── app.py          # FastAPI startup, Hook system init
│   ├── server.py       # WebSocket server
│   └── handlers.py     # activate, rename, click handlers
├── analysis/
│   ├── base.py         # TaskStatus enum (6 states)
│   ├── content_cleaner.py  # Unicode whitelist filter
│   └── cleaner.py      # ChangeCleaner (debounce)
├── hooks/
│   ├── manager.py      # HookManager facade
│   ├── event_processor.py  # HookEvent → StateMachine
│   ├── state_machine.py    # Transition rules
│   ├── state_store.py      # State persistence + callbacks
│   ├── state.py            # PaneState, StateHistoryEntry
│   ├── receiver.py     # HTTP /api/hook endpoint
│   ├── prompt_monitor.py   # iTerm2 PromptMonitor wrapper
│   └── sources/
│       ├── shell.py        # command_start, command_end
│       ├── claude_code.py  # PreToolUse, Stop, etc.
│       └── iterm.py        # focus (2s debounce)
└── templates/
    └── index.html      # Frontend (vanilla JS)
```

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
# === Polling ===
POLL_INTERVAL = 1.0                    # seconds

# === PaneChangeQueue ===
QUEUE_REFRESH_LINES = 5                # SVG refresh threshold
QUEUE_NEW_RECORD_LINES = 20            # Queue push threshold
QUEUE_FLUSH_TIMEOUT = 10.0             # Fallback refresh (seconds)
QUEUE_MAX_SIZE = 20

# === State Machine ===
LONG_RUNNING_THRESHOLD_SECONDS = 60.0  # RUNNING → LONG_RUNNING
STATE_HISTORY_MAX_LENGTH = 30          # History entries per pane

# === Focus ===
FOCUS_DEBOUNCE_SECONDS = 2.0           # iTerm focus debounce

# === Source Priority ===
SOURCE_PRIORITY = {
    "claude-code": 10,
    "gemini": 10,
    "codex": 10,
    "shell": 1,
    "render": 1,
    "timer": 0,
}
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
