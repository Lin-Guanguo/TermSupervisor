# TermSupervisor

TermSupervisor monitors iTerm2 pane content and mirrors the layout on a real-time web dashboard.

## Project Overview

- **Core:** iTerm2 layout mirror with per-pane state pipeline; content changes filtered by ContentCleaner + PaneChangeQueue throttling.
- **Architecture:** HookManager → StateManager (per-pane ActorQueue + display layer) → PaneStateMachine; layout/SVG rendered to a vanilla HTML/JS WebSocket dashboard. Event System (state events) and Render Pipeline (content polling) are independent.
- **Hooks/UI:** Shell PromptMonitor, Claude Code HTTP hook, iTerm FocusMonitor (0.3s debounce); frontend actions are JSON (`activate/rename/create_tab`, tabs-per-row & hidden-tab controls).
- **Docs:** `docs/state-architecture.md`; design source `mnema/state-architecture/`; hook notes `docs/hook-manager-refactor.md`.

## Building and Running

Prereqs: Enable iTerm2 Python API; Python 3.12+ via uv.

| Command | Description |
| --- | --- |
| `make run` | Start the web server in background (logs to `server.log`). |
| `make stop` | Stop the background web server. |
| `make rerun` | Restart the background web server. |
| `make loghook` | Monitor hook events in real-time. |
| `make logerr` | Monitor errors in real-time. |
| `make viewlog` | View `server.log`. |
| `make taillog` | Follow log. |
| `make test` | Run pytest. |
| `make debug-states` | List all pane debug snapshots. |
| `make debug-state ID=<pane_id>` | View single pane state/queue details. |
| `uv sync` | Install deps. |

Dashboard: http://localhost:8765

## Project Structure

```
src/termsupervisor/
├── config.py               # Configuration constants
├── telemetry.py            # Logger + in-memory metrics facade
├── core/
│   └── ids.py              # ID normalization utilities
├── state/                  # State architecture
│   ├── manager.py          # StateManager (ActorQueue + display layer)
│   ├── state_machine.py    # Transition processing + history/state_id
│   ├── transitions.py      # Rule table
│   ├── queue.py            # ActorQueue with generation/backpressure
│   ├── predicates.py       # Transition predicates (exit code checks)
│   └── types.py            # Data types (HookEvent, DisplayState, TaskStatus, etc.)
├── hooks/
│   ├── manager.py          # HookManager facade (Event System entry)
│   ├── receiver.py         # HTTP /api/hook
│   ├── prompt_monitor.py   # iTerm2 PromptMonitor wrapper
│   └── sources/            # Shell, Claude Code, iTerm focus debounce
├── adapters/               # Terminal data structures
│   └── iterm2/             # iTerm2 integration
│       ├── client.py       # iTerm2Client
│       ├── layout.py       # Layout traversal
│       ├── models.py       # Layout DTOs
│       └── naming.py       # Naming utilities
├── analysis/               # Content processing
│   ├── content_cleaner.py  # Unicode filter + hash
│   └── change_queue.py     # PaneChangeQueue throttling
├── render/                 # SVG renderer
├── runtime/
│   └── bootstrap.py        # Component construction
├── web/                    # FastAPI + WebSocket handlers
│   └── app.py              # Entry point
└── templates/index.html    # Frontend dashboard
```

## Key Files

- `src/termsupervisor/runtime/bootstrap.py`: centralized component construction (HookManager, Sources, Receiver).
- `src/termsupervisor/hooks/manager.py`: `emit_event()` unified entry, enqueue → StateManager, user/focus/click helpers.
- `src/termsupervisor/state/manager.py`: StateManager (per-pane ActorQueue + display layer).
- `src/termsupervisor/state/state_machine.py`: transition processing/history/state_id; predicates in `state/predicates.py`.
- `src/termsupervisor/adapters/iterm2/models.py`: Layout DTOs (LayoutData, WindowInfo, TabInfo, PaneInfo, PaneSnapshot).
- `src/termsupervisor/adapters/iterm2/client.py`: iTerm2Client for API interactions.
- `src/termsupervisor/analysis/change_queue.py`: Content throttle DTOs (PaneChangeQueue, ChangeRecord, PaneChange, PaneHistory).
- `docs/state-architecture.md`: current architecture summary.

