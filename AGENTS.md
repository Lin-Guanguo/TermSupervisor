# TermSupervisor

TermSupervisor monitors iTerm2 pane content and mirrors the layout on a real-time web dashboard.

## Project Overview

- **Core:** iTerm2 layout mirror with per-pane state pipeline; content changes filtered by ContentCleaner + PaneChangeQueue throttling.
- **Architecture:** HookManager → StateManager (per-pane ActorQueue) → PaneStateMachine → Pane display (delay + notification suppression) with Timer handling LONG_RUNNING + delayed clears; layout/SVG rendered to a vanilla HTML/JS WebSocket dashboard.
- **Hooks/UI:** Shell PromptMonitor, Claude Code HTTP hook, iTerm FocusMonitor (2s debounce); `content.update` comes from polling; frontend actions are JSON (`activate/rename/create_tab`, tabs-per-row & hidden-tab controls).
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
| `uv sync` | Install deps. |

Dashboard: http://localhost:8765

## Project Structure

```
src/termsupervisor/
├── config.py               # Configuration constants
├── telemetry.py            # Logger + in-memory metrics facade
├── timer.py                # Interval/delay scheduler (LONG_RUNNING + display delay)
├── supervisor.py           # 1s polling + content.update emission + layout mirror
├── runtime/                # Bootstrap + lifecycle
│   └── bootstrap.py        # Centralized component construction (Timer, HookManager, Sources)
├── pane/                   # State architecture
│   ├── manager.py          # Coordination + per-pane ActorQueue + LONG_RUNNING
│   ├── state_machine.py    # Transition processing + history/state_id
│   ├── transitions.py      # Rule table (WAITING→RUNNING fallback, etc.)
│   ├── pane.py             # Display layer (delay, notification suppression)
│   ├── queue.py            # ActorQueue with generation/backpressure
│   ├── persistence.py      # Versioned checksum save/load (v2)
│   ├── predicates.py
│   └── types.py
├── hooks/
│   ├── manager.py          # HookManager facade (emit_event unified entry)
│   ├── receiver.py         # HTTP /api/hook
│   └── sources/            # Shell, Claude Code, iTerm focus debounce, PromptMonitor
│       └── prompt_monitor.py   # iTerm2 PromptMonitor wrapper
├── analysis/               # ContentCleaner + change_queue (throttle DTOs)
│   ├── change_queue.py     # PaneChangeQueue, PaneHistory, PaneChange, ChangeRecord
│   ├── cleaner.py          # ChangeCleaner (debounce/similarity filter)
│   └── content_cleaner.py  # Unicode filter + hash
├── iterm/                  # Layout traversal + client + models
│   ├── models.py           # Layout DTOs (LayoutData, WindowInfo, TabInfo, PaneInfo, PaneSnapshot)
│   └── ...
├── render/                 # SVG renderer
├── web/                    # FastAPI + WebSocket handlers
│   └── app.py              # Entry point (uses runtime.bootstrap)
└── templates/index.html    # Frontend dashboard
```

## Key Files

- `src/termsupervisor/runtime/bootstrap.py`: centralized component construction (Timer, HookManager, Sources, Receiver).
- `src/termsupervisor/hooks/manager.py`: `emit_event()` unified entry, enqueue → StateManager, user/focus/click helpers.
- `src/termsupervisor/pane/manager.py`: per-pane ActorQueue, LONG_RUNNING tick, content.update fallback, display callback.
- `src/termsupervisor/pane/state_machine.py`: transition processing/history/state_id; predicates in `pane/predicates.py`.
- `src/termsupervisor/pane/pane.py`: DONE/FAILED→IDLE delayed 5s, notification suppression (<3s or focused), content hash broadcast.
- `src/termsupervisor/timer.py`: interval + delay scheduler (async/sync), `timer.errors` metric.
- `src/termsupervisor/supervisor.py`: layout mirror, PaneChangeQueue-based throttle, emits `content.update` to HookManager.
- `src/termsupervisor/iterm/models.py`: Layout DTOs (LayoutData, WindowInfo, TabInfo, PaneInfo, PaneSnapshot).
- `src/termsupervisor/analysis/change_queue.py`: Content throttle DTOs (PaneChangeQueue, ChangeRecord, PaneChange, PaneHistory).
- `docs/state-architecture.md`: current architecture summary.

