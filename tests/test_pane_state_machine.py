"""PaneStateMachine 测试"""

import pytest

from termsupervisor.state import (
    HookEvent,
    PaneStateMachine,
    StateChange,
    TaskStatus,
)
from termsupervisor.telemetry import metrics


@pytest.fixture
def machine():
    """创建测试用状态机"""
    return PaneStateMachine(pane_id="test-pane-123")


@pytest.fixture(autouse=True)
def reset_metrics():
    """每次测试前重置指标"""
    metrics.reset()
    yield
    metrics.reset()


class TestShellTransitions:
    """Shell 事件流转测试"""

    def test_command_start_from_idle(self, machine):
        """S1: IDLE → RUNNING (shell.command_start)"""
        event = HookEvent(
            source="shell",
            pane_id="test-pane-123",
            event_type="command_start",
            data={"command": "ls -la"},
            pane_generation=1,
        )

        result = machine.process(event)

        assert result is not None  # StateChange 返回
        assert isinstance(result, StateChange)
        assert result.new_status == TaskStatus.RUNNING
        assert machine.status == TaskStatus.RUNNING
        assert machine.source == "shell"
        assert machine.description == "执行: ls -la"
        assert machine.started_at is not None

    def test_command_end_success(self, machine):
        """S2: RUNNING → DONE (exit_code=0)"""
        # 先执行命令
        machine.process(
            HookEvent(
                source="shell",
                pane_id="test-pane-123",
                event_type="command_start",
                data={"command": "ls"},
                pane_generation=1,
            )
        )

        # 命令成功结束
        event = HookEvent(
            source="shell",
            pane_id="test-pane-123",
            event_type="command_end",
            data={"exit_code": 0},
            pane_generation=1,
        )

        result = machine.process(event)

        assert result is not None
        assert machine.status == TaskStatus.DONE
        assert machine.source == "shell"

    def test_command_end_failure(self, machine):
        """S3: RUNNING → FAILED (exit_code≠0)"""
        machine.process(
            HookEvent(
                source="shell",
                pane_id="test-pane-123",
                event_type="command_start",
                data={"command": "false"},
                pane_generation=1,
            )
        )

        event = HookEvent(
            source="shell",
            pane_id="test-pane-123",
            event_type="command_end",
            data={"exit_code": 1},
            pane_generation=1,
        )

        result = machine.process(event)

        assert result is not None
        assert machine.status == TaskStatus.FAILED
        assert "exit=1" in machine.description

    def test_command_end_ignored_when_not_shell_source(self, machine):
        """shell.command_end 只处理 shell source 的 RUNNING"""
        # Claude 发起的 RUNNING
        machine.process(
            HookEvent(
                source="claude-code",
                pane_id="test-pane-123",
                event_type="SessionStart",
                pane_generation=1,
            )
        )
        assert machine.source == "claude-code"

        # shell.command_end 应该被忽略
        event = HookEvent(
            source="shell",
            pane_id="test-pane-123",
            event_type="command_end",
            data={"exit_code": 0},
            pane_generation=1,
        )

        result = machine.process(event)

        assert result is None
        assert machine.status == TaskStatus.RUNNING  # 状态未变


