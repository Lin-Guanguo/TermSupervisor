# 状态架构（当前实现）

Last Updated: 2025-11-30

描述当前代码中的状态管线、模块边界与关键数据流。所有内容基于 `src/termsupervisor/` 现有代码，不是计划稿。

## 总览

- 事件入口：Shell PromptMonitor、Claude Code HTTP、iTerm Focus 防抖（2s）、内容变化（polling → PaneChangeQueue → content.changed）。
- 处理链：HookManager → StateManager（per-pane ActorQueue）→ PaneStateMachine（规则/历史/state_id）→ Pane 显示层（延迟 + 通知抑制）。
- 定时：Timer 统一承担 LONG_RUNNING 检测（1s tick）与 DONE/FAILED → IDLE 显示延迟任务。
- 输出：WebSocket 广播 DisplayState + layout；前端基于状态决定边框/闪烁/提示。

---

## 系统架构总图

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                              TermSupervisor System                                   │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                       │
│  ┌────────────────────┐         ┌───────────────────────────────────────────────┐   │
│  │    iTerm2 App      │         │           Hook Sources (事件入口)              │   │
│  │   (iterm2 API)     │         │  ┌─────────────────────────────────────────┐  │   │
│  │                    │         │  │ 1. ShellHookSource (PromptMonitor)      │  │   │
│  │ - Windows          │         │  │ 2. ClaudeCodeHookSource (HTTP API)      │  │   │
│  │ - Tabs             │         │  │ 3. ItermHookSource (Focus 2s debounce)  │  │   │
│  │ - Sessions         │         │  │ 4. Content polling (supervisor.py)      │  │   │
│  │ - Content          │         │  └─────────────────────────────────────────┘  │   │
│  └─────────┬──────────┘         └───────────────────┬───────────────────────────┘   │
│            │                                        │                                │
│            │                                        ▼                                │
│            │                        ┌───────────────────────────────┐               │
│            │                        │     HookManager (Facade)      │               │
│            │                        │                               │               │
│            │                        │ - _normalize_event()          │               │
│            │                        │ - process_event()             │               │
│            │                        │ - process_shell_*()           │               │
│            │                        │ - process_claude_code_*()     │               │
│            │                        │ - process_content_change()    │               │
│            │                        └───────────────┬───────────────┘               │
│            │                                        │                                │
│            ▼                                        ▼                                │
│  ┌────────────────────────┐         ┌───────────────────────────────┐               │
│  │   TermSupervisor       │         │      StateManager             │               │
│  │  (Layout Mirror)       │         │                               │               │
│  │                        │         │ Per-Pane Instances:           │               │
│  │ - check_updates()      │         │ - EventQueue (ActorQueue)     │               │
│  │ - PaneChangeQueue      │         │ - PaneStateMachine            │               │
│  │ - ContentCleaner       │         │ - Pane                        │               │
│  │ - SVG Rendering        │         │                               │               │
│  └──────────┬─────────────┘         │ Methods:                      │               │
│             │                        │ - get_or_create(pane_id)     │               │
│             │                        │ - enqueue(event)             │               │
│             │                        │ - process_queued()           │               │
│             │                        │ - tick_all()                 │               │
│             │                        └───────────┬───────────────────┘               │
│             │                                    │                                   │
│             │                    ┌───────────────┼───────────────┐                  │
│             │                    │               │               │                  │
│             │                    ▼               ▼               ▼                  │
│             │            ┌────────────┐ ┌─────────────┐ ┌─────────────────┐         │
│             │            │ EventQueue │ │    Pane     │ │PaneStateMachine │         │
│             │            │            │ │             │ │                 │         │
│             │            │ ActorQueue │ │ DisplayState│ │ rules/history   │         │
│             │            │ FIFO 256   │ │ delay logic │ │ state_id/pred   │         │
│             │            │ generation │ │ suppress    │ │ transitions     │         │
│             │            └─────┬──────┘ └──────┬──────┘ └────────┬────────┘         │
│             │                  │               │                 │                  │
│             │                  └───────────────┼─────────────────┘                  │
│             │                                  │                                    │
│             │                                  ▼                                    │
│             │                        ┌─────────────────┐                            │
│             │                        │     Timer       │                            │
│             │                        │                 │                            │
│             │                        │ - interval 1s   │                            │
│             │                        │ - delay tasks   │                            │
│             │                        └────────┬────────┘                            │
│             │                                 │                                     │
│             └─────────────────────────────────┼───────────────────────────────┐     │
│                                               │                               │     │
│                                               ▼                               ▼     │
│                                    ┌────────────────────────────────────────────┐   │
│                                    │              WebServer                     │   │
│                                    │         (FastAPI + WebSocket)              │   │
│                                    │                                            │   │
│                                    │ - GET / (index.html)                       │   │
│                                    │ - WebSocket /ws (real-time broadcast)      │   │
│                                    │ - POST /api/hook (HookReceiver)            │   │
│                                    └─────────────────┬──────────────────────────┘   │
│                                                      │                              │
│                                                      ▼                              │
│                                    ┌────────────────────────────────┐               │
│                                    │     Frontend Dashboard         │               │
│                                    │     (HTML/JS/WebSocket)        │               │
│                                    │                                │               │
│                                    │ - Layout visualization         │               │
│                                    │ - Pane state display           │               │
│                                    │ - Interactive controls         │               │
│                                    │ - Notifications                │               │
│                                    └────────────────────────────────┘               │
│                                                                                      │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 组件交互图（详细文件级别）

