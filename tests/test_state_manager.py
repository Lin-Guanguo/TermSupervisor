"""StateManager 测试"""

import asyncio
import pytest
import tempfile
from pathlib import Path

from termsupervisor.pane import (
    TaskStatus,
    HookEvent,
    StateManager,
    persistence,
)
from termsupervisor.timer import Timer
from termsupervisor.telemetry import metrics


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

        count = await manager.process_queued()
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

    async def test_content_changed_updates_pane(self, manager):
        """content.changed 更新 Pane 内容"""
        event = HookEvent(
            source="content",
            pane_id="test-pane",
            event_type="changed",
            data={"content": "new content", "content_hash": "hash123"},
        )

        manager.enqueue(event)
        await manager.process_queued()

        pane = manager.get_pane("test-pane")
        assert pane.content == "new content"
        assert pane.content_hash == "hash123"

    async def test_content_changed_fallback_waiting_to_running(self, manager):
        """content.changed 在 WAITING 时触发兜底恢复"""
        # 先进入 WAITING 状态
        manager.enqueue(HookEvent(
            source="claude-code",
            pane_id="test-pane",
            event_type="Notification:permission_prompt",
        ))
        await manager.process_queued()
        assert manager.get_status("test-pane") == TaskStatus.WAITING_APPROVAL

        # content.changed 应该触发兜底恢复
        manager.enqueue(HookEvent(
            source="content",
            pane_id="test-pane",
            event_type="changed",
            data={"content": "output"},
        ))
        await manager.process_queued()

        assert manager.get_status("test-pane") == TaskStatus.RUNNING


class TestLongRunningCheck:
    """LONG_RUNNING 检查测试"""

    def test_tick_all_triggers_long_running(self, manager):
        """tick_all 触发 LONG_RUNNING"""
        # 创建 pane 并进入 RUNNING
        manager.enqueue(HookEvent(
            source="shell",
            pane_id="test-pane",
            event_type="command_start",
            data={"command": "sleep 100"},
        ))
        # 直接处理（同步）
        machine = manager.get_machine("test-pane")
        machine.process(HookEvent(
            source="shell",
            pane_id="test-pane",
            event_type="command_start",
            data={"command": "sleep 100"},
            pane_generation=machine.pane_generation,
        ))

        # 手动设置 started_at 到过去
        import time
        machine._started_at = time.time() - 100  # 100秒前

        # tick_all 应该触发
        triggered = manager.tick_all()

        assert "test-pane" in triggered
        assert machine.status == TaskStatus.LONG_RUNNING


class TestCallbacks:
    """回调测试"""

    async def test_display_change_callback(self, manager):
        """显示变化回调"""
        changes = []

        def callback(pane_id, display_state, suppressed, reason):
            changes.append({
                "pane_id": pane_id,
                "status": display_state.status,
                "suppressed": suppressed,
            })

        manager.set_on_display_change(callback)

        manager.enqueue(HookEvent(
            source="shell",
            pane_id="test-pane",
            event_type="command_start",
            data={"command": "ls"},
        ))
        await manager.process_queued()

        assert len(changes) == 1
        assert changes[0]["status"] == TaskStatus.RUNNING


class TestPersistence:
    """持久化测试"""

    def test_save_and_load(self, manager, tmp_path):
        """保存和加载"""
        # 创建一些状态
        machine, _ = manager.get_or_create("test-pane-1")
        machine.process(HookEvent(
            source="shell",
            pane_id="test-pane-1",
            event_type="command_start",
            data={"command": "ls"},
            pane_generation=machine.pane_generation,
        ))

        # 保存
        path = tmp_path / "state.json"
        machines = {pid: m.to_dict() for pid, m in manager._machines.items()}
        panes = {pid: p.to_dict() for pid, p in manager._panes.items()}
        persistence.save(machines, panes, path)

        # 创建新 manager 并加载
        new_manager = StateManager()
        result = persistence.load(path)
        assert result is not None

        machines_data, panes_data = result
        assert "test-pane-1" in machines_data

    def test_corrupted_file_skipped(self, tmp_path):
        """损坏的文件被跳过"""
        path = tmp_path / "corrupted.json"
        path.write_text("invalid json{}")

        result = persistence.load(path)
        assert result is None

    def test_version_mismatch_skipped(self, tmp_path):
        """版本不匹配被跳过"""
        path = tmp_path / "old_version.json"
        import json
        path.write_text(json.dumps({
            "version": 1,  # 旧版本
            "machines": {},
            "panes": {},
        }))

        result = persistence.load(path, version=2)
        assert result is None


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
            manager.enqueue(HookEvent(
                source="shell",
                pane_id="test-pane",
                event_type="command_start" if i % 2 == 0 else "command_end",
                data={"command": f"cmd{i}"} if i % 2 == 0 else {"exit_code": 0},
            ))

        # 处理所有
        count = await manager.process_queued()
        assert count == 5
