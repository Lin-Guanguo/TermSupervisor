Last Updated: 2025-12-01

# Pane State Optimization Strategy

Focus: reduce sticky/noisy states, improve responsiveness, and keep frontend/backend aligned across HookManager -> StateManager -> PaneStateMachine -> Pane display.

## Current snapshot
- Sources: shell / claude-code / iterm.focus / frontend.click / timer.check / content.update. `content.update` comes from 1s polling + PaneChangeQueue (>=5 lines or 10s timeout) with line_count + content/hash for UI and WAITING_APPROVAL fallback.
- Queueing: one ActorQueue per pane (depth 256, drop oldest on overflow). Generations reject stale events. No priority separation; content.update and command_* share the same queue.
- State machine: six states, source-isolated. LONG_RUNNING is triggered by timer.tick; DONE/FAILED exit only on focus/click or a new command_start.
- Display: DONE/FAILED -> IDLE is delayed by 5s; notifications suppressed for short tasks (<3s) or when focused. Only content hash is retained.
- State: in-memory only; all state/history lost on restart (persistence was removed).

## UX principles
- DONE/FAILED auto-dismiss after a short dwell (5-10s) without requiring blur/refocus; allow a muted “recently finished” hint.
- LONG_RUNNING stays sticky once promoted; only drop to RUNNING on a real new start (generation bump or source change). Keep elapsed visible.
- Alert budget: WAITING_APPROVAL and FAILED are the only states that should blink/alert; DONE should be calm and very short tasks should complete quietly.
- Notification suppression: keep focus-based suppression for popups; still advance state; suppress popup and blink for very short tasks (<3s).
- Recovery: WAITING should resume on content.update immediately and via a timed fallback (20-30s) with a reason if it times out.
- Cross-source continuity: same-source RUNNING->RUNNING should not reset timers; cross-source starts can reset.
- Failure forgiveness: under queue pressure, prefer dropping content.update, never command_end; UI should stay consistent even with drops.
- Fresh start: restart begins with clean state (no persistence).

## Phase plan
### Phase 1 (must ship): UX fixes + queue priority
Scope:
- Auto-dismiss DONE/FAILED after dwell even if focused; add muted “recently finished” hint.
- LONG_RUNNING ignores same-source RUNNING while LONG_RUNNING unless generation bumps; preserve elapsed badge.
- content.update treated as low priority; drop/merge under high watermark, never drop command_end; add drop counters.
- Optional: quiet completion toggle for tasks <3s (state changes but no flash/toast).
Done checklist:
- Tests cover auto-dismiss, sticky LONG_RUNNING same-source ignore, and queue drop policy (command_end preserved).
- Defaults set in config for dwell, quiet window, and queue watermarks.
- Docs mention the new UX behavior; logs/metrics hooked for drops and auto-clear.

### Phase 2 (must ship): WAITING recovery + content.update rename
Scope:
- Lower polling/refresh threshold while WAITING (1-line or hash heartbeat).
- WAITING resumes on content heartbeat and via timed fallback (20-30s) to RUNNING if changing, else to IDLE with reason.
- Rename `content.changed` -> `content.update` everywhere (backend, frontend, tests); decide on temporary alias flag if needed and remove after verification.
Done checklist:
- Tests for content-driven resume and timed fallback; WAITING->RUNNING/IDLE paths covered.
- WebSocket emits and frontend consumes `content.update`; no duplicate renders (hash respected).
- wait_fallback metrics/logs present; alias flag removed or gated explicitly.

### Phase 3 (optional/flagged): Content heuristics
Scope:
- Add `analysis/heuristics.py` (or hooks/sources/content_heuristic.py) as a light detector behind a flag (default off).
- Fire command_start/idle/end only for allowed sources (e.g., gemini/codex), only when pane is idle-ish; ignore panes owned by shell/claude.
- Same-source stickiness respected (no restart of LONG_RUNNING); idle threshold ends heuristic sessions.
Done checklist:
- Tests for start/idle/end, idle timeout, and guardrails against clobbering other sources.
- Metrics/logs for heuristic start/idle/drop; flag documented.
- No regression in stickiness rules or queue pressure behavior.

## Module map (where changes land)
- State UX: pane/pane.py (delay, hint, quiet completion), pane/transitions.py + pane/state_machine.py (sticky LONG_RUNNING), pane/manager.py (timer/user-idle auto-clear), optional CSS in templates/index.html.
- Queue policy: pane/manager.py (content low-priority drop + metrics), pane/queue.py (watermarks/priority lanes), analysis/change_queue.py (WAITING thresholds), config.py (tunables), telemetry.py (drop counters).
- WAITING recovery: pane/manager.py (content resume + timed fallback), pane/transitions.py (R1 content.update), timer.py (scheduled fallback), tests for debounce/timeout.
- Heuristics (flagged): analysis/heuristics.py (or hooks/sources/content_heuristic.py) called from pane/manager.py; transitions accept content-heuristic.*.
- Frontend: web/app.py + templates/index.html (content.update event, hint rendering); ensure content_hash deduping; minimal visual changes.
- Tests: tests/test_pane_state_machine.py, tests/test_state_manager.py, tests/test_hook_manager.py for WAITING fallbacks, drop policy, stickiness; metric assertions.