### 1. 入口层（Hook Sources）

```
                    ┌─────────────────────────────────────┐
                    │           External Events           │
                    └─────────────────────────────────────┘
                                      │
        ┌─────────────────────────────┼─────────────────────────────┐
        │                             │                             │
        ▼                             ▼                             ▼
┌───────────────────┐     ┌───────────────────────┐     ┌───────────────────┐
│ hooks/sources/    │     │ hooks/sources/        │     │ hooks/sources/    │
│   shell.py        │     │   claude_code.py      │     │   iterm.py        │
│                   │     │                       │     │                   │
│ ShellHookSource   │     │ ClaudeCodeHookSource  │     │ ItermHookSource   │
│                   │     │                       │     │                   │
│ ┌───────────────┐ │     │ Events:               │     │ Events:           │
│ │PromptMonitor  │ │     │ - SessionStart        │     │ - iterm.focus     │
│ │   Manager     │ │     │ - PreToolUse          │     │   (2s debounce)   │
│ └───────────────┘ │     │ - PostToolUse         │     │                   │
│                   │     │ - Stop                │     │                   │
│ Events:           │     │ - SessionEnd          │     │                   │
│ - command_start   │     │ - Notification:*      │     │                   │
│ - command_end     │     │                       │     │                   │
└─────────┬─────────┘     └───────────┬───────────┘     └─────────┬─────────┘
          │                           │                           │
          │      ┌────────────────────┼────────────────────┐      │
          │      │                    │                    │      │
          │      │                    ▼                    │      │
          │      │        ┌───────────────────────┐        │      │
          │      │        │ hooks/receiver.py     │        │      │
          │      │        │                       │        │      │
          │      │        │ HookReceiver          │        │      │
          │      │        │ POST /api/hook        │        │      │
          │      │        │                       │        │      │
          │      │        │ Adapters:             │        │      │
          │      │        │ - ClaudeCodeAdapter   │        │      │
          │      │        └───────────┬───────────┘        │      │
          │      │                    │                    │      │
          └──────┼────────────────────┼────────────────────┼──────┘
                 │                    │                    │
                 ▼                    ▼                    ▼
          ┌──────────────────────────────────────────────────────┐
          │                                                      │
          │                 hooks/manager.py                     │
          │                    HookManager                       │
          │                                                      │
          │  Methods:                                            │
          │  - _normalize_event(source, pane_id, type, data)    │
          │  - process_event(event: HookEvent)                  │
          │  - process_shell_command_start(pane_id, command)    │
          │  - process_shell_command_end(pane_id, exit_code)    │
          │  - process_claude_code_event(pane_id, type, data)   │
          │  - process_content_change(pane_id, content, hash)   │
          │  - process_user_click(pane_id)                      │
          │  - process_iterm_focus(pane_id)                     │
          │                                                      │
          │  Callbacks:                                          │
          │  - set_change_callback() → WebSocket broadcast      │
          │  - set_focus_checker() → notification suppression   │
          │                                                      │
          └──────────────────────────┬───────────────────────────┘
                                     │
                                     ▼
                    ┌────────────────────────────────────┐
                    │        pane/manager.py             │
                    │          StateManager              │
                    └────────────────────────────────────┘
```

