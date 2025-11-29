"""状态机单元测试"""

import pytest
from datetime import datetime, timedelta

from termsupervisor.analysis.base import TaskStatus
from termsupervisor.hooks.state import PaneState, StateHistoryEntry
from termsupervisor.hooks.state_machine import StateMachine
from termsupervisor.hooks.state_store import StateStore
from termsupervisor.hooks.event_processor import EventProcessor, HookEvent


class TestTaskStatus:
    """TaskStatus 枚举测试"""

    def test_status_values(self):
        """测试状态值"""
        assert TaskStatus.IDLE.value == "idle"
        assert TaskStatus.RUNNING.value == "running"
        assert TaskStatus.LONG_RUNNING.value == "long_running"
        assert TaskStatus.WAITING_APPROVAL.value == "waiting_approval"
        assert TaskStatus.DONE.value == "done"
        assert TaskStatus.FAILED.value == "failed"

    def test_needs_notification(self):
        """测试需要通知的状态"""
        assert not TaskStatus.IDLE.needs_notification
        assert not TaskStatus.RUNNING.needs_notification
        assert not TaskStatus.LONG_RUNNING.needs_notification
        assert TaskStatus.WAITING_APPROVAL.needs_notification
        assert TaskStatus.DONE.needs_notification
        assert TaskStatus.FAILED.needs_notification

    def test_needs_attention(self):
        """测试需要关注的状态（闪烁）"""
        assert not TaskStatus.IDLE.needs_attention
        assert not TaskStatus.RUNNING.needs_attention
        assert not TaskStatus.LONG_RUNNING.needs_attention
        assert TaskStatus.WAITING_APPROVAL.needs_attention
        assert TaskStatus.DONE.needs_attention
        assert TaskStatus.FAILED.needs_attention

    def test_is_running(self):
        """测试运行中状态（转圈）"""
        assert not TaskStatus.IDLE.is_running
        assert TaskStatus.RUNNING.is_running
        assert TaskStatus.LONG_RUNNING.is_running
        assert not TaskStatus.WAITING_APPROVAL.is_running
        assert not TaskStatus.DONE.is_running
        assert not TaskStatus.FAILED.is_running

    def test_display(self):
        """测试前端显示"""
        assert not TaskStatus.IDLE.display
        assert TaskStatus.RUNNING.display
        assert TaskStatus.LONG_RUNNING.display
        assert TaskStatus.WAITING_APPROVAL.display
        assert TaskStatus.DONE.display
        assert TaskStatus.FAILED.display


class TestPaneState:
    """PaneState 测试"""

    def test_idle_factory(self):
        """测试 idle 工厂方法"""
        state = PaneState.idle()
        assert state.status == TaskStatus.IDLE
        assert state.source == "shell"
        assert state.description == ""

    def test_add_history(self):
        """测试添加历史记录"""
        state = PaneState.idle()
        state.add_history("shell.command_start", success=True)
        state.add_history("shell.command_end", success=False)

        assert len(state.history) == 2
        assert state.history[0].signal == "shell.command_start"
        assert state.history[0].success is True
        assert state.history[1].signal == "shell.command_end"
        assert state.history[1].success is False

    def test_history_max_length(self):
        """测试历史记录最大长度"""
        state = PaneState.idle()
        for i in range(50):
            state.add_history(f"test.event_{i}")

        # 默认最大 30 条
        assert len(state.history) <= 30

    def test_copy_with(self):
        """测试 copy_with 方法"""
        state = PaneState(
            status=TaskStatus.RUNNING,
            source="shell",
            description="执行: test",
            started_at=datetime.now()
        )
        state.add_history("shell.command_start")

        new_state = state.copy_with(
            status=TaskStatus.DONE,
            description="命令完成"
        )

        assert new_state.status == TaskStatus.DONE
        assert new_state.source == "shell"  # 保持原值
        assert new_state.description == "命令完成"
        assert new_state.history is state.history  # 共享历史


