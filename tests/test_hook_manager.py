"""HookManager 测试"""

import pytest
from unittest.mock import MagicMock

from termsupervisor.pane import TaskStatus
from termsupervisor.hooks.manager import HookManager
from termsupervisor.timer import Timer
from termsupervisor.telemetry import metrics


@pytest.fixture
def timer():
    """创建测试用 Timer"""
    return Timer(tick_interval=0.05)


@pytest.fixture
def manager(timer):
    """创建测试用 HookManager"""
    return HookManager(timer=timer)


@pytest.fixture(autouse=True)
def reset_metrics():
    """每次测试前重置指标"""
    metrics.reset()
    yield
    metrics.reset()


class TestShellEvents:
    """Shell 事件测试"""

    async def test_shell_command_start(self, manager):
        """处理 shell 命令开始"""
        result = await manager.process_shell_command_start("test-pane", "ls -la")

        assert result is True
        assert manager.get_status("test-pane") == TaskStatus.RUNNING

    async def test_shell_command_end_success(self, manager):
        """处理 shell 命令成功结束"""
        await manager.process_shell_command_start("test-pane", "ls")
        result = await manager.process_shell_command_end("test-pane", 0)

        assert result is True
        assert manager.get_status("test-pane") == TaskStatus.DONE

    async def test_shell_command_end_failure(self, manager):
        """处理 shell 命令失败结束"""
        await manager.process_shell_command_start("test-pane", "false")
        result = await manager.process_shell_command_end("test-pane", 1)

        assert result is True
        assert manager.get_status("test-pane") == TaskStatus.FAILED


class TestClaudeCodeEvents:
    """Claude Code 事件测试"""

    async def test_session_start(self, manager):
        """处理 Claude Code 会话开始"""
        result = await manager.process_claude_code_event(
            "test-pane", "SessionStart"
        )

        assert result is True
        assert manager.get_status("test-pane") == TaskStatus.RUNNING

    async def test_pre_tool_use(self, manager):
        """处理 Claude Code PreToolUse"""
        result = await manager.process_claude_code_event(
            "test-pane", "PreToolUse", {"tool_name": "Read"}
        )

        assert result is True
        assert manager.get_status("test-pane") == TaskStatus.RUNNING

    async def test_stop(self, manager):
        """处理 Claude Code Stop"""
        await manager.process_claude_code_event("test-pane", "PreToolUse")
        result = await manager.process_claude_code_event("test-pane", "Stop")

        assert result is True
        assert manager.get_status("test-pane") == TaskStatus.DONE

    async def test_permission_prompt(self, manager):
        """处理 Claude Code 权限提示"""
        result = await manager.process_claude_code_event(
            "test-pane", "Notification:permission_prompt"
        )

        assert result is True
        assert manager.get_status("test-pane") == TaskStatus.WAITING_APPROVAL

    async def test_event_type_normalization(self, manager):
        """事件类型规范化"""
        # 小写 stop 应该被转换为 Stop
        await manager.process_claude_code_event("test-pane", "pre_tool_use")
        assert manager.get_status("test-pane") == TaskStatus.RUNNING

        await manager.process_claude_code_event("test-pane", "stop")
        assert manager.get_status("test-pane") == TaskStatus.DONE


class TestUserEvents:
    """用户事件测试"""

    async def test_user_focus(self, manager):
        """处理用户 focus 事件"""
        # WAITING_APPROVAL → IDLE
        await manager.process_claude_code_event(
            "test-pane", "Notification:permission_prompt"
        )
        assert manager.get_status("test-pane") == TaskStatus.WAITING_APPROVAL

        result = await manager.process_user_focus("test-pane")
        assert result is True
        assert manager.get_status("test-pane") == TaskStatus.IDLE

    async def test_user_click(self, manager):
        """处理用户点击事件"""
        # DONE → IDLE
        await manager.process_shell_command_start("test-pane", "ls")
        await manager.process_shell_command_end("test-pane", 0)
        assert manager.get_status("test-pane") == TaskStatus.DONE

        result = await manager.process_user_click("test-pane")
        assert result is True
        assert manager.get_status("test-pane") == TaskStatus.IDLE


class TestContentEvents:
    """内容事件测试"""

    async def test_content_changed_updates_pane(self, manager):
        """content.changed 更新 Pane 内容"""
        await manager.process_content_changed(
            "test-pane",
            content="new content",
            content_hash="hash123",
        )

        state = manager.get_state("test-pane")
        # 注意：content_changed 本身不改变状态，只更新内容
        # 状态应该是 IDLE
        assert manager.get_status("test-pane") == TaskStatus.IDLE

    async def test_content_changed_waiting_to_running(self, manager):
        """content.changed 在 WAITING 时触发兜底恢复"""
        # 先进入 WAITING 状态
        await manager.process_claude_code_event(
            "test-pane", "Notification:permission_prompt"
        )
        assert manager.get_status("test-pane") == TaskStatus.WAITING_APPROVAL

        # content.changed 应该触发兜底恢复
        await manager.process_content_changed(
            "test-pane",
            content="output",
            content_hash="hash456",
        )
        assert manager.get_status("test-pane") == TaskStatus.RUNNING