### 2. 状态处理层（State Management）

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           pane/manager.py                                   │
│                             StateManager                                    │
│                                                                             │
│  Instances (per pane_id):                                                   │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐          │
│  │ _machines        │  │ _panes           │  │ _queues          │          │
│  │ {id: Machine}    │  │ {id: Pane}       │  │ {id: EventQueue} │          │
│  └──────────────────┘  └──────────────────┘  └──────────────────┘          │
│                                                                             │
│  Core Methods:                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ get_or_create(pane_id) → (PaneStateMachine, Pane, EventQueue)       │   │
│  │ enqueue(event: HookEvent) → 入队到对应 pane 的 EventQueue           │   │
│  │ process_queued(pane_id) → 处理队列中的所有事件                       │   │
│  │ tick_all() → 检查所有 RUNNING 状态，触发 LONG_RUNNING               │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  Callback Chain:                                                            │
│  PaneStateMachine.on_state_change → Pane.handle_state_change              │
│  Pane.on_display_change → StateManager._on_pane_display_change            │
│  StateManager → External callback (WebSocket broadcast)                    │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
                │                    │                    │
                ▼                    ▼                    ▼
┌───────────────────────┐ ┌───────────────────────┐ ┌───────────────────────┐
│    pane/queue.py      │ │ pane/state_machine.py │ │     pane/pane.py      │
│      EventQueue       │ │   PaneStateMachine    │ │        Pane           │
│                       │ │                       │ │                       │
│ ActorQueue[HookEvent] │ │ State:                │ │ State:                │
│                       │ │ - _status             │ │ - DisplayState        │
│ - max_size: 256       │ │ - _source             │ │ - _content            │
│ - FIFO                │ │ - _started_at         │ │ - _content_hash       │
│ - drop oldest if full │ │ - _state_id           │ │ - _last_state_id      │
│ - generation filter   │ │ - _pane_generation    │ │                       │
│                       │ │ - _history            │ │ Methods:              │
│ Methods:              │ │                       │ │ - handle_state_change │
│ - enqueue_event()     │ │ Methods:              │ │ - update_content()    │
│ - dequeue()           │ │ - process(event)      │ │ - should_suppress_    │
│                       │ │ - should_check_       │ │   notification()      │
│ Metrics:              │ │   long_running()      │ │ - to_dict/from_dict   │
│ - queue.depth         │ │ - to_dict/from_dict   │ │                       │
│ - queue.dropped       │ │                       │ │ Delay Logic:          │
│                       │ │                       │ │ - DONE/FAILED → IDLE  │
└───────────────────────┘ │                       │ │   延迟 5s 显示        │
                          │                       │ │ - 通知抑制 <3s/focus  │
                          └───────────────────────┘ └───────────────────────┘
                                     │
                    ┌────────────────┼────────────────┐
                    ▼                ▼                ▼
          ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────────┐
          │pane/transitions │ │pane/predicates  │ │   pane/types.py     │
          │      .py        │ │      .py        │ │                     │
          │                 │ │                 │ │ DTOs & Enums:       │
          │ TRANSITION_RULES│ │ Predicate funcs:│ │ - TaskStatus        │
          │ (20+ rules)     │ │ - require_exit_ │ │ - HookEvent         │
          │                 │ │   code()        │ │ - StateChange       │
          │ Rules:          │ │ - require_same_ │ │ - DisplayState      │
          │ S1-S3 (shell)   │ │   generation()  │ │ - StateHistoryEntry │
          │ C1-C6 (claude)  │ │ - require_      │ │ - TransitionRule    │
          │ T1 (timer)      │ │   running_      │ │ - StateSnapshot     │
          │ U1-U2 (user)    │ │   duration_gt() │ │                     │
          │ R1 (content)    │ │ - require_      │ │                     │
          │                 │ │   status_in()   │ │                     │
          │ Functions:      │ │ - require_      │ │                     │
          │ - find_matching │ │   source_match()│ │                     │
          │   _rule()       │ │                 │ │                     │
          └─────────────────┘ └─────────────────┘ └─────────────────────┘