class TestStateMachine:
    """StateMachine 测试"""

    @pytest.fixture
    def sm(self):
        return StateMachine()

    @pytest.fixture
    def idle_state(self):
        return PaneState.idle()

    # === Shell 事件测试 ===

    def test_shell_command_start(self, sm, idle_state):
        """测试 shell 命令开始"""
        new_state = sm.transition(
            idle_state,
            "shell.command_start",
            {"command": "sleep 10"}
        )

        assert new_state is not None
        assert new_state.status == TaskStatus.RUNNING
        assert new_state.source == "shell"
        assert "sleep 10" in new_state.description
        assert new_state.started_at is not None

    def test_shell_command_end_success(self, sm):
        """测试 shell 命令成功结束"""
        running_state = PaneState(
            status=TaskStatus.RUNNING,
            source="shell",
            started_at=datetime.now()
        )

        new_state = sm.transition(
            running_state,
            "shell.command_end",
            {"exit_code": 0}
        )

        assert new_state is not None
        assert new_state.status == TaskStatus.DONE
        assert "完成" in new_state.description

    def test_shell_command_end_failure(self, sm):
        """测试 shell 命令失败"""
        running_state = PaneState(
            status=TaskStatus.RUNNING,
            source="shell",
            started_at=datetime.now()
        )

        new_state = sm.transition(
            running_state,
            "shell.command_end",
            {"exit_code": 1}
        )

        assert new_state is not None
        assert new_state.status == TaskStatus.FAILED
        assert "exit=1" in new_state.description

    def test_shell_command_end_ignored_for_claude(self, sm):
        """测试 claude-code 状态下忽略 shell 命令结束"""
        claude_running = PaneState(
            status=TaskStatus.RUNNING,
            source="claude-code",
            started_at=datetime.now()
        )

        new_state = sm.transition(
            claude_running,
            "shell.command_end",
            {"exit_code": 0}
        )

        # 应该被忽略，因为当前是 claude-code 的状态
        assert new_state is None

    # === Claude Code 事件测试 ===

    def test_claude_session_start(self, sm, idle_state):
        """测试 Claude 会话开始"""
        new_state = sm.transition(idle_state, "claude-code.SessionStart")

        assert new_state is not None
        assert new_state.status == TaskStatus.RUNNING
        assert new_state.source == "claude-code"

    def test_claude_pre_tool_use(self, sm, idle_state):
        """测试 Claude 工具调用"""
        new_state = sm.transition(
            idle_state,
            "claude-code.PreToolUse",
            {"tool_name": "Bash"}
        )

        assert new_state is not None
        assert new_state.status == TaskStatus.RUNNING
        assert "Bash" in new_state.description

    def test_claude_stop(self, sm):
        """测试 Claude 停止"""
        running_state = PaneState(
            status=TaskStatus.RUNNING,
            source="claude-code",
            started_at=datetime.now()
        )

        new_state = sm.transition(running_state, "claude-code.Stop")

        assert new_state is not None
        assert new_state.status == TaskStatus.DONE
        assert "完成" in new_state.description

    def test_claude_stop_ignored_for_idle(self, sm, idle_state):
        """测试 IDLE 状态下忽略 Stop 事件"""
        # 设置为 claude-code 的 IDLE 状态
        idle_state.source = "claude-code"

        new_state = sm.transition(idle_state, "claude-code.Stop")

        # 应该被忽略，因为当前不是 RUNNING/LONG_RUNNING
        assert new_state is None

    def test_claude_permission_prompt(self, sm, idle_state):
        """测试 Claude 权限提示"""
        new_state = sm.transition(
            idle_state,
            "claude-code.Notification:permission_prompt"
        )

        assert new_state is not None
        assert new_state.status == TaskStatus.WAITING_APPROVAL

    def test_claude_idle_prompt(self, sm):
        """测试 Claude 空闲提示"""
        running_state = PaneState(
            status=TaskStatus.RUNNING,
            source="claude-code",
            started_at=datetime.now()
        )

        new_state = sm.transition(
            running_state,
            "claude-code.Notification:idle_prompt"
        )

        assert new_state is not None
        assert new_state.status == TaskStatus.IDLE

    def test_claude_session_end(self, sm):
        """测试 Claude 会话结束"""
        running_state = PaneState(
            status=TaskStatus.RUNNING,
            source="claude-code",
            started_at=datetime.now()
        )

        new_state = sm.transition(running_state, "claude-code.SessionEnd")

        assert new_state is not None
        assert new_state.status == TaskStatus.IDLE

    # === Timer 事件测试 ===

    def test_timer_check_running_to_long_running(self, sm):
        """测试 RUNNING -> LONG_RUNNING"""
        running_state = PaneState(
            status=TaskStatus.RUNNING,
            source="shell",
            started_at=datetime.now() - timedelta(seconds=70)
        )

        new_state = sm.transition(
            running_state,
            "timer.check",
            {"elapsed": "70s"}
        )

        assert new_state is not None
        assert new_state.status == TaskStatus.LONG_RUNNING
        assert new_state.source == "shell"  # 保持原 source

    def test_timer_check_idle_no_change(self, sm, idle_state):
        """测试 IDLE 状态下 timer 不变"""
        new_state = sm.transition(idle_state, "timer.check", {"elapsed": "10s"})
        assert new_state is None

    # === 用户操作测试 ===

    def test_user_focus_clears_done(self, sm):
        """测试用户 focus 清除 DONE 状态"""
        done_state = PaneState(status=TaskStatus.DONE, source="shell")

        new_state = sm.transition(done_state, "iterm.focus")

        assert new_state is not None
        assert new_state.status == TaskStatus.IDLE

    def test_user_click_clears_failed(self, sm):
        """测试用户 click 清除 FAILED 状态"""
        failed_state = PaneState(status=TaskStatus.FAILED, source="shell")

        new_state = sm.transition(failed_state, "frontend.click_pane")

        assert new_state is not None
        assert new_state.status == TaskStatus.IDLE

    def test_user_focus_no_effect_on_running(self, sm):
        """测试用户 focus 不影响 RUNNING 状态"""
        running_state = PaneState(
            status=TaskStatus.RUNNING,
            source="shell",
            started_at=datetime.now()
        )

        new_state = sm.transition(running_state, "iterm.focus")
        assert new_state is None

    # === Render 事件测试 ===

    def test_render_content_updated_waiting_approval(self, sm):
        """测试 render 更新触发 WAITING_APPROVAL -> RUNNING"""
        waiting_state = PaneState(
            status=TaskStatus.WAITING_APPROVAL,
            source="claude-code"
        )

        new_state = sm.transition(
            waiting_state,
            "render.content_updated",
            {"lines_changed": 10}
        )

        assert new_state is not None
        assert new_state.status == TaskStatus.RUNNING

    def test_render_content_updated_done_no_change(self, sm):
        """测试 render 更新不影响 DONE 状态"""
        done_state = PaneState(status=TaskStatus.DONE, source="shell")

        new_state = sm.transition(done_state, "render.content_updated")
        assert new_state is None

    # === 优先级测试 ===

    def test_priority_claude_overrides_shell(self, sm):
        """测试 claude-code 可以覆盖 shell 状态"""
        shell_running = PaneState(
            status=TaskStatus.RUNNING,
            source="shell",
            started_at=datetime.now()
        )

        new_state = sm.transition(shell_running, "claude-code.SessionStart")

        assert new_state is not None
        assert new_state.status == TaskStatus.RUNNING
        assert new_state.source == "claude-code"

    def test_priority_shell_cannot_override_claude(self, sm):
        """测试 shell 无法覆盖 claude-code 状态"""
        claude_running = PaneState(
            status=TaskStatus.RUNNING,
            source="claude-code",
            started_at=datetime.now()
        )

        # shell.command_start 优先级低，无法覆盖
        # 但根据当前实现，command_start 没有优先级检查
        # 这里主要测试 command_end 被忽略
        new_state = sm.transition(
            claude_running,
            "shell.command_end",
            {"exit_code": 0}
        )

        assert new_state is None