class TestClaudeCodeTransitions:
    """Claude Code 事件流转测试"""

    def test_session_start(self, machine):
        """C1: * → RUNNING (SessionStart)"""
        event = HookEvent(
            source="claude-code",
            pane_id="test-pane-123",
            event_type="SessionStart",
            pane_generation=1,
        )

        result = machine.process(event)

        assert result is not None
        assert machine.status == TaskStatus.RUNNING
        assert machine.source == "claude-code"

    def test_pre_tool_use(self, machine):
        """C2: * → RUNNING (PreToolUse)"""
        event = HookEvent(
            source="claude-code",
            pane_id="test-pane-123",
            event_type="PreToolUse",
            data={"tool_name": "Read"},
            pane_generation=1,
        )

        result = machine.process(event)

        assert result is not None
        assert machine.status == TaskStatus.RUNNING
        assert "Read" in machine.description

    def test_pre_tool_use_same_source_no_reset_started_at(self, machine):
        """C2: PreToolUse 同源时不重置 started_at"""
        # 第一个工具
        machine.process(
            HookEvent(
                source="claude-code",
                pane_id="test-pane-123",
                event_type="PreToolUse",
                data={"tool_name": "Read"},
                pane_generation=1,
            )
        )
        first_started_at = machine.started_at

        # 等一小段时间
        import time

        time.sleep(0.01)

        # 第二个工具
        machine.process(
            HookEvent(
                source="claude-code",
                pane_id="test-pane-123",
                event_type="PreToolUse",
                data={"tool_name": "Write"},
                pane_generation=1,
            )
        )

        # started_at 应该保持不变
        assert machine.started_at == first_started_at

    def test_stop(self, machine):
        """C3: RUNNING → DONE (Stop)"""
        machine.process(
            HookEvent(
                source="claude-code",
                pane_id="test-pane-123",
                event_type="SessionStart",
                pane_generation=1,
            )
        )

        event = HookEvent(
            source="claude-code",
            pane_id="test-pane-123",
            event_type="Stop",
            pane_generation=1,
        )

        result = machine.process(event)

        assert result is not None
        assert machine.status == TaskStatus.DONE

    def test_permission_prompt(self, machine):
        """C4: * → WAITING_APPROVAL"""
        event = HookEvent(
            source="claude-code",
            pane_id="test-pane-123",
            event_type="Notification:permission_prompt",
            pane_generation=1,
        )

        result = machine.process(event)

        assert result is not None
        assert machine.status == TaskStatus.WAITING_APPROVAL

    def test_idle_prompt(self, machine):
        """C5: * → IDLE"""
        machine.process(
            HookEvent(
                source="claude-code",
                pane_id="test-pane-123",
                event_type="SessionStart",
                pane_generation=1,
            )
        )

        event = HookEvent(
            source="claude-code",
            pane_id="test-pane-123",
            event_type="Notification:idle_prompt",
            pane_generation=1,
        )

        result = machine.process(event)

        assert result is not None
        assert machine.status == TaskStatus.IDLE

    def test_session_end(self, machine):
        """C6: * → IDLE"""
        machine.process(
            HookEvent(
                source="claude-code",
                pane_id="test-pane-123",
                event_type="SessionStart",
                pane_generation=1,
            )
        )

        event = HookEvent(
            source="claude-code",
            pane_id="test-pane-123",
            event_type="SessionEnd",
            pane_generation=1,
        )

        result = machine.process(event)

        assert result is not None
        assert machine.status == TaskStatus.IDLE


class TestUserTransitions:
    """用户操作流转测试"""

    def test_user_clear_waiting_focus(self, machine):
        """U1: WAITING → IDLE (iterm.focus)"""
        machine.process(
            HookEvent(
                source="claude-code",
                pane_id="test-pane-123",
                event_type="Notification:permission_prompt",
                pane_generation=1,
            )
        )

        event = HookEvent(
            source="iterm",
            pane_id="test-pane-123",
            event_type="focus",
            pane_generation=1,
        )

        result = machine.process(event)

        assert result is not None
        assert machine.status == TaskStatus.IDLE
        assert machine.source == "user"

    def test_user_clear_done_click(self, machine):
        """U2: DONE → IDLE (frontend.click_pane)"""
        # 进入 DONE 状态
        machine.process(
            HookEvent(
                source="shell",
                pane_id="test-pane-123",
                event_type="command_start",
                data={"command": "ls"},
                pane_generation=1,
            )
        )
        machine.process(
            HookEvent(
                source="shell",
                pane_id="test-pane-123",
                event_type="command_end",
                data={"exit_code": 0},
                pane_generation=1,
            )
        )
        assert machine.status == TaskStatus.DONE

        event = HookEvent(
            source="frontend",
            pane_id="test-pane-123",
            event_type="click_pane",
            pane_generation=1,
        )

        result = machine.process(event)

        assert result is not None
        assert machine.status == TaskStatus.IDLE