```

### 3. 定时器层（Timer）

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                               timer.py                                      │
│                                 Timer                                       │
│                                                                             │
│  ┌────────────────────────────────────────────────────────────────────┐    │
│  │                         IntervalTask                               │    │
│  │                                                                     │    │
│  │  - name: str                                                        │    │
│  │  - interval: float (seconds)                                        │    │
│  │  - callback: Callable                                               │    │
│  │  - last_run: float (timestamp)                                      │    │
│  │                                                                     │    │
│  │  Registered:                                                        │    │
│  │  - StateManager.tick_all() (每 1s, LONG_RUNNING 检测)               │    │
│  └────────────────────────────────────────────────────────────────────┘    │
│                                                                             │
│  ┌────────────────────────────────────────────────────────────────────┐    │
│  │                          DelayTask                                 │    │
│  │                                                                     │    │
│  │  - name: str (unique key, overwrites duplicates)                    │    │
│  │  - delay: float (seconds)                                           │    │
│  │  - trigger_at: float (timestamp)                                    │    │
│  │  - callback: Callable                                               │    │
│  │  - cancelled: bool                                                  │    │
│  │                                                                     │    │
│  │  Used by:                                                           │    │
│  │  - Pane._register_delayed_display() (DONE/FAILED → IDLE 延迟 5s)   │    │
│  └────────────────────────────────────────────────────────────────────┘    │
│                                                                             │
│  Core Methods:                                                              │
│  - register_interval(name, interval, callback) → 注册周期任务              │
│  - register_delay(name, delay, callback) → 注册延迟任务                    │
│  - cancel_delay(name) → 取消延迟任务                                       │
│  - has_delay(name) → 检查延迟任务是否存在                                   │
│  - run() → async 主循环 (1s tick)                                          │
│  - stop() → 停止所有任务                                                   │
│                                                                             │
│  Exception Isolation: 单个任务失败不影响其他任务                            │
│  Metrics: timer.errors                                                      │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
                    │
                    │ triggers
                    ▼
    ┌───────────────────────────────────────────┐
    │                                           │
    │  StateManager.tick_all()                  │
    │  ├── 遍历所有 PaneStateMachine            │
    │  ├── 检查 should_check_long_running()     │
    │  ├── 若 RUNNING 且 elapsed > 60s          │
    │  └── 发送 timer.check 事件                │
    │                                           │
    │  Pane delayed display callback            │
    │  ├── 检查 state_id 是否过期               │
    │  └── 更新 DisplayState 为 IDLE            │
    │                                           │
    └───────────────────────────────────────────┘
```

### 4. 内容处理层（Content Processing）

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           supervisor.py                                     │
│                          TermSupervisor                                     │
│                                                                             │
│  ┌───────────────────────────────────────────────────────────────────┐     │
│  │                     iTerm2 Polling Loop                           │     │
│  │                                                                    │     │
│  │  check_updates(connection) ── 每 1s 调用                          │     │
│  │  ├── 遍历所有 pane                                                 │     │
│  │  ├── 读取 content                                                  │     │
│  │  ├── ContentCleaner.clean_content_str()                            │     │
│  │  ├── PaneChangeQueue.check_and_record()                            │     │
│  │  │   ├── ≥5 lines changed OR 10s timeout → refresh SVG            │     │
│  │  │   │   └── hook_manager.process_content_changed()               │     │
│  │  │   └── else → 仅更新队尾                                         │     │
│  │  └── 广播 layout 变化                                              │     │
│  └───────────────────────────────────────────────────────────────────┘     │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
          │                         │                         │
          ▼                         ▼                         ▼
