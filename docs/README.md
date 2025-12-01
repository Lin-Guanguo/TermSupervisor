# Mnema - TermSupervisor 项目文档

Last Updated: 2025-12-01

## 文件列表

| 文件 | 描述 |
|------|------|
| `architecture.md` | **当前架构**：文件结构、模块调用关系图、数据流、状态机、配置项 |
| `_root_AGENTS.md` | 项目 Agent 配置说明 |
| `content-heuristic.md` | Content-based heuristic to clear RUNNING/LONG_RUNNING panes without `command_end` hooks |
| `state-machine-design.md` | **设计讨论**：状态机设计、事件清单、状态消失规则、优先级覆盖 |
| `hook-system-design.md` | Hook 系统设计：接收外部工具状态事件，支持 Claude Code 等多种 Hook 源 |
| `notification-refresh-refactor.md` | ~~重构完成~~（已过时，被 architecture.md 取代） |
| `task-detection-improvements.md` | 任务状态检测改进方案：规则引擎/LLM 分析、Toast 通知、状态确认 |

## state-architecture/ 目录

状态管理架构相关文档：

| 文件 | 描述 |
|------|------|
| `state-architecture.md` | **主文档**：当前实现 + 改进计划 |
| `refactor_plan.md` | 重构计划总览：5 步实施计划 |
| `refactor_01_timer.md` | Step 1: Timer 模块 |
| `refactor_02_transitions.md` | Step 2: 流转表 + PaneStateMachine |
| `refactor_03_pane.md` | Step 3: Pane 类 |
| `refactor_04_manager.md` | Step 4: PaneManager + 集成 + 持久化 |
| `refactor_05_cleanup.md` | Step 5: 清理旧代码 + 测试 |