class TestCallback:
    """回调测试"""

    async def test_change_callback_called(self, manager):
        """状态变更时调用回调"""
        changes = []

        def callback(pane_id, status, description, source, suppressed):
            changes.append({
                "pane_id": pane_id,
                "status": status,
                "source": source,
                "suppressed": suppressed,
            })

        manager.set_change_callback(callback)

        await manager.process_shell_command_start("test-pane", "ls")

        assert len(changes) == 1
        assert changes[0]["pane_id"] == "test-pane"
        assert changes[0]["status"] == TaskStatus.RUNNING


class TestStateQuery:
    """状态查询测试"""

    async def test_get_status(self, manager):
        """获取状态"""
        assert manager.get_status("test-pane") == TaskStatus.IDLE

        await manager.process_shell_command_start("test-pane", "ls")
        assert manager.get_status("test-pane") == TaskStatus.RUNNING

    async def test_get_reason(self, manager):
        """获取状态描述"""
        await manager.process_shell_command_start("test-pane", "echo hello")
        reason = manager.get_reason("test-pane")
        assert "echo hello" in reason or "执行" in reason

    async def test_get_active_source(self, manager):
        """获取当前来源"""
        await manager.process_shell_command_start("test-pane", "ls")
        assert manager.get_active_source("test-pane") == "shell"

        await manager.process_claude_code_event("test-pane", "PreToolUse")
        assert manager.get_active_source("test-pane") == "claude-code"

    async def test_get_all_panes(self, manager):
        """获取所有 pane"""
        await manager.process_shell_command_start("pane-1", "ls")
        await manager.process_shell_command_start("pane-2", "pwd")

        panes = manager.get_all_panes()
        assert "pane-1" in panes
        assert "pane-2" in panes

    async def test_get_all_states(self, manager):
        """获取所有状态"""
        await manager.process_shell_command_start("pane-1", "ls")
        await manager.process_claude_code_event("pane-2", "PreToolUse")

        states = manager.get_all_states()
        assert "pane-1" in states
        assert "pane-2" in states


class TestGeneration:
    """Generation 测试"""

    async def test_get_generation(self, manager):
        """获取 generation"""
        await manager.process_shell_command_start("test-pane", "ls")
        gen = manager.get_generation("test-pane")
        assert gen >= 1

    async def test_increment_generation(self, manager):
        """递增 generation"""
        await manager.process_shell_command_start("test-pane", "ls")
        old_gen = manager.get_generation("test-pane")
        new_gen = manager.increment_generation("test-pane")
        assert new_gen == old_gen + 1


class TestCleanup:
    """清理测试"""

    async def test_remove_pane(self, manager):
        """移除 pane"""
        await manager.process_shell_command_start("test-pane", "ls")
        assert "test-pane" in manager.get_all_panes()

        manager.remove_pane("test-pane")
        assert "test-pane" not in manager.get_all_panes()

    async def test_clear_all(self, manager):
        """清除所有状态"""
        await manager.process_shell_command_start("pane-1", "ls")
        await manager.process_shell_command_start("pane-2", "pwd")

        manager.clear_all()
        assert len(manager.get_all_panes()) == 0

    async def test_cleanup_closed_panes(self, manager):
        """清理已关闭的 pane"""
        await manager.process_shell_command_start("pane-1", "ls")
        await manager.process_shell_command_start("pane-2", "pwd")
        await manager.process_shell_command_start("pane-3", "cd")

        # pane-2 关闭了
        closed = manager.cleanup_closed_panes({"pane-1", "pane-3"})

        assert "pane-2" in closed
        assert "pane-2" not in manager.get_all_panes()


class TestLongRunning:
    """LONG_RUNNING 测试"""

    async def test_tick_all_triggers_long_running(self, manager):
        """tick_all 触发 LONG_RUNNING"""
        await manager.process_shell_command_start("test-pane", "sleep 100")

        # 手动设置 started_at 到过去
        import time
        machine = manager.state_manager.get_machine("test-pane")
        machine._started_at = time.time() - 100  # 100秒前

        # tick_all 应该触发
        triggered = manager.tick_all()

        assert "test-pane" in triggered
        assert manager.get_status("test-pane") == TaskStatus.LONG_RUNNING