┌───────────────────────┐ ┌───────────────────────┐ ┌───────────────────────┐
│analysis/change_queue  │ │analysis/content_      │ │   render/renderer.py  │
│                       │ │   cleaner.py          │ │                       │
│ PaneChangeQueue       │ │                       │ │ TerminalRenderer      │
│ - check_and_record()  │ │ ContentCleaner        │ │                       │
│ - REFRESH_LINES: 5    │ │                       │ │ - ANSI → Rich color   │
│ - NEW_RECORD_LINES:20 │ │ Whitelist:            │ │ - Wide char handling  │
│ - FLUSH_TIMEOUT: 10s  │ │ - English, Latin      │ │ - XML sanitization    │
│                       │ │ - CJK, JP, KR         │ │                       │
│ ChangeRecord          │ │                       │ │ Output: SVG           │
│ - hash                │ │ Methods:              │ │                       │
│ - snapshot            │ │ - clean_line()        │ │                       │
│ - diff_summary        │ │ - clean_content()     │ │                       │
│                       │ │ - diff_lines()        │ │                       │
│ LayoutData            │ │ - content_hash()      │ │                       │
│ - windows/tabs/panes  │ │                       │ │                       │
│ - positioning         │ │ Filters:              │ │                       │
│                       │ │ - ANSI codes          │ │                       │
│                       │ │ - Spinners            │ │                       │
│                       │ │ - Punctuation/emojis  │ │                       │
└───────────────────────┘ └───────────────────────┘ └───────────────────────┘
```

### 5. Web 服务层（Web Server）

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              web/app.py                                     │
│                         App Factory & Setup                                 │
│                                                                             │
│  Functions:                                                                 │
│  - create_app(supervisor, iterm_client) → WebServer                        │
│  - setup_hook_system(server, connection):                                   │
│      ├── 获取 HookManager & Timer 单例                                      │
│      ├── 创建 ShellHookSource, ClaudeCodeHookSource, ItermHookSource       │
│      ├── 注册 on_status_change callback → broadcast                        │
│      ├── 设置 focus_checker → notification suppression                     │
│      ├── 创建 HookReceiver, 注册 adapters                                  │
│      └── 启动所有 sources                                                   │
│  - start_server(connection) → 入口                                         │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                            web/server.py                                    │
│                              WebServer                                      │
│                                                                             │
│  Base: FastAPI                                                              │
│                                                                             │
│  Endpoints:                                                                 │
│  ┌──────────────────────────────────────────────────────────────────┐      │
│  │ GET /              → templates/index.html                        │      │
│  │ WebSocket /ws      → Real-time updates                           │      │
│  │ POST /api/hook     → HookReceiver (via setup_hook_receiver)      │      │
│  └──────────────────────────────────────────────────────────────────┘      │
│                                                                             │
│  Methods:                                                                   │
│  - broadcast(dict) → 发送到所有连接的 WebSocket 客户端                       │
│  - setup_hook_receiver(receiver) → 安装 HTTP hook 接收器                    │
│                                                                             │
│  Callbacks:                                                                 │
│  - 接收 layout & state 变化 → broadcast to WS clients                       │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           web/handlers.py                                   │
│                           MessageHandler                                    │
│                                                                             │
│  WebSocket Message Types (JSON only):                                       │
│  ┌──────────────────────────────────────────────────────────────────┐      │
│  │ {"action": "activate", "session_id": ...}                        │      │
│  │   → emit_event("click_pane") → focus pane                        │      │
│  │                                                                   │      │
│  │ {"action": "rename", "type": "window|tab|session", ...}          │      │
│  │   → iterm_client.rename_*()                                       │      │
│  │                                                                   │      │
│  │ {"action": "create_tab", "window_id": ..., "layout": ...}        │      │
│  │   → iterm_client.create_tab()                                     │      │
│  └──────────────────────────────────────────────────────────────────┘      │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 6. iTerm2 集成层

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                             iterm/ 目录                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌───────────────────────────────────────────────────────────────────┐     │
│  │                         iterm/layout.py                           │     │
│  │                                                                    │     │
│  │  get_layout(app, exclude_names) → LayoutData                      │     │
│  │  ├── traverse_node(): 递归 DFS Splitter 树                         │     │
│  │  ├── 处理 vertical/horizontal splits                               │     │
│  │  ├── 计算 widths/heights                                           │     │
│  │  └── 分配 global pane indices                                      │     │
│  └───────────────────────────────────────────────────────────────────┘     │
│                                                                             │
│  ┌───────────────────────────────────────────────────────────────────┐     │
│  │                         iterm/client.py                           │     │
│  │                          ITerm2Client                             │     │
│  │                                                                    │     │
│  │  Methods:                                                          │     │
│  │  - activate_session(session_id) → 聚焦 pane                        │     │
│  │  - rename_window/tab/session(id, new_name)                        │     │
│  │  - create_tab(window_id, layout)                                  │     │
│  │  - get_session_by_id(session_id)                                  │     │
│  └───────────────────────────────────────────────────────────────────┘     │
│                                                                             │
│  ┌───────────────────────────────────────────────────────────────────┐     │
│  │                          iterm/utils.py                           │     │
│  │                                                                    │     │
│  │  - normalize_session_id(session_id): w0t1p1:UUID → UUID           │     │
│  │  - session_id_match(id1, id2): 比较规范化 ID                       │     │
│  └───────────────────────────────────────────────────────────────────┘     │
│                                                                             │
│  ┌───────────────────────────────────────────────────────────────────┐     │
│  │                         iterm/naming.py                           │     │
│  │                                                                    │     │
│  │  - Get/set window, tab, session display names                     │     │
│  └───────────────────────────────────────────────────────────────────┘     │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 7. 基础设施层

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Infrastructure                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌───────────────────────────────────────────────────────────────────┐     │
│  │                          config.py                                │     │
│  │                                                                    │     │
│  │  Central configuration constants:                                  │     │
│  │  - Poll intervals                                                  │     │
│  │  - State thresholds (LONG_RUNNING: 60s)                            │     │
│  │  - Queue sizes (256 max)                                           │     │
│  │  - Display delays (5s)                                             │     │
│  │  - Notification suppression (3s)                                   │     │
│  │                                                                    │     │
│  │  Used by: nearly all modules                                       │     │
│  └───────────────────────────────────────────────────────────────────┘     │
│                                                                             │
│  ┌───────────────────────────────────────────────────────────────────┐     │
│  │                         telemetry.py                              │     │
│  │                                                                    │     │
│  │  Logging & Metrics:                                                │     │
│  │  - get_logger(name): Logger 工厂                                   │     │
│  │  - Metrics: in-memory counters/gauges                             │     │
│  │  - format_pane_log(): 标准化日志格式                                │     │
│  │                                                                    │     │
│  │  Tracked metrics:                                                  │     │
│  │  - queue.depth, queue.dropped                                     │     │
│  │  - transition.ok, transition.fail                                 │     │
│  │  - timer.errors                                                   │     │
│  │  - pane.stale_state_id                                            │     │
│  └───────────────────────────────────────────────────────────────────┘     │
│                                                                             │
│  ┌───────────────────────────────────────────────────────────────────┐     │
│  │                      runtime/bootstrap.py                         │     │
│  │                                                                    │     │
│  │  Centralized component construction:                               │     │
│  │  - bootstrap(connection) → RuntimeComponents                       │     │
│  │    Creates: Timer, HookManager, Sources, Receiver                  │     │
│  │  - get_current_components() → access existing instance             │     │
│  │  - Prevents dual-construction (raises RuntimeError)                │     │
│  └───────────────────────────────────────────────────────────────────┘     │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 事件处理流程图

```
USER ACTION / EXTERNAL EVENT
         │
         ▼
