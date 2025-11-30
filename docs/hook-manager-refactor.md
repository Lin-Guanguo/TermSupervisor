# HookManager event handling refactor plan

Context: `HookManager` currently owns source-specific helpers (e.g., `process_shell_command_start`) and logging. We want Manager to stay generic (normalize + enqueue) and move per-source translation/sanitization into sources.

## Principles
- Manager: normalize event (generation/timestamp/signal) + enqueue + optional generic logging hook only; no source-specific branching.
- Sources: own mapping, sanitization, and logging decisions; emit already-normalized event types.
- API stability: keep thin compatibility wrappers during the transition; mark for removal after sources are migrated and tests updated.
- Logging hygiene: sanitize/limit payloads (esp. shell commands) at the source; Manager should not log raw payloads by default.
- Construction: avoid DI frameworks; use explicit bootstrap wiring for clarity of ownership/order.

## Proposed changes
1) Manager API
   - Add `emit_event(source, pane_id, event_type, data=None, *, log=True, log_level=INFO)` that calls `_normalize_event` + `process_event`; central place for optional logging/metrics.
   - Keep existing `process_shell_command_start/end`, `process_claude_code_event`, etc. as thin wrappers that delegate to `emit_event`; annotate as transitional.
2) Shell source
   - Sanitize command before logging: strip NUL/newlines, collapse whitespace, truncate (e.g., 120 chars).
   - Log sanitized summary only; carry sanitized command in `data["command"]`. Optionally allow a `mask_commands` flag to drop payload entirely.
   - Emit via `emit_event("shell", pane_id, "command_start", {...})` / `"command_end"`.
3) Claude source
   - Keep event-name normalization (`pre_tool` → `PreToolUse`, etc.) inside the source, then `emit_event("claude-code", ...)`.
   - Clamp payload size; avoid logging large `tool_input` blobs by default.
4) Other sources
   - Content: call `emit_event("content", "changed", {...})` with logging disabled.
   - Iterm/frontend: use `emit_event("iterm", "focus")`, `emit_event("frontend", "click_pane")`.
   - Timer: `emit_event("timer", "check", {...})`.
5) Telemetry
   - Optionally add a lightweight counter in `emit_event` (e.g., `metrics.inc("hooks.events", tags={source, event_type})`), controlled via config if needed.
6) Deprecation cleanup
   - After sources/tests/docs migrate, remove source-specific Manager methods or keep them as shims marked deprecated with a planned removal version.
7) Receiver ownership
   - HookManager should own the HTTP receiver lifecycle; provide `ensure_receiver()/get_receiver()` and `register_adapter(adapter)` that delegates to the receiver.
   - Web layer simply mounts `hook_manager.get_receiver()`; adapter registration happens via HookManager, not in web/app initialization.
8) WebSocket message format
   - Current WebSocket handler has mixed formats (`"activate:<id>"` prefix vs JSON actions). Normalize to JSON (e.g., `{"action": "activate", "session_id": ...}`) and phase out prefix handling after frontend migration.
   - Frontend sends JSON for activate/rename/create; backend removes string-prefix branch once the frontend is updated.
9) Callback reduction
   - Prefer explicit ownership over runtime setter callbacks: StateManager should own Pane/StateMachine and call their methods directly (no `set_on_state_change`/`set_on_display_change` setters).
   - StateMachine.process returns state change; StateManager calls Pane.handle_state_change and then directly notifies HookManager (or returns a DisplayState) — only one outward callback remains (`HookManager.set_change_callback` for Web).
   - PromptMonitor integration stays in the shell source; Timer retains its scheduling callbacks (not part of the state/display chain).
10) Runtime/bootstrap ownership
   - Move HookManager/Timer singleton creation out of `analysis/__init__.py` into a dedicated runtime/bootstrap module (e.g., `runtime.py` or `bootstrap.py`).
   - Keep `analysis` focused on cleaning/analysis utilities; drop the legacy `create_analyzer` shim once callers migrate.
   - Update callers (`web/app.py`, `supervisor.py`, docs) to import HookManager/Timer from the new module.
