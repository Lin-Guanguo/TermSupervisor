"""StateManager 测试"""

import asyncio

import pytest

from termsupervisor.pane import (
    DisplayUpdate,
    HookEvent,
    StateManager,
    TaskStatus,
)
from termsupervisor.telemetry import metrics
from termsupervisor.timer import Timer


@pytest.fixture
def timer():
    """创建测试用 Timer"""
    return Timer(tick_interval=0.05)


@pytest.fixture
def manager(timer):
    """创建测试用 StateManager"""
    return StateManager(timer=timer)


@pytest.fixture(autouse=True)
def reset_metrics():
    """每次测试前重置指标"""
    metrics.reset()
    yield
    metrics.reset()


class TestPaneManagement:
    """Pane 管理测试"""

    def test_get_or_create_new_pane(self, manager):
        """创建新 pane"""
        machine, pane = manager.get_or_create("test-pane-123")

        assert machine is not None
        assert pane is not None
        assert machine.status == TaskStatus.IDLE

    def test_get_or_create_existing_pane(self, manager):
        """获取已存在的 pane"""
        machine1, pane1 = manager.get_or_create("test-pane-123")
        machine2, pane2 = manager.get_or_create("test-pane-123")

        assert machine1 is machine2
        assert pane1 is pane2

    def test_remove_pane(self, manager):
        """移除 pane"""
        manager.get_or_create("test-pane-123")
        assert "test-pane-123" in manager.get_all_panes()

        manager.remove_pane("test-pane-123")
        assert "test-pane-123" not in manager.get_all_panes()

    def test_cleanup_closed_panes(self, manager):
        """清理已关闭的 pane"""
        manager.get_or_create("pane-1")
        manager.get_or_create("pane-2")
        manager.get_or_create("pane-3")

        # pane-2 关闭了
        closed = manager.cleanup_closed_panes({"pane-1", "pane-3"})

        assert "pane-2" in closed
        assert "pane-2" not in manager.get_all_panes()


class TestEventProcessing:
    """事件处理测试"""

    async def test_enqueue_and_process(self, manager):
        """入队并处理事件"""
        event = HookEvent(
            source="shell",
            pane_id="test-pane",
            event_type="command_start",
            data={"command": "ls"},
        )

        result = manager.enqueue(event)
        assert result is True

        count, updates = await manager.process_queued()
        assert count == 1

        assert manager.get_status("test-pane") == TaskStatus.RUNNING

    async def test_stale_generation_rejected(self, manager):
        """旧 generation 事件被拒绝"""
        # 先创建 pane
        manager.get_or_create("test-pane")

        # 递增 generation
        manager.increment_generation("test-pane")

        # 发送旧 generation 的事件
        event = HookEvent(
            source="shell",
            pane_id="test-pane",
            event_type="command_start",
            data={"command": "ls"},
            pane_generation=1,  # 旧的
        )

        result = manager.enqueue(event)
        assert result is False

    async def test_content_update_updates_content(self, manager):
        """content.update 更新内容存储"""
        event = HookEvent(
            source="content",
            pane_id="test-pane",
            event_type="update",
            data={"content": "new content", "content_hash": "hash123"},
        )

        manager.enqueue(event)
        await manager.process_queued()

        # Phase 3.4: 使用新的 get_content/get_content_hash 方法
        assert manager.get_content("test-pane") == "new content"
        assert manager.get_content_hash("test-pane") == "hash123"

    async def test_content_changed_updates_content_compat(self, manager):
        """content.changed（兼容）更新内容存储"""
        event = HookEvent(
            source="content",
            pane_id="test-pane",
            event_type="changed",
            data={"content": "new content", "content_hash": "hash123"},
        )

        manager.enqueue(event)
        await manager.process_queued()

        # Phase 3.4: 使用新的 get_content/get_content_hash 方法
        assert manager.get_content("test-pane") == "new content"
        assert manager.get_content_hash("test-pane") == "hash123"

class TestLongRunningCheck:
    """LONG_RUNNING 检查测试"""

    def test_tick_all_triggers_long_running(self, manager):
        """tick_all 触发 LONG_RUNNING"""
        # 创建 pane 并进入 RUNNING
        manager.enqueue(
            HookEvent(
                source="shell",
                pane_id="test-pane",
                event_type="command_start",
                data={"command": "sleep 100"},
            )
        )
        # 直接处理（同步）
        machine = manager.get_machine("test-pane")
        machine.process(
            HookEvent(
                source="shell",
                pane_id="test-pane",
                event_type="command_start",
                data={"command": "sleep 100"},
                pane_generation=machine.pane_generation,
            )
        )

        # 手动设置 started_at 到过去
        import time

        machine._started_at = time.time() - 100  # 100秒前

        # tick_all 应该触发
        triggered = manager.tick_all()

        assert "test-pane" in triggered
        assert machine.status == TaskStatus.LONG_RUNNING