┌──────────────────────────┐
│   Hook Source            │ (shell / claude-code / iterm / content)
└──────────────┬───────────┘
               │
               ▼
       ┌───────────────────┐
       │  HookManager      │
       │ normalize_event() │ ◄─── 添加: generation, timestamp, signal
       │ process_event()   │
       └─────────┬─────────┘
               │
               ▼
       ┌──────────────────────┐
       │ StateManager         │
       │ enqueue(event)       │
       └─────────┬────────────┘
               │
               ▼
       ┌──────────────────────┐
       │ EventQueue           │
       │ (per pane)           │ ◄─── FIFO, 256 max, drop oldest if full
       │ enqueue_event()      │
       └─────────┬────────────┘
               │
               ▼
       ┌──────────────────────────┐
       │ StateManager             │
       │ process_queued()         │
       │ ├─ dequeue()             │
       │ └─ _process_event()      │
       └────────┬─────────────────┘
               │
         ┌─────┴─────┐
         │            │
         ▼            ▼
    content.changed  OTHER EVENTS
         │            │
         │            ├──> PaneStateMachine.process(event)
         │            │
    Pane.             │  1. Check generation
    update_content()  │  2. Find matching rules
         │            │  3. Check predicates
         │            │  4. Update state
         │            │  5. Record history
         │            │  6. Fire callback
         │            │
         ▼            ▼
    DisplayState  StateChange
         │            │
         └────┬───────┘
              │
              ▼
    ┌────────────────────────┐
    │ Pane.handle_state_     │
    │     change()           │
    │                        │
    │ 1. Check state_id      │
    │ 2. Cancel old delays   │
    │ 3. Check if delay req  │
    │ 4. Update display      │
    │ 5. Fire callback       │
    └────────┬───────────────┘
             │
             ▼
    ┌──────────────────────┐
    │ StateManager         │
    │ _on_pane_display_    │
    │    change()          │
    │                      │
    │ Check notification   │
    │ suppression          │
    └────────┬─────────────┘
             │
             ▼
    ┌──────────────────────┐
    │ WebServer.broadcast  │
    │                      │
    │ → All WebSocket      │
    │   clients            │
    └──────────────────────┘
```

---

## Timer 流程图

```
Timer.run() [async loop, 1s interval]
         │
         ▼
