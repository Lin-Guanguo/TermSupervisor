"""Pane 显示层测试"""

import asyncio
import pytest
from datetime import datetime

from termsupervisor.pane import TaskStatus, StateChange, Pane
from termsupervisor.timer import Timer
from termsupervisor.telemetry import metrics


@pytest.fixture
def timer():
    """创建测试用 Timer"""
    return Timer(tick_interval=0.05)


@pytest.fixture
def pane(timer):
    """创建测试用 Pane"""
    return Pane(pane_id="test-pane-123", timer=timer)


@pytest.fixture(autouse=True)
def reset_metrics():
    """每次测试前重置指标"""
    metrics.reset()
    yield
    metrics.reset()


class TestStateChange:
    """状态变化处理测试"""

    def test_handle_state_change_updates_display(self, pane):
        """状态变化更新显示"""
        change = StateChange(
            old_status=TaskStatus.IDLE,
            new_status=TaskStatus.RUNNING,
            old_source="shell",
            new_source="shell",
            description="执行: ls",
            state_id=10,
            started_at=datetime.now().timestamp(),
            running_duration=0.0,
        )

        result = pane.handle_state_change(change)

        assert result is True
        assert pane.status == TaskStatus.RUNNING
        assert pane.state_id == 10

    def test_state_id_prevents_stale_update(self, pane):
        """state_id 防乱序"""
        # 先更新到 state_id=10
        pane.handle_state_change(StateChange(
            old_status=TaskStatus.IDLE,
            new_status=TaskStatus.RUNNING,
            old_source="shell",
            new_source="shell",
            description="first",
            state_id=10,
        ))
        assert pane.state_id == 10

        # 尝试用旧 state_id 更新
        result = pane.handle_state_change(StateChange(
            old_status=TaskStatus.RUNNING,
            new_status=TaskStatus.DONE,
            old_source="shell",
            new_source="shell",
            description="stale",
            state_id=5,  # 旧的
        ))

        assert result is False
        assert pane.status == TaskStatus.RUNNING  # 状态未变

    def test_callback_called_on_display_change(self, pane):
        """显示变化时调用回调"""
        changes = []

        def callback(display_state):
            changes.append(display_state)

        pane.set_on_display_change(callback)

        pane.handle_state_change(StateChange(
            old_status=TaskStatus.IDLE,
            new_status=TaskStatus.RUNNING,
            old_source="shell",
            new_source="shell",
            description="test",
            state_id=1,
        ))

        assert len(changes) == 1
        assert changes[0].status == TaskStatus.RUNNING