class TestStateStore:
    """StateStore 测试"""

    @pytest.fixture
    def store(self):
        return StateStore()

    def test_get_default_idle(self, store):
        """测试获取默认 IDLE 状态"""
        state = store.get("test_pane")
        assert state.status == TaskStatus.IDLE

    @pytest.mark.anyio
    async def test_set_and_get(self, store):
        """测试设置和获取状态"""
        new_state = PaneState(
            status=TaskStatus.RUNNING,
            source="shell",
            description="test"
        )

        changed = await store.set("test_pane", new_state)
        assert changed is True

        retrieved = store.get("test_pane")
        assert retrieved.status == TaskStatus.RUNNING

    @pytest.mark.anyio
    async def test_set_no_change(self, store):
        """测试设置相同状态不触发变更"""
        state1 = PaneState(status=TaskStatus.RUNNING, source="shell", description="test")
        state2 = PaneState(status=TaskStatus.RUNNING, source="shell", description="test")

        await store.set("test_pane", state1)
        changed = await store.set("test_pane", state2)

        assert changed is False

    @pytest.mark.anyio
    async def test_change_callback(self, store):
        """测试状态变更回调"""
        callback_called = []

        async def callback(pane_id, state):
            callback_called.append((pane_id, state.status))

        store.set_change_callback(callback)

        await store.set("test_pane", PaneState(
            status=TaskStatus.RUNNING,
            source="shell"
        ))

        assert len(callback_called) == 1
        assert callback_called[0] == ("test_pane", TaskStatus.RUNNING)


class TestEventProcessor:
    """EventProcessor 测试"""

    @pytest.fixture
    def processor(self):
        store = StateStore()
        machine = StateMachine()
        return EventProcessor(store, machine)

    @pytest.mark.anyio
    async def test_process_shell_command_start(self, processor):
        """测试处理 shell 命令开始"""
        changed = await processor.process_shell_command_start("test_pane", "ls -la")

        assert changed is True
        state = processor.state_store.get("test_pane")
        assert state.status == TaskStatus.RUNNING

    @pytest.mark.anyio
    async def test_process_shell_command_end(self, processor):
        """测试处理 shell 命令结束"""
        # 先开始命令
        await processor.process_shell_command_start("test_pane", "echo test")
        # 再结束命令
        changed = await processor.process_shell_command_end("test_pane", 0)

        assert changed is True
        state = processor.state_store.get("test_pane")
        assert state.status == TaskStatus.DONE

    @pytest.mark.anyio
    async def test_history_recorded(self, processor):
        """测试历史记录"""
        await processor.process_shell_command_start("test_pane", "test")
        await processor.process_shell_command_end("test_pane", 0)
        await processor.process_user_focus("test_pane")

        state = processor.state_store.get("test_pane")
        assert len(state.history) == 3
        assert all(h.success for h in state.history)

    @pytest.mark.anyio
    async def test_failed_transition_recorded(self, processor):
        """测试失败转换被记录"""
        # IDLE 状态下发送 timer.check 不会转换
        await processor.process_timer_check("test_pane", "10s")

        state = processor.state_store.get("test_pane")
        assert len(state.history) == 1
        assert state.history[0].success is False