## State Machine

6 states with source isolation (no SOURCE_PRIORITY; from_source rules only):

| State | Trigger Events | Color | Visual |
|-------|---------------|-------|--------|
| IDLE | `idle_prompt`, `SessionEnd`, focus/click | - | Hidden |
| RUNNING | `command_start`, `PreToolUse`, `SessionStart` | Blue | Rotating border |
| LONG_RUNNING | RUNNING > 60s | Dark blue | Rotating border |
| WAITING_APPROVAL | `Notification:permission_prompt` | Yellow | Blinking |
| DONE | `command_end`(exit=0), `Stop` | Green | Blinking |
| FAILED | `command_end`(exit≠0) | Red | Blinking |

Rule table excerpt (see `pane/transitions.py`):

| # | from_status | from_source | signal | to_status | to_source | 描述 | reset_started_at | 备注 |
|---|-------------|-------------|--------|-----------|-----------|------|------------------|------|
| S1 | * | * | shell.command_start | RUNNING | shell | 执行: {command:30} | Y | |
| S2 | RUNNING \| LONG_RUNNING | shell | shell.command_end(exit=0) | DONE | shell | 命令完成 | N | 保留 started_at |
| S3 | RUNNING \| LONG_RUNNING | shell | shell.command_end(exit≠0) | FAILED | shell | 失败 (exit={exit_code}) | N | |
| C1 | * | * | claude-code.SessionStart | RUNNING | claude-code | 会话开始 | Y | |
| C2 | * | * | claude-code.PreToolUse | RUNNING | claude-code | 工具: {tool_name:30} | same-source: N / else: Y | |
| C3 | RUNNING \| LONG_RUNNING | claude-code | claude-code.Stop | DONE | claude-code | 已完成回复 | N | |
| C4 | * | * | claude-code.Notification:permission_prompt | WAITING_APPROVAL | claude-code | 需要权限确认 | N | |
| C5 | * | * | claude-code.Notification:idle_prompt | IDLE | claude-code |  | Y | |
| C6 | * | * | claude-code.SessionEnd | IDLE | claude-code |  | Y | |
| T1 | RUNNING | = | timer.check | LONG_RUNNING | = | 已运行 {elapsed} | N | StateManager 发出 |
| U1 | WAITING_APPROVAL | * | iterm.focus / frontend.click_pane | IDLE | user |  | Y | 立即流转 |
| U2 | DONE \| FAILED | * | iterm.focus / frontend.click_pane | IDLE | user |  | Y | 立即流转，显示延迟 |
| R1 | WAITING_APPROVAL | * | content.update | RUNNING | = | 内容变化，恢复执行 | N | 始终渲染 Pane |
| T2 | WAITING_APPROVAL | * | timer.waiting_fallback_running | RUNNING | = | 超时恢复（有内容变化） | N | WAITING 超时 fallback |
| T3 | WAITING_APPROVAL | * | timer.waiting_fallback_idle | IDLE | = | 超时恢复（无内容变化） | Y | WAITING 超时 fallback |

Signal format: `{source}.{event_type}` (e.g., `shell.command_start`, `claude-code.Stop`)

## Content Change Detection

```
1s Polling → ContentCleaner → PaneChangeQueue → SVG Refresh + content.update → HookManager
                  │                  │
                  │                  ├── Refresh: ≥5 lines or 10s timeout
                  │                  └── Queue push: ≥20 lines
                  │
                  └── Unicode whitelist (filters ANSI, spinners, punctuation)
```

## Development Conventions

- Structure: code in `src/termsupervisor/`, tests in `tests/`.
- Configuration: `src/termsupervisor/config.py`.
- Type hints throughout; pytest for tests (`make test`).
- Debugging: `make loghook` to monitor hook events in real time.

## Current Status Notes

- runtime/bootstrap builds the single Timer + HookManager + Sources stack; per-pane ActorQueue + generation gating are active.
- WebSocket handler is JSON-only (`activate/rename/create_tab`); status changes broadcast from HookManager callback.
- `supervisor.py` still uses PaneChangeQueue for content throttle; a dedicated content hook source is still pending.
- Persistence (v2, checksum) is implemented but not auto-wired; restart resets state/history unless save/load is called.
- Telemetry metrics are in-memory only; no Prometheus/StatsD sink yet.