class TestContentTransitions:
    """内容变化流转测试"""

    def test_content_update_from_other_states_ignored(self, machine):
        """content.update 只在 WAITING_APPROVAL 时触发"""
        # IDLE 状态
        event = HookEvent(
            source="content",
            pane_id="test-pane-123",
            event_type="update",
            pane_generation=1,
        )

        result = machine.process(event)

        assert result is None
        assert machine.status == TaskStatus.IDLE


class TestTimerTransitions:
    """Timer 流转测试"""

    def test_timer_check_running_to_long_running(self, machine):
        """T1: RUNNING → LONG_RUNNING (timer.check)"""
        machine.process(
            HookEvent(
                source="shell",
                pane_id="test-pane-123",
                event_type="command_start",
                data={"command": "sleep 100"},
                pane_generation=1,
            )
        )
        original_source = machine.source

        event = HookEvent(
            source="timer",
            pane_id="test-pane-123",
            event_type="check",
            data={"elapsed": "1m 5s"},
            pane_generation=1,
        )

        result = machine.process(event)

        assert result is not None
        assert machine.status == TaskStatus.LONG_RUNNING
        # source 保持不变
        assert machine.source == original_source


class TestStickyLongRunning:
    """Sticky LONG_RUNNING 测试（Phase 1）"""

    def test_long_running_ignores_same_source_shell_command_start(self, machine):
        """LONG_RUNNING 忽略同源 shell.command_start"""
        # 进入 shell RUNNING
        machine.process(
            HookEvent(
                source="shell",
                pane_id="test-pane-123",
                event_type="command_start",
                data={"command": "sleep 100"},
                pane_generation=1,
            )
        )
        # 手动升级到 LONG_RUNNING
        machine.process(
            HookEvent(
                source="timer",
                pane_id="test-pane-123",
                event_type="check",
                data={"elapsed": "1m 5s"},
                pane_generation=1,
            )
        )
        assert machine.status == TaskStatus.LONG_RUNNING
        assert machine.source == "shell"

        # 同源 shell.command_start 应该被忽略
        result = machine.process(
            HookEvent(
                source="shell",
                pane_id="test-pane-123",
                event_type="command_start",
                data={"command": "ls"},
                pane_generation=1,
            )
        )

        assert result is None
        assert machine.status == TaskStatus.LONG_RUNNING

    def test_long_running_ignores_same_source_claude_session_start(self, machine):
        """LONG_RUNNING 忽略同源 claude-code.SessionStart"""
        # 进入 claude-code RUNNING
        machine.process(
            HookEvent(
                source="claude-code",
                pane_id="test-pane-123",
                event_type="SessionStart",
                pane_generation=1,
            )
        )
        # 手动升级到 LONG_RUNNING
        machine.process(
            HookEvent(
                source="timer",
                pane_id="test-pane-123",
                event_type="check",
                data={"elapsed": "1m 5s"},
                pane_generation=1,
            )
        )
        assert machine.status == TaskStatus.LONG_RUNNING
        assert machine.source == "claude-code"

        # 同源 SessionStart 应该被忽略
        result = machine.process(
            HookEvent(
                source="claude-code",
                pane_id="test-pane-123",
                event_type="SessionStart",
                pane_generation=1,
            )
        )

        assert result is None
        assert machine.status == TaskStatus.LONG_RUNNING

    def test_long_running_ignores_same_source_pre_tool_use(self, machine):
        """LONG_RUNNING 忽略同源 claude-code.PreToolUse"""
        # 进入 claude-code RUNNING
        machine.process(
            HookEvent(
                source="claude-code",
                pane_id="test-pane-123",
                event_type="SessionStart",
                pane_generation=1,
            )
        )
        # 手动升级到 LONG_RUNNING
        machine.process(
            HookEvent(
                source="timer",
                pane_id="test-pane-123",
                event_type="check",
                data={"elapsed": "1m 5s"},
                pane_generation=1,
            )
        )
        assert machine.status == TaskStatus.LONG_RUNNING

        # 同源 PreToolUse 应该被忽略
        result = machine.process(
            HookEvent(
                source="claude-code",
                pane_id="test-pane-123",
                event_type="PreToolUse",
                data={"tool_name": "Read"},
                pane_generation=1,
            )
        )

        assert result is None
        assert machine.status == TaskStatus.LONG_RUNNING

    def test_long_running_allows_cross_source_command_start(self, machine):
        """LONG_RUNNING 允许跨源 command_start"""
        # 进入 shell LONG_RUNNING
        machine.process(
            HookEvent(
                source="shell",
                pane_id="test-pane-123",
                event_type="command_start",
                data={"command": "sleep 100"},
                pane_generation=1,
            )
        )
        machine.process(
            HookEvent(
                source="timer",
                pane_id="test-pane-123",
                event_type="check",
                data={"elapsed": "1m 5s"},
                pane_generation=1,
            )
        )
        assert machine.status == TaskStatus.LONG_RUNNING
        assert machine.source == "shell"

        # 跨源 claude-code.SessionStart 应该成功
        result = machine.process(
            HookEvent(
                source="claude-code",
                pane_id="test-pane-123",
                event_type="SessionStart",
                pane_generation=1,
            )
        )

        assert result is not None
        assert machine.status == TaskStatus.RUNNING
        assert machine.source == "claude-code"

    def test_long_running_allows_stop(self, machine):
        """LONG_RUNNING 允许 Stop 信号"""
        # 进入 claude-code LONG_RUNNING
        machine.process(
            HookEvent(
                source="claude-code",
                pane_id="test-pane-123",
                event_type="SessionStart",
                pane_generation=1,
            )
        )
        machine.process(
            HookEvent(
                source="timer",
                pane_id="test-pane-123",
                event_type="check",
                data={"elapsed": "1m 5s"},
                pane_generation=1,
            )
        )
        assert machine.status == TaskStatus.LONG_RUNNING

        # Stop 应该成功
        result = machine.process(
            HookEvent(
                source="claude-code",
                pane_id="test-pane-123",
                event_type="Stop",
                pane_generation=1,
            )
        )

        assert result is not None
        assert machine.status == TaskStatus.DONE


