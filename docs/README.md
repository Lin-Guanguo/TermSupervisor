# TermSupervisor - Project Documentation

Last Updated: 2025-12-06

## Current Documentation

| File | Description |
|------|-------------|
| `architecture.md` | **Current architecture**: File structure, module dependencies, data flow, state machine, config |
| `content-heuristic.md` | Keyword-gated content heuristic design (`esc to ...`, `1yes` patterns, per-pane tracking) |
| `state-machine-design.md` | State machine design discussion: events, state transitions, priority rules |
| `hook-system-design.md` | Hook system design: external tool integration (Claude Code, shell, iTerm focus) |

## Historical / Reference

| File | Description |
|------|-------------|
| `_root_AGENTS.md` | Agent configuration reference |
| `notification-refresh-refactor.md` | ~~Deprecated~~ (superseded by architecture.md) |
| `task-detection-improvements.md` | Task detection improvement proposals |

## state-architecture/ Directory

State management architecture documents (refactor completed):

| File | Description |
|------|-------------|
| `state-architecture.md` | **Main doc**: Current implementation + improvement plans |
| `refactor_plan.md` | Refactor overview: 5-step implementation plan |
| `refactor_01_timer.md` | Step 1: Timer module |
| `refactor_02_transitions.md` | Step 2: Transition rules + PaneStateMachine |
| `refactor_03_pane.md` | Step 3: Pane display class |
| `refactor_04_manager.md` | Step 4: PaneManager + integration |
| `refactor_05_cleanup.md` | Step 5: Cleanup + tests |