class TestCallbacks:
    """回调测试 (Phase 3.3: 改用返回值)"""

    async def test_process_queued_returns_updates(self, manager):
        """process_queued 返回 DisplayUpdate（替代回调）"""
        manager.enqueue(
            HookEvent(
                source="shell",
                pane_id="test-pane",
                event_type="command_start",
                data={"command": "ls"},
            )
        )
        count, updates = await manager.process_queued()

        assert len(updates) == 1
        assert updates[0].display_state.status == TaskStatus.RUNNING
        assert updates[0].pane_id == "test-pane"


class TestProcessQueuedReturnValue:
    """process_queued 返回值测试 (Phase 3.2)"""

    async def test_process_queued_returns_display_updates(self, manager):
        """process_queued 返回 DisplayUpdate 列表"""
        manager.enqueue(
            HookEvent(
                source="shell",
                pane_id="test-pane",
                event_type="command_start",
                data={"command": "ls"},
            )
        )

        result = await manager.process_queued()

        # result 现在是 (count, updates) 元组
        count, updates = result
        assert count == 1
        assert len(updates) == 1
        assert updates[0].pane_id == "test-pane"
        assert updates[0].display_state.status == TaskStatus.RUNNING

    async def test_process_queued_no_update_for_content_events(self, manager):
        """content 事件不返回 DisplayUpdate"""
        manager.enqueue(
            HookEvent(
                source="content",
                pane_id="test-pane",
                event_type="update",
                data={"content": "test", "content_hash": "hash"},
            )
        )

        count, updates = await manager.process_queued()

        assert count == 1  # 事件被处理
        assert len(updates) == 0  # 但不产生 DisplayUpdate

    async def test_process_queued_multiple_updates(self, manager):
        """多个事件返回多个 DisplayUpdate"""
        manager.enqueue(
            HookEvent(
                source="shell",
                pane_id="pane-1",
                event_type="command_start",
                data={"command": "ls"},
            )
        )
        manager.enqueue(
            HookEvent(
                source="claude-code",
                pane_id="pane-2",
                event_type="SessionStart",
                data={},
            )
        )

        count, updates = await manager.process_queued()

        assert count == 2
        assert len(updates) == 2
        # 验证两个不同的 pane
        pane_ids = {u.pane_id for u in updates}
        assert pane_ids == {"pane-1", "pane-2"}


class TestGeneration:
    """Generation 测试"""

    def test_increment_generation(self, manager):
        """递增 generation"""
        manager.get_or_create("test-pane")
        initial = manager.get_generation("test-pane")

        new = manager.increment_generation("test-pane")

        assert new == initial + 1


class TestQueueBehavior:
    """队列行为测试"""

    async def test_queue_serializes_events(self, manager):
        """队列串行化事件"""
        # 入队多个事件
        for i in range(5):
            manager.enqueue(
                HookEvent(
                    source="shell",
                    pane_id="test-pane",
                    event_type="command_start" if i % 2 == 0 else "command_end",
                    data={"command": f"cmd{i}"} if i % 2 == 0 else {"exit_code": 0},
                )
            )

        # 处理所有
        count, updates = await manager.process_queued()
        assert count == 5


