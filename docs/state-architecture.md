# 状态架构（当前实现）

描述当前代码中的状态管线、模块边界与关键数据流。所有内容基于 `src/termsupervisor/` 现有代码，不是计划稿。

## 总览

- 事件入口：Shell PromptMonitor、Claude Code HTTP、iTerm Focus 防抖（2s）、内容变化（polling → PaneChangeQueue → content.changed）。
- 处理链：HookManager → StateManager（per-pane ActorQueue）→ PaneStateMachine（规则/历史/state_id）→ Pane 显示层（延迟 + 通知抑制）。
- 定时：Timer 统一承担 LONG_RUNNING 检测（1s tick）与 DONE/FAILED → IDLE 显示延迟任务。
- 输出：WebSocket 广播 DisplayState + layout；前端基于状态决定边框/闪烁/提示。

## 模块示意

```
Signal Sources (shell | claude-code | iterm.focus | content.changed | timer.check)
        │
        ▼
┌──────────────────────────┐
│       HookManager        │ normalize generation/time, enqueue
└───────────┬──────────────┘
            ▼
┌──────────────────────────┐
│      StateManager        │ per-pane ActorQueue, LONG_RUNNING tick
└──────┬───────────┬──────┘
       │           │
       ▼           ▼
┌────────────────┐ ┌────────────────┐
│ PaneStateMachine│ │     Pane       │
│ rules/history   │ │ display delay/ │
│ state_id/pred   │ │ notification   │
└────────────────┘ └────────────────┘
            │                │
            └─────Timer──────┘ (interval + delay tasks)
                     │
                     ▼
                WebSocket/UI
```

## 文件映射

- Hook 管线：`hooks/manager.py`（事件规范化、入队）、`hooks/receiver.py`（HTTP）、`hooks/sources/{shell,claude_code,iterm}.py`。
- 状态层：`pane/manager.py`（StateManager + ActorQueue/generation）、`pane/state_machine.py`（规则执行 + history）、`pane/transitions.py`（规则表）、`pane/predicates.py`（谓词）、`pane/types.py`（DTO/enum）。
- 显示层：`pane/pane.py`（延迟展示、通知抑制、content hash）、`timer.py`（interval/delay 调度）、`telemetry.py`（日志+内存指标）。
- 内容链路：`supervisor.py`（1s 轮询 iTerm2，ContentCleaner + PaneChangeQueue 节流，刷新时发 `content.changed` 并更新 layout）、`analysis/content_cleaner.py`。
- 持久化：`pane/persistence.py`（v2 + checksum + temp/rename；实现存在但运行流程未调用 save/load）。

## 关键数据流

### 1) 命令执行
```
shell.command_start → HookManager._normalize_event → StateManager.enqueue
  → ActorQueue 串行 → PaneStateMachine (S1) RUNNING + state_id++
  → Pane 更新显示，立即广播
shell.command_end(exit) → ... → PaneStateMachine (S2/S3) DONE/FAILED
  → Pane 显示 DONE/FAILED，若随后 focus/click → state 变 IDLE，显示延迟 5s（Timer）
```

### 2) Claude 权限/工具链
```
claude-code.Notification:permission_prompt → WAITING_APPROVAL
content.changed（轮询触发）→ Pane 更新内容 → 若当前 WAITING_APPROVAL，规则 R1 将状态恢复 RUNNING（源保持 claude-code）
claude-code.PreToolUse / Stop / SessionEnd 按表流转，PreToolUse 同源不重置 started_at
```

### 3) LONG_RUNNING
```
Timer 每 1s 调用 StateManager.tick_all()
  对 RUNNING 且 elapsed>60s 生成 timer.check → PaneStateMachine (T1) → LONG_RUNNING
```

### 4) 通知抑制与延迟展示
- Pane 仅在 DONE/FAILED 显示状态时检查抑制：运行时长 <3s 或 pane 正在 focus → 抑制通知。
- DONE/FAILED → IDLE 时，显示层延迟 5s；期间若有更高 state_id 更新则跳过延迟任务。

### 5) 内容刷新链路（当前实现）
```
iTerm2 屏幕 → ContentCleaner.clean → PaneChangeQueue.check_and_record
  ├─ 阈值满足 → SVG 刷新 + hook_manager.process_content_changed(content, hash)
  └─ 阈值不满足 → 仅更新队尾/历史
```
PaneChangeQueue 仍保留在 `models.py` + `supervisor.py`，作为节流与 diff 日志；内容 hook 尚未拆到 hooks/sources/content.py。

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

## 现存特点与限制

- 持久化：v2 + checksum 已实现（`pane/persistence.py`），但运行时未调用 save/load，重启会丢状态/历史。
- 队列：ActorQueue generation 过滤 + 丢弃最旧（满 256），打点 `queue.dropped`；state_id 乱序仅在 Pane 显示层防护。
- Telemetry：仅内存指标（inc/gauge）；未接 Prometheus/StatsD。
- 内容路径：PaneChangeQueue 仍在用，尚未迁移到 hooks/sources/content.py；analyzer 兼容层保留但不参与状态决策。
