# TermSupervisor

Monitor iTerm2 pane content changes with a real-time web dashboard.

## Features

- **Real-time Web Dashboard**: Visualizes your entire iTerm2 environment.
- **Unified Layout**: Displays all Windows and Tabs simultaneously in a responsive grid (4 tabs per row), removing the need for manual switching.
- **Accurate Pane Mirroring**: Panes within each tab are rendered with relative positioning and aspect ratios matching the actual terminal layout.
- **Content Change Detection**: Periodically scans all panes for content changes using diffs (added/removed lines).
- **Visual Notifications**: Panes flash green when content updates are detected.
- **Interactive**: Click on any pane in the dashboard to activate that specific session in iTerm2.
- **Configurable**: Filter panes by name, adjust scan intervals, and set change thresholds.

## Architecture

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

- **TermSupervisor**: Core service that monitors iTerm2 panes, detects content changes
- **WebServer**: FastAPI server with WebSocket, serves the dashboard and broadcasts updates

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

### Demo (Interactive)

```bash
uv run termsupervisor-demo
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
INTERVAL = 5.0           # Monitor interval (seconds)
EXCLUDE_NAMES = ["supervisor"]  # Excluded pane names (substring match)
MIN_CHANGED_LINES = 3    # Minimum changed lines to trigger notification
DEBUG = True             # Debug mode (print change details)
```

## Web Dashboard Features

- **Window Groups**: Windows act as containers for their tabs.
- **Tiled Tab View**: Tabs are tiled horizontally (flex-wrap) to provide a "bird's-eye view" of all running contexts.
- **Overlap Detection**: Semi-transparent pane styling helps identify any layout anomalies.
- **Detailed Tooltips**: Hover over a pane to see its session ID, index, and precise coordinate calculations.
- **Auto-reconnect**: WebSocket reconnects automatically if the server is restarted.

## Development

```bash
# Run tests
uv run pytest

# Or via make
make test
```