class TestQueuePriority:
    """队列优先级测试（Phase 1）"""

    def test_low_priority_dropped_at_high_watermark(self, manager):
        """低优先级事件在高水位时被丢弃"""
        from termsupervisor.pane.queue import EventQueue

        queue = EventQueue("test-pane", max_size=10)

        # 填充到高水位以上（80% = 8个）
        for i in range(9):
            queue.enqueue_event(
                HookEvent(
                    source="shell",
                    pane_id="test-pane",
                    event_type="command_start",
                    data={"command": f"cmd{i}"},
                    pane_generation=1,
                )
            )

        # 低优先级事件应该被丢弃
        result = queue.enqueue_event(
            HookEvent(
                source="content",
                pane_id="test-pane",
                event_type="changed",
                data={"content": "test"},
                pane_generation=1,
            )
        )

        assert result is False
        assert queue.low_priority_drops == 1

    def test_protected_signal_never_dropped(self, manager):
        """受保护信号永不丢弃"""
        from termsupervisor.pane.queue import EventQueue

        queue = EventQueue("test-pane", max_size=10)

        # 填充到高水位以上
        for i in range(9):
            queue.enqueue_event(
                HookEvent(
                    source="shell",
                    pane_id="test-pane",
                    event_type="command_start",
                    data={"command": f"cmd{i}"},
                    pane_generation=1,
                )
            )

        # 受保护信号应该成功入队
        result = queue.enqueue_event(
            HookEvent(
                source="shell",
                pane_id="test-pane",
                event_type="command_end",
                data={"exit_code": 0},
                pane_generation=1,
            )
        )

        assert result is True

    def test_low_priority_allowed_below_watermark(self, manager):
        """低优先级事件在水位以下允许入队"""
        from termsupervisor.pane.queue import EventQueue

        queue = EventQueue("test-pane", max_size=10)

        # 只填充少量（低于水位）
        for i in range(5):
            queue.enqueue_event(
                HookEvent(
                    source="shell",
                    pane_id="test-pane",
                    event_type="command_start",
                    data={"command": f"cmd{i}"},
                    pane_generation=1,
                )
            )

        # 低优先级事件应该成功入队
        result = queue.enqueue_event(
            HookEvent(
                source="content",
                pane_id="test-pane",
                event_type="changed",
                data={"content": "test"},
                pane_generation=1,
            )
        )

        assert result is True
        assert queue.low_priority_drops == 0

    def test_merge_content_events(self, manager):
        """合并连续 content 事件"""
        from termsupervisor.pane.queue import EventQueue

        queue = EventQueue("test-pane", max_size=10)

        # 入队多个 content 事件（中间夹杂其他事件）
        queue.enqueue_event(
            HookEvent(
                source="content",
                pane_id="test-pane",
                event_type="changed",
                data={"content": "content1"},
                pane_generation=1,
            )
        )
        queue.enqueue_event(
            HookEvent(
                source="content",
                pane_id="test-pane",
                event_type="changed",
                data={"content": "content2"},
                pane_generation=1,
            )
        )
        queue.enqueue_event(
            HookEvent(
                source="shell",
                pane_id="test-pane",
                event_type="command_start",
                data={"command": "ls"},
                pane_generation=1,
            )
        )
        queue.enqueue_event(
            HookEvent(
                source="content",
                pane_id="test-pane",
                event_type="changed",
                data={"content": "content3"},
                pane_generation=1,
            )
        )

        assert len(queue) == 4

        # 合并
        merged = queue.merge_content_events()

        # 应该合并了 content1（保留 content2 因为它在 command_start 之前）
        assert merged == 1
        assert len(queue) == 3


class TestDisplayUpdate:
    """DisplayUpdate 数据类测试"""

    def test_display_update_structure(self):
        """DisplayUpdate 基本结构"""
        from termsupervisor.pane import DisplayState

        display_state = DisplayState(
            status=TaskStatus.RUNNING,
            source="shell",
            description="执行: ls",
            state_id=1,
        )
        update = DisplayUpdate(
            pane_id="test-pane",
            display_state=display_state,
            suppressed=False,
            reason="state_change",
        )

        assert update.pane_id == "test-pane"
        assert update.display_state.status == TaskStatus.RUNNING
        assert update.suppressed is False
        assert update.reason == "state_change"

    def test_display_update_suppressed(self):
        """DisplayUpdate 带 suppressed 标记"""
        from termsupervisor.pane import DisplayState

        display_state = DisplayState(
            status=TaskStatus.DONE,
            source="shell",
            description="命令完成",
            state_id=2,
        )
        update = DisplayUpdate(
            pane_id="test-pane",
            display_state=display_state,
            suppressed=True,
            reason="短任务，不通知",
        )

        assert update.suppressed is True
        assert update.reason == "短任务，不通知"

    def test_display_update_to_dict(self):
        """DisplayUpdate to_dict 方法"""
        from termsupervisor.pane import DisplayState

        display_state = DisplayState(
            status=TaskStatus.FAILED,
            source="shell",
            description="失败 (exit=1)",
            state_id=3,
        )
        update = DisplayUpdate(
            pane_id="test-pane",
            display_state=display_state,
            suppressed=False,
            reason="command_end",
        )

        d = update.to_dict()
        assert d["pane_id"] == "test-pane"
        assert d["suppressed"] is False
        assert d["reason"] == "command_end"
        # display_state 也应该被序列化
        assert "display_state" in d
        assert d["display_state"]["status"] == "failed"