## State Machine

5 states with source isolation (no SOURCE_PRIORITY; from_source rules only):

| State | Trigger Events | Color | Visual |
|-------|---------------|-------|--------|
| IDLE | `idle_prompt`, `SessionEnd`, focus/click | - | Hidden |
| RUNNING | `command_start`, `PreToolUse`, `SessionStart` | Blue | Rotating border |
| WAITING_APPROVAL | `Notification:permission_prompt` | Yellow | Blinking |
| DONE | `command_end`(exit=0), `Stop` | Green | Blinking |
| FAILED | `command_end`(exit≠0) | Red | Blinking |

Rule table excerpt (see `state/transitions.py`):

| # | from_status | from_source | signal | to_status | to_source | 描述 | reset_started_at | 备注 |
|---|-------------|-------------|--------|-----------|-----------|------|------------------|------|
| S1 | * | * | shell.command_start | RUNNING | shell | 执行: {command:30} | Y | |
| S2 | RUNNING | shell | shell.command_end(exit=0) | DONE | shell | 命令完成 | N | 保留 started_at |
| S3 | RUNNING | shell | shell.command_end(exit≠0) | FAILED | shell | 失败 (exit={exit_code}) | N | |
| C1 | * | * | claude-code.SessionStart | RUNNING | claude-code | 会话开始 | Y | |
| C2 | * | * | claude-code.PreToolUse | RUNNING | claude-code | 工具: {tool_name:30} | same-source: N / else: Y | |
| C3 | RUNNING | claude-code | claude-code.Stop | DONE | claude-code | 已完成回复 | N | |
| C4 | * | * | claude-code.Notification:permission_prompt | WAITING_APPROVAL | claude-code | 需要权限确认 | N | |
| C5 | * | * | claude-code.Notification:idle_prompt | IDLE | claude-code |  | Y | |
| C6 | * | * | claude-code.SessionEnd | IDLE | claude-code |  | Y | |
| U1 | WAITING_APPROVAL | * | iterm.focus / frontend.click_pane | IDLE | user |  | Y | 立即流转 |
| U2 | DONE \| FAILED | * | iterm.focus / frontend.click_pane | IDLE | user |  | Y | 立即流转 |

Signal format: `{source}.{event_type}` (e.g., `shell.command_start`, `claude-code.Stop`)

## Content Change Detection (Render Pipeline)

```
1s Polling → ContentCleaner → PaneChangeQueue → SVG Refresh → WebSocket
                  │                  │
                  │                  ├── Refresh: ≥5 lines or 10s timeout
                  │                  └── Queue push: ≥20 lines
                  │
                  └── Unicode whitelist (filters ANSI, spinners, punctuation)
```

Content changes are handled by the Render Pipeline only (independent from Event System state transitions).

## Development Conventions

- Structure: code in `src/termsupervisor/`, tests in `tests/`.
- Configuration: `src/termsupervisor/config.py`.
- Type hints throughout; pytest for tests (`make test`).
- Debugging: `make loghook` to monitor hook events in real time.

## Current Status Notes

- runtime/bootstrap builds the HookManager + Sources stack; per-pane ActorQueue + generation gating are active.
- **Event System** (HookManager → StateManager) handles state events only; **Render Pipeline** handles content polling independently.
- WebSocket handler is JSON-only (`activate/rename/create_tab`); status changes broadcast from HookManager.
- `adapters/iterm2/` provides iTerm2 integration (client, layout, models, naming).
- State is in-memory only; restart resets all state/history.
- Telemetry metrics are in-memory only; no Prometheus/StatsD sink yet.