class TestDelayedDisplay:
    """延迟展示测试（DONE/FAILED → IDLE 时延迟展示 5s）"""

    def test_done_to_idle_delayed_display(self, pane, timer):
        """DONE → IDLE 时延迟展示（状态机已转换，显示层保持 DONE）"""
        # 进入 DONE 状态
        pane.handle_state_change(StateChange(
            old_status=TaskStatus.IDLE,
            new_status=TaskStatus.DONE,
            old_source="shell",
            new_source="shell",
            description="done",
            state_id=1,
        ))
        assert pane.status == TaskStatus.DONE

        # DONE → IDLE（状态机已转换）
        result = pane.handle_state_change(StateChange(
            old_status=TaskStatus.DONE,
            new_status=TaskStatus.IDLE,
            old_source="shell",
            new_source="user",
            description="",
            state_id=2,
        ))

        # 延迟展示：返回 False，显示仍为 DONE
        assert result is False
        assert pane.status == TaskStatus.DONE

        # 应该注册了延迟展示任务
        delay_name = f"pane_display_delay_{pane.pane_id[:8]}"
        assert timer.has_delay(delay_name)

    def test_failed_to_idle_delayed_display(self, pane, timer):
        """FAILED → IDLE 时延迟展示"""
        pane.handle_state_change(StateChange(
            old_status=TaskStatus.IDLE,
            new_status=TaskStatus.FAILED,
            old_source="shell",
            new_source="shell",
            description="failed",
            state_id=1,
        ))
        assert pane.status == TaskStatus.FAILED

        result = pane.handle_state_change(StateChange(
            old_status=TaskStatus.FAILED,
            new_status=TaskStatus.IDLE,
            old_source="shell",
            new_source="user",
            description="",
            state_id=2,
        ))

        assert result is False
        assert pane.status == TaskStatus.FAILED
        delay_name = f"pane_display_delay_{pane.pane_id[:8]}"
        assert timer.has_delay(delay_name)

    def test_running_to_done_immediate(self, pane, timer):
        """RUNNING → DONE 立即展示"""
        pane.handle_state_change(StateChange(
            old_status=TaskStatus.IDLE,
            new_status=TaskStatus.RUNNING,
            old_source="shell",
            new_source="shell",
            description="running",
            state_id=1,
        ))

        result = pane.handle_state_change(StateChange(
            old_status=TaskStatus.RUNNING,
            new_status=TaskStatus.DONE,
            old_source="shell",
            new_source="shell",
            description="done",
            state_id=2,
        ))

        # 立即展示
        assert result is True
        assert pane.status == TaskStatus.DONE
        # 不应该有延迟任务（延迟只在 DONE/FAILED → IDLE 时）
        delay_name = f"pane_display_delay_{pane.pane_id[:8]}"
        assert not timer.has_delay(delay_name)

    def test_new_state_cancels_delayed_display(self, pane, timer):
        """新状态取消延迟展示任务"""
        # IDLE → DONE
        pane.handle_state_change(StateChange(
            old_status=TaskStatus.IDLE,
            new_status=TaskStatus.DONE,
            old_source="shell",
            new_source="shell",
            description="done",
            state_id=1,
        ))

        # DONE → IDLE（触发延迟展示）
        pane.handle_state_change(StateChange(
            old_status=TaskStatus.DONE,
            new_status=TaskStatus.IDLE,
            old_source="shell",
            new_source="user",
            description="",
            state_id=2,
        ))

        delay_name = f"pane_display_delay_{pane.pane_id[:8]}"
        assert timer.has_delay(delay_name)

        # 新命令开始，应该取消延迟任务
        pane.handle_state_change(StateChange(
            old_status=TaskStatus.IDLE,
            new_status=TaskStatus.RUNNING,
            old_source="shell",
            new_source="shell",
            description="new cmd",
            state_id=3,
        ))

        assert pane.status == TaskStatus.RUNNING
        assert not timer.has_delay(delay_name)

    def test_idle_to_running_immediate(self, pane, timer):
        """IDLE → RUNNING 立即展示（无延迟）"""
        result = pane.handle_state_change(StateChange(
            old_status=TaskStatus.IDLE,
            new_status=TaskStatus.RUNNING,
            old_source="shell",
            new_source="shell",
            description="running",
            state_id=1,
        ))

        assert result is True
        assert pane.status == TaskStatus.RUNNING
        delay_name = f"pane_display_delay_{pane.pane_id[:8]}"
        assert not timer.has_delay(delay_name)