## Content.update migration (risks, mitigations, code map)
- Risks: WAITING fallback could listen to old name; frontend/WS could ignore new event; large payloads could bloat queue/logs; stale events could bypass dedupe if names diverge.
- Mitigations: one-shot rename; keep low-priority drop policy + counters; truncate or delta+hash if needed; confirm generation/gating rejects stale events.
- Code map:
  - src/termsupervisor/supervisor.py: emit content.update with line_count+content/hash (optional queued_at); document truncation if used.
  - src/termsupervisor/analysis/change_queue.py: align DTO/return fields; keep refresh thresholds.
  - src/termsupervisor/pane/manager.py: rename branch, update_content before WAITING resume; optional heuristic call.
  - src/termsupervisor/pane/transitions.py: R1 uses content.update; tests updated.
  - src/termsupervisor/hooks/manager.py: rename constants/routes; keep generation/gating.
  - src/termsupervisor/web/app.py, templates/index.html: WebSocket message/subscription uses content.update; render path aligned.
  - Tests: update hook/state/pane tests; keep WAITING->RUNNING fallback case.
  - Docs: replace content.changed mentions in README/AGENTS/state docs.
- New modules: not required; heuristics module only if enabled.

## Config and thresholds to lock
- WAITING fallback duration (e.g., 25s) and poll threshold while WAITING (1 line or hash heartbeat).
- DONE/FAILED auto-clear dwell (e.g., 60s) and quiet window for short tasks (e.g., 3s).
- Queue high/low watermarks and drop/merge ordering (always keep command_end; drop or coalesce content first).
- Heuristic flag default (off) and allowed sources; idle threshold for heuristic sessions.
- Rename alias flag (if any) and removal plan.

## Testing and observability
- Success metrics: non-content drop rate <1%; WAITING timeouts <0.5% of waits; no transition latency regression; zero "double transition" logs in timer overlap tests.
- Testing matrix: fake timers for WAITING fallback and auto-clear; queue-under-pressure ensures command_end never drops; same-source RUNNING ignored in LONG_RUNNING; WAITING resume via hash heartbeat; WS emits/consumes content.update without dupes; heuristic start/idle/end guarded by flag.
- Observability/logging: rate-limit drop metrics/logs; standard prefixes [PaneSM]/[StateMgr]/[Pane]/[Heuristic]; include pane_id + generation in logs; counters for wait_fallback (content vs timeout), auto_clear, heuristic start/idle/drop.

## Structure and modularity guardrails
- Preserve layers: emission/throttle (supervisor + analysis/change_queue), routing (hooks/manager), state/logic (pane/manager, state_machine, transitions), presentation (pane/pane.py + frontend). Avoid cross-layer calls; keep payload DTOs stable at layer boundaries.
- Single-responsibility modules: queue policy and thresholds live in pane/manager.py + pane/queue.py; heuristics isolated in analysis/heuristics.py (flagged). Do not mix heuristic logic into state_machine/transitions.
- Config-driven tuning: thresholds/flags reside in config.py; tests may override via fixtures; avoid scattering magic numbers.
- Dependency hygiene: new helpers (heuristics) should be pure or light-state with explicit inputs/outputs; inject via manager to keep state_machine deterministic.
- Frontend decoupling: WebSocket payloads stay minimal (state + content_hash + hints); no queue/state internals leaked. Keep content.update naming consistent across transport and tests.
- Test granularity: unit tests cover state machine rules and manager policies; integration tests for rename/WS path; avoid over-mocking so transitions remain truthful.

## Risks and pitfalls
- Heuristic false positives can flip panes; keep strict confidence and avoid touching panes with active shell/claude unless idle.
- Timer overlap (LONG_RUNNING tick, auto-clear, WAITING fallback) can double-transition; guard with generation and idempotent handlers.
- WebSocket/client lag may drop heartbeats needed for WAITING recovery; keep a minimum heartbeat and log resume source (content vs timeout).
- Drop metrics/logs may get noisy under load; sample/rate-limit to avoid log/telemetry spam.
- Frontend hints can linger on pane rebuild; bump generation and clear hashes on rebuild.

## Further refinement
- Parameterize thresholds in config.py to tune without code churn.
- Add a compact state diagram/table in docs/state-architecture.md to reflect WAITING/DONE timers and heuristic signals.
- If heuristics mature, split per source and allow workspace-level disable.
- Consider a lightweight E2E harness (WS -> frontend) replaying persisted snapshots to validate rename and quiet-completion flows without iTerm2.
