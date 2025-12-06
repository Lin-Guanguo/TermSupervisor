"""TaskStatus 枚举测试

注意：状态机测试已迁移到 test_pane_state_machine.py
此文件保留 TaskStatus 属性测试。
"""

from termsupervisor.pane import TaskStatus


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

    def test_color(self):
        """测试状态颜色"""
        assert TaskStatus.IDLE.color == "gray"
        assert TaskStatus.RUNNING.color == "blue"
        assert TaskStatus.LONG_RUNNING.color == "darkblue"
        assert TaskStatus.WAITING_APPROVAL.color == "yellow"
        assert TaskStatus.DONE.color == "green"
        assert TaskStatus.FAILED.color == "red"