class TestNotificationSuppression:
    """通知抑制测试"""

    def test_suppress_short_task(self, pane):
        """短任务抑制通知"""
        # 模拟短时间任务
        pane.handle_state_change(StateChange(
            old_status=TaskStatus.IDLE,
            new_status=TaskStatus.DONE,
            old_source="shell",
            new_source="shell",
            description="done",
            state_id=1,
            running_duration=1.0,  # < 3s
        ))

        suppressed, reason = pane.should_suppress_notification()

        assert suppressed is True
        assert "duration" in reason

    def test_suppress_focused_pane(self, pane):
        """focus 中的 pane 抑制通知"""
        # 设置 focus checker
        pane.set_focus_checker(lambda pid: pid == "test-pane-123")

        pane.handle_state_change(StateChange(
            old_status=TaskStatus.IDLE,
            new_status=TaskStatus.DONE,
            old_source="shell",
            new_source="shell",
            description="done",
            state_id=1,
            running_duration=10.0,  # > 3s
        ))

        suppressed, reason = pane.should_suppress_notification()

        assert suppressed is True
        assert reason == "focused"

    def test_no_suppress_long_task_unfocused(self, pane):
        """长任务且未 focus 不抑制"""
        pane.set_focus_checker(lambda pid: False)

        pane.handle_state_change(StateChange(
            old_status=TaskStatus.IDLE,
            new_status=TaskStatus.DONE,
            old_source="shell",
            new_source="shell",
            description="done",
            state_id=1,
            running_duration=10.0,
        ))

        suppressed, reason = pane.should_suppress_notification()

        assert suppressed is False

    def test_only_done_failed_suppressed(self, pane):
        """只有 DONE/FAILED 判断抑制"""
        pane.handle_state_change(StateChange(
            old_status=TaskStatus.IDLE,
            new_status=TaskStatus.RUNNING,
            old_source="shell",
            new_source="shell",
            description="running",
            state_id=1,
            running_duration=0.5,
        ))

        suppressed, reason = pane.should_suppress_notification()

        assert suppressed is False


class TestContentUpdate:
    """内容更新测试"""

    def test_update_content(self, pane):
        """更新内容"""
        pane.update_content("new content", "hash123")

        assert pane.content == "new content"
        assert pane.content_hash == "hash123"

    def test_update_content_triggers_callback(self, pane):
        """内容更新触发回调"""
        changes = []

        def callback(display_state):
            changes.append(display_state)

        pane.set_on_display_change(callback)
        pane.update_content("content", "hash")

        assert len(changes) == 1


class TestSerialization:
    """序列化测试"""

    def test_to_dict_and_from_dict(self, pane):
        """序列化往返"""
        pane.handle_state_change(StateChange(
            old_status=TaskStatus.IDLE,
            new_status=TaskStatus.RUNNING,
            old_source="shell",
            new_source="shell",
            description="test",
            state_id=5,
        ))
        pane.update_content("", "hash456")

        data = pane.to_dict()
        restored = Pane.from_dict(data)

        assert restored.pane_id == pane.pane_id
        assert restored.status == pane.status
        assert restored.state_id == pane.state_id
        assert restored.content_hash == pane.content_hash


class TestConvenienceMethods:
    """便捷方法测试"""

    def test_is_running(self, pane):
        """is_running 方法"""
        assert pane.is_running() is False

        pane.handle_state_change(StateChange(
            old_status=TaskStatus.IDLE,
            new_status=TaskStatus.RUNNING,
            old_source="shell",
            new_source="shell",
            description="",
            state_id=1,
        ))

        assert pane.is_running() is True

    def test_needs_notification(self, pane):
        """needs_notification 方法"""
        assert pane.needs_notification() is False

        pane.handle_state_change(StateChange(
            old_status=TaskStatus.IDLE,
            new_status=TaskStatus.DONE,
            old_source="shell",
            new_source="shell",
            description="",
            state_id=1,
        ))

        assert pane.needs_notification() is True

    def test_get_display_dict(self, pane):
        """get_display_dict 方法"""
        pane.handle_state_change(StateChange(
            old_status=TaskStatus.IDLE,
            new_status=TaskStatus.RUNNING,
            old_source="shell",
            new_source="shell",
            description="test",
            state_id=1,
        ))

        d = pane.get_display_dict()

        assert d["status"] == "running"
        assert d["is_running"] is True
        assert d["description"] == "test"