11) models.py split
    - Move layout DTOs (`LayoutData`, `WindowInfo`, `TabInfo`, `PaneInfo`, `PaneSnapshot`, `UpdateCallback`) to `iterm/models.py` (or similar) to align with layout traversal.
    - Move content change/throttle types (`PaneChangeQueue`, `ChangeRecord`, `PaneChange`, `PaneHistory`) to `analysis/change_queue.py` as legacy content analysis/throttle.
    - Update imports in `supervisor.py`, `web/server.py`, `iterm/layout.py`, and docs to reflect the new locations.
12) Bootstrap/initialization split
    - Extract runtime/bootstrap wiring (Timer + HookManager + sources + receiver + WebServer + Supervisor run loop + session sync) into a dedicated module (e.g., `runtime/bootstrap.py`).
    - Keep `supervisor.py` focused on polling/layout mirror/content.changed emission; keep `web/app.py` focused on building the FastAPI/WebSocket app.
    - Provide a single `init_runtime(connection)` helper that returns the constructed components/tasks; `start_server` should delegate to it instead of hand-wiring hooks/sources/receivers/timers directly.

## Migration plan
1. Introduce `emit_event` + wrap existing per-source helpers to delegate (no behavior change).
2. Update shell source to sanitize/log/emit via the generic entry point.
3. Update Claude source to normalize + emit via the generic entry point; clamp logging.
4. Migrate iterm/frontend/content/timer sources to `emit_event`; adjust logging expectations.
5. Update tests to call `emit_event` where appropriate and reflect sanitized logging; refresh docs/diagrams (`AGENTS.md`, `docs/state-architecture.md`, `mnema/*`).
6. Refactor state/display callback chain to explicit calls (StateManager driving Pane/StateMachine without setters); keep only the top-level HookManager change callback for Web.
7. Optionally remove or deprecate legacy helpers once callers are cleaned up.
8. Final pass: layered tests for new wiring/state/display paths; sync docs/diagrams once code changes are done.

## Execution plan & acceptance (staged)
- Phase 0: Baseline
  - Create working branch, run existing tests (if any) to establish baseline. No code changes.
- Phase 1: Manager foundation
  - Add `emit_event`, telemetry hooks, and wrappers. No behavioral change.
  - Acceptance: existing tests still pass; logs unchanged in behavior.
- Phase 2: Source migration
  - Shell: sanitize/log/emit via `emit_event`; optional masking flag. Claude/iterm/frontend/content/timer migrate to `emit_event`.
  - Acceptance: updated unit tests for sources; manual hook path sanity (shell start/end, claude events, focus, content.changed).
- Phase 3: Logging/metrics convention
  - Apply logging format/sanitization and metrics counters; add config switches in `config.py`.
  - Acceptance: sample logs show prefixes/truncation; metrics counters increment in memory.
- Phase 4: State chain simplification
  - Remove setter-based callbacks between StateMachine/Pane/StateManager; drive calls explicitly; keep only HookManager → Web callback.
  - Acceptance: state transition tests pass; no duplicate/ missing state change notifications.
- Phase 5: Runtime/bootstrap & module splits ✓
  - Move HookManager/Timer bootstrap to `runtime/bootstrap.py`; split models (layout → iterm/models.py, queue → analysis/change_queue.py); clean analysis/__init__.py; refactor start_server to use bootstrap; iTerm client consolidation.
  - Done: bootstrap created, models split, supervisor uses ITerm2Client, deprecated singletons removed.
- Phase 6: WebSocket format unification ✓
  - Frontend/backend switch to JSON actions for activate/rename/create; remove string-prefix handler.
  - Done: legacy `activate:xxx` format removed, JSON-only handler.
