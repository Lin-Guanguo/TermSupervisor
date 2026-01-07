# Tmux Integration Implementation Plan

Last Updated: 2026-01-07

## Status: Complete

All phases of tmux integration are implemented:
- ✅ Phase 1: TerminalAdapter protocol + iTerm2 adapter
- ✅ Phase 2: TmuxClient core implementation
- ✅ Phase 3: TmuxAdapter + integration
- ✅ Phase 4: Hook system integration (focus events)
- ✅ Phase 5: Final review and documentation

## Overview

This document provides a detailed, phased implementation plan for adding tmux support to TermSupervisor. The plan prioritizes minimal changes and test-driven development.

## Design Decisions

### Q1: Is TerminalAdapter Interface Too Complex?

**Yes.** The original design proposes too many methods. Simplified approach:

```python
# adapters/base.py
from typing import Protocol

class TerminalAdapter(Protocol):
    """Minimal terminal adapter interface."""

    name: str  # "iterm2" | "tmux"

    async def get_layout(self) -> LayoutData | None:
        """Get current layout."""
        ...

    async def get_pane_content(self, pane_id: str) -> str | None:
        """Get pane content."""
        ...

    async def get_job_metadata(self, pane_id: str) -> JobMetadata | None:
        """Get foreground job info (optional - return None if unsupported)."""
        ...

    async def activate_pane(self, pane_id: str) -> bool:
        """Jump to pane."""
        ...

    async def rename_pane(self, pane_id: str, name: str) -> bool:
        """Rename pane."""
        ...
```

**Deferred from interface:**
- `connect()` - implementation detail
- `subscribe_events()` - too terminal-specific, keep in concrete classes

### Q2: Should CompositeAdapter Be Deferred?

**Yes.** For MVP:
- Support running with iTerm2 only (current)
- Support running with tmux only (new)
- CompositeAdapter (both simultaneously) is Phase 4+ (future)

### Q3: Pane ID Format

**Keep native IDs, don't prefix.** Reasons:
1. Minimal code changes
2. IDs are already terminal-native throughout
3. `core/ids.py` already handles normalization for iTerm2
4. For tmux: IDs are `%0`, `%1` format (no prefix needed)

If CompositeAdapter is needed later, handle prefixing at that layer only.

### Q4: Minimum Viable TmuxClient

5 core methods:
```python
class TmuxClient:
    async def list_windows(self) -> list[dict]    # tmux list-windows -a -F
    async def list_panes(self) -> list[dict]      # tmux list-panes -a -F
    async def capture_pane(self, pane_id: str, lines: int = 30) -> str
    async def select_pane(self, pane_id: str) -> bool
    async def get_active_pane(self) -> str | None  # For focus detection
```

---

## Implementation Phases

### Phase 1: TerminalAdapter Protocol + iTerm2 Adapter
**Goal:** Introduce abstraction without breaking existing functionality

#### 1.1 Create base adapter protocol
- [ ] Create `adapters/base.py` with `TerminalAdapter` protocol
- [ ] Create `adapters/base.py` with `JobMetadata` base dataclass (move from iterm2)

#### 1.2 Wrap iTerm2Client as adapter
- [ ] Create `adapters/iterm2/adapter.py` implementing `TerminalAdapter`
- [ ] Keep existing `ITerm2Client` internally, wrap with adapter interface
- [ ] Adapter delegates to client + get_layout()

#### 1.3 Update ContentPoller
- [ ] Change `ContentPoller.__init__` to accept `TerminalAdapter` instead of `ITerm2Client`
- [ ] Update method calls to use adapter interface

#### 1.4 Update imports in web/app.py
- [ ] Use adapter instead of direct ITerm2Client for poller

**Acceptance Criteria:**
- [ ] All 186 existing tests pass
- [ ] `make run` works identically to before
- [ ] No functional changes to user

**Tests to Write First:**
```python
# tests/adapters/test_base.py
def test_iterm2_adapter_implements_protocol():
    """ITerm2Adapter satisfies TerminalAdapter protocol."""

async def test_iterm2_adapter_get_layout():
    """Adapter returns LayoutData."""

async def test_iterm2_adapter_get_pane_content():
    """Adapter returns content string."""
```

---

### Phase 2: TmuxClient Core
**Goal:** Implement basic tmux command wrapper

#### 2.1 Create TmuxClient
- [ ] Create `adapters/tmux/__init__.py`
- [ ] Create `adapters/tmux/client.py` with TmuxClient class
- [ ] Implement `run()` - async subprocess for tmux commands
- [ ] Implement `list_windows()` - parse tmux list-windows
- [ ] Implement `list_panes()` - parse tmux list-panes
- [ ] Implement `capture_pane()` - get pane content
- [ ] Implement `select_pane()` - activate pane
- [ ] Implement `get_active_pane()` - get focused pane

#### 2.2 Create layout parser
- [ ] Create `adapters/tmux/layout.py`
- [ ] Parse tmux output into `LayoutData`, `WindowInfo`, `TabInfo`, `PaneInfo`
- [ ] Handle tmux coordinate system (percentage-based)

**Acceptance Criteria:**
- [ ] TmuxClient can list windows/panes from real tmux session
- [ ] TmuxClient can capture pane content
- [ ] Layout parser produces valid LayoutData

**Tests to Write First:**
```python
# tests/adapters/tmux/test_client.py
async def test_tmux_client_run_command():
    """TmuxClient executes tmux commands."""

def test_parse_list_windows():
    """Parse tmux list-windows output."""

def test_parse_list_panes():
    """Parse tmux list-panes output."""

async def test_capture_pane():
    """Capture pane content via tmux capture-pane."""

# tests/adapters/tmux/test_layout.py
def test_build_layout_data():
    """Build LayoutData from tmux output."""

def test_pane_coordinates():
    """Calculate pane coordinates from tmux geometry."""
```