class TestAutoDismiss:
    """Auto-dismiss 测试（Phase 1）"""

    def test_done_registers_auto_dismiss(self, pane, timer):
        """DONE 状态注册 auto-dismiss 定时器"""
        pane.handle_state_change(StateChange(
            old_status=TaskStatus.IDLE,
            new_status=TaskStatus.DONE,
            old_source="shell",
            new_source="shell",
            description="done",
            state_id=1,
            running_duration=10.0,
        ))

        assert pane.status == TaskStatus.DONE
        auto_dismiss_name = f"pane_auto_dismiss_{pane.pane_id[:8]}"
        assert timer.has_delay(auto_dismiss_name)

    def test_failed_registers_auto_dismiss(self, pane, timer):
        """FAILED 状态注册 auto-dismiss 定时器"""
        pane.handle_state_change(StateChange(
            old_status=TaskStatus.IDLE,
            new_status=TaskStatus.FAILED,
            old_source="shell",
            new_source="shell",
            description="failed",
            state_id=1,
            running_duration=10.0,
        ))

        assert pane.status == TaskStatus.FAILED
        auto_dismiss_name = f"pane_auto_dismiss_{pane.pane_id[:8]}"
        assert timer.has_delay(auto_dismiss_name)

    def test_new_state_cancels_auto_dismiss(self, pane, timer):
        """新状态变化取消 auto-dismiss 定时器"""
        pane.handle_state_change(StateChange(
            old_status=TaskStatus.IDLE,
            new_status=TaskStatus.DONE,
            old_source="shell",
            new_source="shell",
            description="done",
            state_id=1,
        ))

        auto_dismiss_name = f"pane_auto_dismiss_{pane.pane_id[:8]}"
        assert timer.has_delay(auto_dismiss_name)

        # 新命令开始，取消 auto-dismiss
        pane.handle_state_change(StateChange(
            old_status=TaskStatus.DONE,
            new_status=TaskStatus.RUNNING,
            old_source="shell",
            new_source="shell",
            description="new cmd",
            state_id=2,
        ))

        assert not timer.has_delay(auto_dismiss_name)

    def test_running_no_auto_dismiss(self, pane, timer):
        """RUNNING 状态不注册 auto-dismiss"""
        pane.handle_state_change(StateChange(
            old_status=TaskStatus.IDLE,
            new_status=TaskStatus.RUNNING,
            old_source="shell",
            new_source="shell",
            description="running",
            state_id=1,
        ))

        auto_dismiss_name = f"pane_auto_dismiss_{pane.pane_id[:8]}"
        assert not timer.has_delay(auto_dismiss_name)


class TestQuietCompletion:
    """静默完成测试（Phase 1）"""

    def test_short_task_quiet_completion(self, pane):
        """短任务标记为 quiet_completion"""
        pane.handle_state_change(StateChange(
            old_status=TaskStatus.IDLE,
            new_status=TaskStatus.DONE,
            old_source="shell",
            new_source="shell",
            description="done",
            state_id=1,
            running_duration=1.0,  # < 3s
        ))

        assert pane.display_state.quiet_completion is True

    def test_long_task_no_quiet_completion(self, pane):
        """长任务不标记为 quiet_completion"""
        pane.handle_state_change(StateChange(
            old_status=TaskStatus.IDLE,
            new_status=TaskStatus.DONE,
            old_source="shell",
            new_source="shell",
            description="done",
            state_id=1,
            running_duration=10.0,  # > 3s
        ))

        assert pane.display_state.quiet_completion is False

    def test_quiet_completion_in_display_dict(self, pane):
        """quiet_completion 出现在 display_dict 中"""
        pane.handle_state_change(StateChange(
            old_status=TaskStatus.IDLE,
            new_status=TaskStatus.DONE,
            old_source="shell",
            new_source="shell",
            description="done",
            state_id=1,
            running_duration=1.0,
        ))

        d = pane.get_display_dict()
        assert "quiet_completion" in d
        assert d["quiet_completion"] is True


class TestRecentlyFinishedHint:
    """recently_finished 提示测试（Phase 1）"""

    def test_recently_finished_default_false(self, pane):
        """recently_finished 默认为 False"""
        assert pane.display_state.recently_finished is False

    def test_recently_finished_in_display_dict(self, pane):
        """recently_finished 出现在 display_dict 中"""
        d = pane.get_display_dict()
        assert "recently_finished" in d
        assert d["recently_finished"] is False