- Phase 7: Cleanup & docs/tests ✓
  - Remove legacy APIs/shims (create_analyzer, old process_* if unused), delete obsolete fixtures; refresh AGENTS/README/docs diagrams.
  - Done: analysis singletons removed, models.py shim deleted, set_on_state_change removed, docs updated.

## Open questions
- Command payload policy: keep sanitized command in data or allow config to drop it? Default proposed: keep sanitized, log summary only.
- Do we want duplicate-start suppression in the shell source as part of this pass, or later?
- Should emit-level metrics be always-on or behind a toggle?
- iTerm2 API usage: consolidate through `iterm/client.py` where possible; keep specialized monitors (PromptMonitor, FocusMonitor, screen capture) in sources/render, avoid ad-hoc `iterm2.async_get_app` calls elsewhere.
13) Logging/metrics conventions
    - Logging: standardized prefix `[Component] action key=val`, levels: INFO for key events/state changes/start-stop, DEBUG for details/branches, WARNING for recoverable issues, ERROR for failures/data loss. Components use consistent short names (HookMgr, StateMgr, PaneSM, ShellSrc, ClaudeSrc, ItermSrc, Supervisor, WebWS, Bootstrap).
    - Sensitive/long fields: sanitize at source (truncate/mask command/payload), INFO uses summaries, DEBUG can include limited detail.
    - Metrics: emit counters via telemetry facade: `hooks.events_total{source,event_type}`, `queue.depth/dropped{pane}`, `timer.errors_total{name}`, optional `pane.transitions_total{from,to,source}`, `content.refresh/enqueue_total{reason}` (while legacy queue remains).
    - Config switches: `LOG_LEVEL`, `LOG_MAX_CMD_LEN`/`MASK_COMMANDS`, `METRICS_ENABLED`; all logging via `telemetry.get_logger`, metrics via the in-memory facade (replaceable sink later).
14) Config conventions
    - Keep configuration centralized in `config.py`; add new feature flags/logging/masking/metrics switches there (avoid scattered env reads).
15) Module public surface
    - Each submodule exposes a clear public API (`__all__` or explicit facade); avoid cross-layer access to internal helpers. Document intended imports per layer.
16) Event/message typing
    - Define shared DTOs for hook events and WebSocket payloads (Pydantic/dataclass) in a types module; reduce magic strings/dicts across sources/handlers.
17) Naming/normalization
    - Centralize session/pane normalization (e.g., `normalize_session_id`) and reuse in sources/manager/web/logging to avoid duplicate transforms.
18) Legacy cleanup
    - After migrations, remove dummy analyzer/create_analyzer, obsolete tests/fixtures, and old API shims.
19) Config guards
    - In `config.py`, add comments/defaults and sanity checks for thresholds (queue limits, truncation lengths, timer intervals); fail fast or warn on invalid values.

## iTerm2 API consolidation plan
- Goal: centralize generic iTerm2 interactions in `iterm/client.py` (and `iterm/layout.py` for traversal); limit direct `iterm2` imports to `iterm/*`, hook sources (Prompt/Focus), and renderer (screen capture).
- Client extensions: add helpers for layout fetch (`get_layout()` wrapping `layout.get_layout`), session content (`get_session_content` already exists), session list, and safe wrappers with consistent error handling/logging.
- Supervisor: refactor to depend on `ITerm2Client` for app/session/layout/content instead of calling `iterm2.async_get_app` directly; keep only `TermSupervisor.run` signature passing the client or connection as needed.
- Renderer: keep direct Session/ScreenContents access (specialized), but fetch sessions via client where possible.
- Sources: Shell/Focus keep using dedicated monitors (PromptMonitor/FocusMonitor); other sources should not import `iterm2` directly.
- Cleanup: remove stray `import iterm2` outside allowed modules; update docs/diagrams to reflect the client boundary; adjust tests/mocks to use the client interfaces.