---

### Phase 3: TmuxAdapter + Integration
**Goal:** Full tmux adapter implementing TerminalAdapter

#### 3.1 Create TmuxAdapter
- [ ] Create `adapters/tmux/adapter.py`
- [ ] Implement `TerminalAdapter` protocol
- [ ] Wire TmuxClient methods to adapter interface

#### 3.2 Create tmux JobMetadata (simplified)
- [ ] Tmux doesn't have shell integration like iTerm2
- [ ] Return basic info: pane_title, current_command, current_path
- [ ] Use tmux variables: `#{pane_current_command}`, `#{pane_current_path}`

#### 3.3 Configuration to select adapter
- [ ] Add `TERMINAL_ADAPTER` config option: "iterm2" | "tmux" | "auto"
- [ ] "auto" mode: detect based on environment ($TMUX vs iTerm2 connection)

#### 3.4 Update app.py to use selected adapter
- [ ] Factory function to create appropriate adapter
- [ ] Pass adapter to RenderPipeline

**Acceptance Criteria:**
- [ ] `TERMINAL_ADAPTER=tmux make run` shows tmux layout in dashboard
- [ ] Clicking pane activates it in tmux
- [ ] Content polling works for tmux panes
- [ ] All existing tests still pass

**Tests to Write First:**
```python
# tests/adapters/tmux/test_adapter.py
async def test_tmux_adapter_get_layout():
    """TmuxAdapter returns LayoutData."""

async def test_tmux_adapter_get_pane_content():
    """TmuxAdapter returns pane content."""

async def test_tmux_adapter_activate_pane():
    """TmuxAdapter activates pane in tmux."""

# tests/integration/test_adapter_selection.py
def test_auto_detect_iterm2():
    """Auto-detect iTerm2 when connection available."""

def test_auto_detect_tmux():
    """Auto-detect tmux when $TMUX set."""
```

---

### Phase 4: Hook System Integration
**Goal:** Enable state management for tmux panes

#### 4.1 Shell event detection for tmux
- [ ] Option A: Polling tmux for command start/end (simpler)
- [ ] Option B: Use tmux hooks if available (more complex)
- [ ] Create `hooks/sources/tmux_shell.py` or extend `shell.py`

#### 4.2 Focus event detection
- [ ] Create tmux focus source
- [ ] Poll `tmux display-message -p '#{pane_id}'` periodically
- [ ] Emit `iterm.focus` equivalent events

#### 4.3 Claude Code integration
- [ ] Claude Code HTTP hook works regardless of terminal (already terminal-agnostic)
- [ ] Ensure pane_id in hook payload matches tmux format

**Acceptance Criteria:**
- [ ] Pane states (IDLE, RUNNING, DONE, FAILED) work in tmux
- [ ] Focus changes update dashboard
- [ ] Claude Code events show correct status

**Tests to Write First:**
```python
# tests/hooks/test_tmux_hooks.py
async def test_tmux_focus_detection():
    """Detect focus changes in tmux."""

async def test_tmux_shell_events():
    """Detect command start/end in tmux."""
```

---

### Phase 5: Polish & Documentation
**Goal:** Production readiness

#### 5.1 Error handling
- [ ] Graceful fallback if tmux not running
- [ ] Handle tmux session disconnect/reconnect
- [ ] Logging improvements

#### 5.2 Documentation
- [ ] Update README with tmux setup instructions
- [ ] Add tmux-specific configuration docs
- [ ] Update CLAUDE.md with new architecture

#### 5.3 Code review
- [ ] DRY principle check
- [ ] Type annotations complete
- [ ] Test coverage review

**Acceptance Criteria:**
- [ ] Documentation complete
- [ ] No critical bugs
- [ ] Code review passed

---

## Files to Create/Modify

### New Files
```
src/termsupervisor/adapters/
├── base.py                    # TerminalAdapter protocol + JobMetadata
├── tmux/
│   ├── __init__.py
│   ├── client.py              # TmuxClient
│   ├── adapter.py             # TmuxAdapter
│   └── layout.py              # Layout parser
```

### Modified Files
```
src/termsupervisor/adapters/iterm2/
├── adapter.py                 # NEW: ITerm2Adapter wrapper
├── client.py                  # Move JobMetadata to base.py

src/termsupervisor/render/
├── poller.py                  # Accept TerminalAdapter instead of ITerm2Client

src/termsupervisor/web/
├── app.py                     # Adapter factory
├── handlers.py                # Route actions to correct adapter

src/termsupervisor/
├── config.py                  # Add TERMINAL_ADAPTER config

tests/adapters/
├── test_base.py               # Existing + new adapter tests
├── tmux/
│   ├── test_client.py
│   ├── test_adapter.py
│   └── test_layout.py
```

---

## Deferred (Future Phases)

1. **CompositeAdapter** - Run both iTerm2 and tmux simultaneously
2. **Notification integration** - Unify with claude-notify
3. **Usage tracking** - SQLite frequency tracking
4. **CLI tools** - Jump/list commands

---

## Risk Assessment

| Risk | Mitigation |
|------|------------|
| Tmux command parsing fragile | Comprehensive test fixtures for output formats |
| iTerm2 breakage during refactor | All tests must pass before merge |
| Performance overhead | Async subprocess, minimal polling |
| ID collision between terminals | Defer to CompositeAdapter phase |

---

## Success Metrics

- [ ] All 186+ tests pass after each phase
- [ ] `make test` green before each commit
- [ ] Dashboard shows tmux layout correctly
- [ ] Pane activation works in tmux
- [ ] No regression in iTerm2 functionality