class TestGenerationCheck:
    """Generation 检查测试"""

    def test_stale_generation_rejected(self, machine):
        """旧 generation 事件被拒绝"""
        # 递增 generation
        machine.increment_generation()
        assert machine.pane_generation == 2

        # 发送旧 generation 的事件
        event = HookEvent(
            source="shell",
            pane_id="test-pane-123",
            event_type="command_start",
            data={"command": "ls"},
            pane_generation=1,  # 旧的
        )

        result = machine.process(event)

        assert result is None
        assert machine.status == TaskStatus.IDLE  # 状态未变


class TestStateId:
    """state_id 测试"""

    def test_state_id_increments_on_transition(self, machine):
        """状态转换时 state_id 递增"""
        initial_id = machine.state_id

        machine.process(
            HookEvent(
                source="shell",
                pane_id="test-pane-123",
                event_type="command_start",
                data={"command": "ls"},
                pane_generation=1,
            )
        )

        assert machine.state_id > initial_id

    def test_state_id_unchanged_on_failed_transition(self, machine):
        """转换失败时 state_id 不变"""
        initial_id = machine.state_id

        # 尝试无效的转换
        machine.process(
            HookEvent(
                source="content",
                pane_id="test-pane-123",
                event_type="changed",
                pane_generation=1,
            )
        )

        assert machine.state_id == initial_id


class TestHistory:
    """历史记录测试"""

    def test_history_records_transitions(self, machine):
        """历史记录包含转换"""
        machine.process(
            HookEvent(
                source="shell",
                pane_id="test-pane-123",
                event_type="command_start",
                data={"command": "ls"},
                pane_generation=1,
            )
        )

        history = machine.history
        assert len(history) == 1
        assert history[0].signal == "shell.command_start"
        assert history[0].success is True

    def test_history_records_failed_transitions(self, machine):
        """历史记录包含失败的转换"""
        machine.process(
            HookEvent(
                source="content",
                pane_id="test-pane-123",
                event_type="changed",
                pane_generation=1,
            )
        )

        history = machine.history
        assert len(history) == 1
        assert history[0].success is False
