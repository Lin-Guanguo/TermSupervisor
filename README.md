# TermSupervisor

Monitor iTerm2 pane content changes with a real-time web dashboard.

## Features

- **Real-time Web Dashboard**: Visualizes your entire iTerm2 environment with SVG terminal rendering.
- **Unified Layout**: Displays all Windows and Tabs in a responsive grid (configurable 1-6 tabs per row).
- **Accurate Pane Mirroring**: Panes rendered with relative positioning and aspect ratios matching the actual terminal layout.
- **Content Change Detection**: Periodically scans all panes for content changes using diffs.
- **Status Analysis**: Hook-based (recommended), rule-based, or LLM-based analysis detects task states (idle, running, thinking, waiting approval, completed, failed, interrupted).
- **Visual Notifications**: Bottom floating notification panel with status-based color coding.
- **Active Pane Highlight**: Currently focused pane is visually highlighted with orange border.
- **Interactive**: Click on any pane to activate that session in iTerm2.
- **Right-click Menu**: Rename Windows, Tabs, and Sessions; hide/show Tabs.
- **Tab Management**: Hide tabs to reduce clutter, restore from dropdown in window title.
- **Configurable**: Filter panes by name, adjust scan intervals, and set change thresholds.

## Architecture

```
src/termsupervisor/
├── models.py           # Data models (PaneInfo, TabInfo, WindowInfo, LayoutData, PaneHistory)
├── config.py           # Configuration constants
├── supervisor.py       # Monitor service (change detection, polling loop)
├── iterm/
│   ├── client.py       # iTerm2 API operations (activate, rename)
│   └── layout.py       # Layout traversal (get window/tab/pane structure)
├── web/
│   ├── app.py          # Application startup
│   ├── server.py       # WebSocket server
│   └── handlers.py     # Message handlers (activate, rename)
├── analysis/
│   ├── base.py         # StatusAnalyzer base class, TaskStatus enum
│   ├── cleaner.py      # ChangeCleaner (debounce, similarity filtering)
│   ├── hook.py         # Hook-based status analyzer (recommended)
│   ├── llm.py          # LLM-based status analyzer
│   └── rule_based.py   # Rule-based status analyzer
├── hooks/
│   ├── manager.py      # HookManager (multi-layer status management)
│   ├── receiver.py     # HTTP API receiver (/api/hook)
│   ├── prompt_monitor.py  # iTerm2 PromptMonitor wrapper
│   └── sources/        # Hook sources (shell, claude_code)
└── templates/
    └── index.html      # Frontend dashboard
```

```
┌─────────────────┐     callback      ┌─────────────────┐
│  TermSupervisor │ ───────────────▶  │    WebServer    │
│   (supervisor)  │                   │  (FastAPI+WS)   │
└────────┬────────┘                   └────────┬────────┘
         │                                     │
         │ iTerm2 API                          │ WebSocket
         ▼                                     ▼
┌─────────────────┐                   ┌─────────────────┐
│     iTerm2      │                   │     Browser     │
│  (pane content) │                   │   (dashboard)   │
└─────────────────┘                   └─────────────────┘
```

## Install

```bash
uv sync
```

## Usage

**Prerequisite:** Enable Python API in iTerm2
- iTerm2 -> Settings -> General -> Magic -> Enable Python API

### Web Dashboard (Recommended)

```bash
# Background mode
make run

# View logs
make viewlog

# Stop server
make stop

# Restart
make rerun
```

Then open http://localhost:8765

### CLI Monitor

```bash
uv run termsupervisor
```

## Makefile Commands

| Command | Description |
|---------|-------------|
| `make run` | Start web server in background |
| `make stop` | Stop background server |
| `make rerun` | Restart server (stop + run) |
| `make viewlog` | View complete log file |
| `make taillog` | Follow log in real-time |
| `make run-web` | Run web server in foreground |
| `make run-cli` | Run CLI monitor |
| `make test` | Run tests |
| `make clean` | Clean logs and cache |

## Configuration

Edit `src/termsupervisor/config.py`:

```python
# Monitor settings
INTERVAL = 3.0                     # Monitor interval (seconds)
LONG_RUNNING_THRESHOLD = 15.0      # Long-running task threshold (seconds)
EXCLUDE_NAMES = ["supervisor"]     # Excluded pane names (substring match)
MIN_CHANGED_LINES = 5              # Minimum changed lines to trigger notification
DEBUG = True                       # Debug mode (print change details)
USER_NAME_VAR = "user.name"        # Variable name for custom names

# Status analysis settings
ANALYZER_TYPE = "hook"             # "hook" (recommended) | "llm" | "rule"
LLM_MODEL = "google/gemini-2.0-flash"
LLM_TIMEOUT = 15.0
```

### Hook-based Status Analysis (Recommended)

The hook analyzer receives status updates from external tools via HTTP API. To integrate with Claude Code:

1. Copy `hooks/claude-code/settings.json` to your Claude Code hooks directory
2. The hook will send status updates to `http://localhost:8765/api/hook` on events like:
   - Tool execution start/stop
   - User prompt submissions
   - Task completions

See `hooks/claude-code/README.md` for setup details.

## Web Dashboard Features

- **Window Groups**: Windows act as containers for their tabs.
- **Tiled Tab View**: Tabs tiled horizontally (configurable 1-6 per row) for a "bird's-eye view".
- **SVG Terminal Rendering**: Panes display actual terminal content as SVG images.
- **Right-click Menu**: Rename Windows, Tabs, or Sessions; hide Tabs.
- **Tab Hide/Show**: Hide tabs via right-click menu, restore from dropdown button in window title.
- **Click to Activate**: Click any pane to switch to that iTerm2 session.
- **Notification Panel**: Bottom floating panel shows status changes (click to focus pane, delete individual notifications).
- **Visual Updates**: Panes flash green on content changes, status-based color coding (purple=thinking, yellow=waiting approval, green=completed, red=failed).
- **Auto-reconnect**: WebSocket reconnects automatically if the server restarts.
- **Persistent Settings**: Tab visibility, tabs per row, and panel state saved to localStorage.

## Development

```bash
# Run tests
uv run pytest

# Or via make
make test
```