Timer._tick()
    ├─ Execute interval tasks ──────────────────────┐
    └─ Execute due delay tasks ──────────────────┐  │
                                                 │  │
         ┌───────────────────────────────────────┘  │
         │                                          │
         ▼                                          ▼
  Pane delayed display                   StateManager.tick_all()
  callback                                         │
         │                               For each machine:
         ├─ Check state_id                        │
         │  是否过期                               ▼
         │                               PaneStateMachine.
         ├─ 若未过期:                     should_check_long_running()?
         │  Update display                        │
         │  to IDLE                     ├─ Yes: RUNNING && elapsed > 60s
         │                              │
         └─ Fire on_display_            ▼
            change                      Construct timer.check event
                                               │
                                               ▼
                                        StateManager.process_queued()
                                               │
                                               ▼
                                        PaneStateMachine.process()
                                        [T1: RUNNING → LONG_RUNNING]
                                               │
                                               ▼
                                        State change callback
                                        → Pane → Frontend
```

---

## DONE/FAILED → IDLE 延迟显示流程

```
StateChange (to_status = IDLE, from DONE/FAILED)
         │
         ▼
Pane.handle_state_change()
         │
         ├─ Check: old ∈ {DONE, FAILED} && new == IDLE?
         │
         ▼ [Yes]
         │
Pane._register_delayed_display()
         │
         │  Timer.register_delay(name, 5s, callback)
         │  Callback: Update display with state_id check
         │
         └─ Return False (display not updated yet)
                    │
                    │ [After 5 seconds]
                    │
                    ▼
         Timer._tick()
                    │
                    ├─ Check due delays
                    │
                    ▼
         delayed_update() called
                    │
                    ├─ Check if state_id < current (newer event?)
                    │
                    ├─ No: Update display to IDLE
                    │
                    └─ Fire on_display_change → frontend
```

---

## 文件依赖关系图

```
                           config.py
                         (used everywhere)
                               │
         ┌─────────────────────┼─────────────────────┐
         │                     │                     │
         ▼                     ▼                     ▼
    telemetry.py          timer.py           (other modules)
         │                     │
         └──────────┬──────────┘
                    │
                    ▼
              pane/types.py ◄────────────────────────────────────────┐
                    │                                                 │
                    ▼                                                 │
            pane/predicates.py                                        │
                    │                                                 │
                    ▼                                                 │
           pane/transitions.py                                        │
                    │                                                 │
                    ▼                                                 │
         pane/state_machine.py                                        │
                    │                                                 │
                    ▼                                                 │
        pane/queue.py ──────────► pane/pane.py ◄──────── timer.py    │
                    │                    │                            │
                    └────────┬───────────┘                            │
                             ▼                                        │
                    pane/manager.py                                   │
                             │                                        │
           ┌─────────────────┼─────────────────┐                     │
           ▼                 ▼                 ▼                     │
                         iterm/utils.py  hooks/manager.py ───────────┘
                                               │
                                               ▼
                                       supervisor.py
                                       analysis/change_queue.py
                                       analysis/content_cleaner.py


hooks/sources/:
  hooks/sources/base.py ◄─── shell.py, claude_code.py, iterm.py
                              (all inherit from HookSource)

web/:
  web/server.py ◄── web/handlers.py
  web/app.py ◄─────┐
                   └─ Integrates supervisor + hooks

render/:
  render/renderer.py (standalone, converts content to SVG)

iterm/:
  iterm/layout.py, iterm/client.py, iterm/utils.py (utilities)
```

---

## 文件映射表

| 路径 | 职责 |
|------|------|
| `config.py` | 中央常量配置 |
| `telemetry.py` | 日志 + 内存指标 |
| `timer.py` | 异步调度器 (interval/delay) |
| `runtime/bootstrap.py` | 集中组件构造 |
| `supervisor.py` | iTerm2 镜像 + 内容轮询 |
| `pane/types.py` | 核心数据类型 (DTO/enum) |
| `pane/transitions.py` | 状态规则表 |
| `pane/predicates.py` | 规则谓词函数 |
| `pane/state_machine.py` | Per-pane 状态机 |
| `pane/pane.py` | 显示层 (延迟/通知抑制) |
| `pane/queue.py` | Actor queue |
| `pane/manager.py` | StateManager 协调器 |
| `hooks/manager.py` | HookManager facade |
| `hooks/receiver.py` | HTTP API 接收器 |
| `hooks/sources/base.py` | Hook source 基类 |
| `hooks/sources/shell.py` | Shell 命令监控 |
| `hooks/sources/claude_code.py` | Claude Code HTTP 事件 |
| `hooks/sources/iterm.py` | iTerm2 焦点监控 |
| `hooks/sources/prompt_monitor.py` | PromptMonitor 封装 |
| `analysis/content_cleaner.py` | Unicode 内容过滤 |
| `analysis/__init__.py` | 单例管理 (HookManager, Timer) |
| `web/app.py` | App 工厂 & 初始化 |
| `web/server.py` | FastAPI + WebSocket |
| `web/handlers.py` | WebSocket 消息处理 |
| `render/renderer.py` | Terminal → SVG |
| `iterm/layout.py` | Layout 遍历 |
| `iterm/client.py` | iTerm2 API 封装 |
| `iterm/utils.py` | Session ID 规范化 |
| `iterm/naming.py` | Window/tab/pane 命名 |

---

## 关键交互模式

### 1. 事件处理链
```
External Event → Hook Source → HookManager.normalize_event()
  → StateManager.enqueue() → EventQueue (per pane, FIFO)
  → StateManager.process_queued() → PaneStateMachine.process()
  → Rule matching + predicates → StateChange callback
  → Pane.handle_state_change() → DisplayState callback
  → Frontend broadcast
