Last Updated: 2025-12-01

# Documentation Index

Brief overview of documentation files in this directory.

## Files

- **[state-architecture.md](state-architecture.md)** — Current state pipeline architecture: HookManager → StateManager → PaneStateMachine → Pane display layer, including module boundaries and data flows.

- **[hook-manager-refactor.md](hook-manager-refactor.md)** — Refactor plan for HookManager event handling: moving source-specific logic into sources while keeping Manager generic.

- **[pane-state-optimization.md](pane-state-optimization.md)** — UX optimization strategy: auto-dismiss behaviors, LONG_RUNNING stickiness, queue priority policies, WAITING recovery, and persistence wiring.
