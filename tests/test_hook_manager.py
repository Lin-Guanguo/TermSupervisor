"""HookManager 测试"""

import pytest

from termsupervisor.hooks.manager import HookManager
from termsupervisor.state import TaskStatus
from termsupervisor.telemetry import metrics


@pytest.fixture
def manager():
    """创建测试用 HookManager"""
    return HookManager()


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
        result = await manager.process_claude_code_event("test-pane", "SessionStart")

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
        await manager.process_claude_code_event("test-pane", "Notification:permission_prompt")
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

    async def test_content_update_updates_pane(self, manager):
        """content.update 更新 Pane 内容"""
        await manager.process_content_update(
            "test-pane",
            content="new content",
            content_hash="hash123",
        )

        # 注意：content_update 本身不改变状态，只更新内容
        # 状态应该是 IDLE
        _ = manager.get_state("test-pane")  # verify state exists
        assert manager.get_status("test-pane") == TaskStatus.IDLE

    async def test_content_changed_compat(self, manager):
        """content.changed 兼容方法仍可用"""
        # 旧的 process_content_changed 方法应该仍然有效
        await manager.process_content_changed(
            "test-pane",
            content="compat test",
            content_hash="compat123",
        )
        assert manager.get_status("test-pane") == TaskStatus.IDLE


class TestCallback:
    """回调测试"""

    async def test_change_callback_called(self, manager):
        """状态变更时调用回调"""
        changes = []

        async def callback(pane_id, status, description, source):
            changes.append(
                {
                    "pane_id": pane_id,
                    "status": status,
                    "source": source,
                }
            )

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


class TestEmitEvent:
    """emit_event 统一入口测试"""

    async def test_emit_event_basic(self, manager):
        """emit_event 基本功能"""
        result = await manager.emit_event(
            source="shell",
            pane_id="test-pane",
            event_type="command_start",
            data={"command": "test"},
        )
        assert result is True
        assert manager.get_status("test-pane") == TaskStatus.RUNNING

    async def test_emit_event_metrics(self, manager):
        """emit_event 递增指标"""
        await manager.emit_event(
            source="shell",
            pane_id="test-pane",
            event_type="command_start",
            data={"command": "ls"},
        )
        count = metrics.get_counter(
            "hooks.events_total",
            labels={"source": "shell", "event_type": "command_start"},
        )
        assert count >= 1

    async def test_emit_event_no_log(self, manager):
        """emit_event log=False 不记录日志"""
        # 这主要验证不抛异常，日志禁用由 log=False 控制
        result = await manager.emit_event(
            source="content",
            pane_id="test-pane",
            event_type="changed",
            data={},
            log=False,
        )
        assert result is True

    async def test_emit_event_custom_log_level(self, manager):
        """emit_event 自定义日志级别"""
        import logging

        result = await manager.emit_event(
            source="shell",
            pane_id="test-pane",
            event_type="command_start",
            data={"command": "test"},
            log_level=logging.DEBUG,
        )
        assert result is True

    async def test_process_methods_delegate_to_emit_event(self, manager):
        """process_* 方法委托给 emit_event"""
        # 验证指标累加证明确实走了 emit_event
        await manager.process_shell_command_start("pane-1", "ls")
        await manager.process_shell_command_end("pane-1", 0)
        await manager.process_claude_code_event("pane-2", "SessionStart")
        await manager.process_user_focus("pane-3")
        await manager.process_user_click("pane-4")
        await manager.process_content_update("pane-5", "content", "hash")  # renamed from changed

        # 检查指标被记录
        shell_start = metrics.get_counter(
            "hooks.events_total",
            labels={"source": "shell", "event_type": "command_start"},
        )
        shell_end = metrics.get_counter(
            "hooks.events_total",
            labels={"source": "shell", "event_type": "command_end"},
        )
        claude = metrics.get_counter(
            "hooks.events_total",
            labels={"source": "claude-code", "event_type": "SessionStart"},
        )
        iterm = metrics.get_counter(
            "hooks.events_total",
            labels={"source": "iterm", "event_type": "focus"},
        )
        frontend = metrics.get_counter(
            "hooks.events_total",
            labels={"source": "frontend", "event_type": "click_pane"},
        )
        content = metrics.get_counter(
            "hooks.events_total",
            labels={"source": "content", "event_type": "update"},  # renamed from changed
        )

        assert shell_start >= 1
        assert shell_end >= 1
        assert claude >= 1
        assert iterm >= 1
        assert frontend >= 1
        assert content >= 1


class TestSanitization:
    """命令清洗测试"""

    def test_sanitize_command_basic(self):
        """基本清洗"""
        from termsupervisor.hooks.sources.shell import sanitize_command

        assert sanitize_command("ls -la") == "ls -la"
        assert sanitize_command("") == ""

    def test_sanitize_command_removes_nul(self):
        """移除 NUL 字符"""
        from termsupervisor.hooks.sources.shell import sanitize_command

        # NUL 字符被直接移除（不替换为空格）
        assert sanitize_command("ls\x00la") == "lsla"
        assert sanitize_command("a\x00b\x00c") == "abc"

    def test_sanitize_command_replaces_newlines(self):
        """换行替换为空格"""
        from termsupervisor.hooks.sources.shell import sanitize_command

        assert sanitize_command("line1\nline2") == "line1 line2"
        assert sanitize_command("line1\r\nline2") == "line1 line2"

    def test_sanitize_command_collapses_whitespace(self):
        """折叠连续空白"""
        from termsupervisor.hooks.sources.shell import sanitize_command

        assert sanitize_command("ls   -la    foo") == "ls -la foo"

    def test_sanitize_command_truncates(self):
        """截断长命令"""
        from termsupervisor.hooks.sources.shell import sanitize_command

        long_cmd = "a" * 200
        result = sanitize_command(long_cmd, max_len=50)
        assert len(result) == 50
        assert result.endswith("...")


class TestClaudeEventNormalization:
    """Claude 事件类型规范化测试"""

    def test_normalize_claude_event_type(self):
        """规范化 Claude 事件类型"""
        from termsupervisor.hooks.sources.claude_code import normalize_claude_event_type

        assert normalize_claude_event_type("stop") == "Stop"
        assert normalize_claude_event_type("STOP") == "Stop"
        assert normalize_claude_event_type("pre_tool") == "PreToolUse"
        assert normalize_claude_event_type("pre_tool_use") == "PreToolUse"
        assert normalize_claude_event_type("session_start") == "SessionStart"
        assert normalize_claude_event_type("permission_prompt") == "Notification:permission_prompt"

    def test_normalize_claude_event_type_passthrough(self):
        """未知事件类型直接透传"""
        from termsupervisor.hooks.sources.claude_code import normalize_claude_event_type

        assert normalize_claude_event_type("CustomEvent") == "CustomEvent"
        assert normalize_claude_event_type("UnknownEvent") == "UnknownEvent"