```

### 2. Generation 门控
- 每个 pane 有 `pane_generation` 计数器
- pane 创建/重建时 generation 递增
- generation < current 的事件被丢弃 (过期)
- 防止重建后旧事件干扰

### 3. State ID 排序
- 每次状态变更递增全局 `_state_id_counter`
- Pane 显示层拒绝 state_id < current 的更新
- 防止乱序显示旧状态

### 4. Actor Queue 模式
- 每个 pane 有独立 EventQueue，确保串行处理
- 同一 pane 无并发状态转换
- 防止状态机竞态条件

### 5. 延迟显示机制
- DONE/FAILED → IDLE 时，Pane 注册 Timer 延迟任务
- 显示保持 DONE/FAILED 5 秒
- 状态机内部已转换
- 用户可看到成功/失败结果更长时间
- 避免状态突变

### 6. 通知抑制
- 在 Pane 层检查: `should_suppress_notification()`
- 条件 1: 运行时长 < 3s (快速任务不通知)
- 条件 2: pane 当前 focus
- 结果传递给前端 (服务端处理)

### 7. 内容变化回退
- 若 WAITING_APPROVAL 且内容变化，自动恢复为 RUNNING
- R1 规则响应 `content.changed` 信号

---

## 状态规则（摘录）

| # | from_status | from_source | signal | to_status | to_source | 描述 |
|---|-------------|-------------|--------|-----------|-----------|------|
| S1 | * | * | shell.command_start | RUNNING | shell | 执行: {command:30} |
| S2 | RUNNING\|LONG_RUNNING | shell | shell.command_end(exit=0) | DONE | shell | 命令完成 |
| S3 | RUNNING\|LONG_RUNNING | shell | shell.command_end(exit≠0) | FAILED | shell | 失败 (exit={exit_code}) |
| C1 | * | * | claude-code.SessionStart | RUNNING | claude-code | 会话开始 |
| C2 | * | * | claude-code.PreToolUse | RUNNING | claude-code | 工具: {tool_name:30} |
| C3 | RUNNING\|LONG_RUNNING | claude-code | claude-code.Stop | DONE | claude-code | 已完成回复 |
| C4 | * | * | claude-code.Notification:permission_prompt | WAITING_APPROVAL | claude-code | 需要权限确认 |
| C5 | * | * | claude-code.Notification:idle_prompt | IDLE | claude-code |  |
| C6 | * | * | claude-code.SessionEnd | IDLE | claude-code |  |
| T1 | RUNNING | = | timer.check | LONG_RUNNING | = | 已运行 {elapsed} |
| U1 | WAITING_APPROVAL | * | iterm.focus / frontend.click_pane | IDLE | user | 清空等待 |
| U2 | DONE\|FAILED | * | iterm.focus / frontend.click_pane | IDLE | user | 清空完成/失败 |
| R1 | WAITING_APPROVAL | * | content.changed | RUNNING | = | 内容变化，恢复执行 |

---

## 现存特点与限制

- **状态**：纯内存，重启会丢状态/历史。
- **队列**：ActorQueue generation 过滤 + 丢弃最旧（满 256），打点 `queue.dropped`；state_id 乱序仅在 Pane 显示层防护。
- **Telemetry**：仅内存指标（inc/gauge）；未接 Prometheus/StatsD。
- **内容路径**：PaneChangeQueue 仍在用，尚未迁移到 hooks/sources/content.py；analyzer 兼容层保留但不参与状态决策。
