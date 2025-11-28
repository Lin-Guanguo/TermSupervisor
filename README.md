# TermSupervisor

Monitor iTerm2 pane content changes with a real-time web dashboard.

## Features

- **Real-time Web Dashboard**: Visualizes your entire iTerm2 environment.
- **Unified Layout**: Displays all Windows and Tabs simultaneously in a responsive grid (4 tabs per row).
- **Accurate Pane Mirroring**: Panes within each tab are rendered with relative positioning and aspect ratios matching the actual terminal layout.
- **Content Change Detection**: Periodically scans all panes for content changes using diffs.
- **Status Analysis**: LLM-based analysis detects task states (running, waiting approval, completed, failed, etc.).
- **Visual Notifications**: Panes flash green when content updates are detected, with status-based color coding.
- **Active Pane Highlight**: Currently focused pane is visually highlighted.
- **Interactive**: Click on any pane to activate that session in iTerm2.
- **Right-click Rename**: Rename Windows, Tabs, and Sessions directly from the dashboard.
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
│   ├── llm.py          # LLM-based status analyzer
│   └── rule_based.py   # Rule-based status analyzer
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
ANALYZER_TYPE = "llm"              # "llm" (default) | "rule"
LLM_MODEL = "google/gemini-2.0-flash"
LLM_TIMEOUT = 15.0
```

## Web Dashboard Features

- **Window Groups**: Windows act as containers for their tabs.
- **Tiled Tab View**: Tabs are tiled horizontally (flex-wrap) for a "bird's-eye view".
- **Right-click Menu**: Rename Windows, Tabs, or Sessions directly.
- **Click to Activate**: Click any pane to switch to that iTerm2 session.
- **Visual Updates**: Panes flash green when content changes.
- **Auto-reconnect**: WebSocket reconnects automatically if the server restarts.

## Development

```bash
# Run tests
uv run pytest

# Or via make
make test
```
