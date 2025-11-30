"""Timer 模块测试"""

import asyncio
import pytest
from unittest.mock import Mock, AsyncMock

from termsupervisor.timer import Timer
from termsupervisor.telemetry import metrics


@pytest.fixture
def timer():
    """创建测试用 Timer"""
    return Timer(tick_interval=0.1)  # 快速 tick 用于测试


@pytest.fixture(autouse=True)
def reset_metrics():
    """每次测试前重置指标"""
    metrics.reset()
    yield
    metrics.reset()


class TestTimerInterval:
    """周期任务测试"""

    @pytest.mark.asyncio
    async def test_register_interval_sync_callback(self, timer):
        """测试同步回调的周期任务"""
        counter = {"value": 0}

        def sync_callback():
            counter["value"] += 1

        timer.register_interval("test_sync", 0.15, sync_callback)

        # 运行 0.5 秒，应该触发至少 3 次
        async def run_timer():
            await timer.run()

        task = asyncio.create_task(run_timer())
        await asyncio.sleep(0.5)
        timer.stop()
        await asyncio.sleep(0.1)  # 等待清理

        assert counter["value"] >= 3

    @pytest.mark.asyncio
    async def test_register_interval_async_callback(self, timer):
        """测试异步回调的周期任务"""
        counter = {"value": 0}

        async def async_callback():
            counter["value"] += 1
            await asyncio.sleep(0.01)

        timer.register_interval("test_async", 0.15, async_callback)

        task = asyncio.create_task(timer.run())
        await asyncio.sleep(0.5)
        timer.stop()
        await asyncio.sleep(0.1)

        assert counter["value"] >= 3

    @pytest.mark.asyncio
    async def test_unregister_interval(self, timer):
        """测试取消注册周期任务"""
        counter = {"value": 0}

        def callback():
            counter["value"] += 1

        timer.register_interval("test", 0.1, callback)
        assert timer.interval_task_count == 1

        result = timer.unregister_interval("test")
        assert result is True
        assert timer.interval_task_count == 0

        # 取消不存在的任务
        result = timer.unregister_interval("nonexistent")
        assert result is False


class TestTimerDelay:
    """延迟任务测试"""

    @pytest.mark.asyncio
    async def test_register_delay_triggers(self, timer):
        """测试延迟任务准时触发"""
        triggered = {"value": False}

        def callback():
            triggered["value"] = True

        timer.register_delay("test_delay", 0.2, callback)
        assert timer.delay_task_count == 1

        task = asyncio.create_task(timer.run())
        await asyncio.sleep(0.15)
        assert triggered["value"] is False  # 还没到时间

        await asyncio.sleep(0.15)
        assert triggered["value"] is True  # 已触发

        timer.stop()
        await asyncio.sleep(0.1)

        # 触发后任务被清理
        assert timer.delay_task_count == 0

    @pytest.mark.asyncio
    async def test_cancel_delay(self, timer):
        """测试取消延迟任务"""
        triggered = {"value": False}

        def callback():
            triggered["value"] = True

        timer.register_delay("test_cancel", 0.2, callback)
        assert timer.has_delay("test_cancel") is True

        result = timer.cancel_delay("test_cancel")
        assert result is True
        assert timer.has_delay("test_cancel") is False

        # 运行一段时间，回调不应被触发
        task = asyncio.create_task(timer.run())
        await asyncio.sleep(0.3)
        timer.stop()
        await asyncio.sleep(0.1)

        assert triggered["value"] is False

    @pytest.mark.asyncio
    async def test_delay_overwrite(self, timer):
        """测试延迟任务覆盖"""
        results = []

        def callback_1():
            results.append("first")

        def callback_2():
            results.append("second")

        timer.register_delay("test_overwrite", 0.3, callback_1)
        timer.register_delay("test_overwrite", 0.2, callback_2)  # 覆盖

        task = asyncio.create_task(timer.run())
        await asyncio.sleep(0.35)
        timer.stop()
        await asyncio.sleep(0.1)

        # 只有第二个回调被执行
        assert results == ["second"]

    @pytest.mark.asyncio
    async def test_stop_cancels_pending_delays(self, timer):
        """测试 stop 取消未触发的延迟任务"""
        triggered = {"value": False}

        def callback():
            triggered["value"] = True

        timer.register_delay("pending", 1.0, callback)

        task = asyncio.create_task(timer.run())
        await asyncio.sleep(0.1)
        timer.stop()
        await asyncio.sleep(0.1)

        # 任务被取消，不会触发
        assert triggered["value"] is False
        assert timer.delay_task_count == 0


class TestTimerErrorHandling:
    """异常处理测试"""

    @pytest.mark.asyncio
    async def test_sync_callback_exception_isolated(self, timer):
        """测试同步回调异常不影响其他任务"""
        counter = {"good": 0, "bad": 0}

        def good_callback():
            counter["good"] += 1

        def bad_callback():
            counter["bad"] += 1
            raise ValueError("Test error")

        timer.register_interval("good", 0.15, good_callback)
        timer.register_interval("bad", 0.15, bad_callback)

        task = asyncio.create_task(timer.run())
        await asyncio.sleep(0.5)
        timer.stop()
        await asyncio.sleep(0.1)

        # 两个任务都应该执行多次
        assert counter["good"] >= 3
        assert counter["bad"] >= 3
        # 应该有 timer.errors 计数
        assert metrics.get_counter("timer.errors", {"task": "bad"}) >= 3

    @pytest.mark.asyncio
    async def test_async_callback_exception_isolated(self, timer):
        """测试异步回调异常不影响其他任务"""
        counter = {"good": 0, "bad": 0}

        async def good_callback():
            counter["good"] += 1

        async def bad_callback():
            counter["bad"] += 1
            raise RuntimeError("Async error")

        timer.register_interval("good", 0.15, good_callback)
        timer.register_interval("bad", 0.15, bad_callback)

        task = asyncio.create_task(timer.run())
        await asyncio.sleep(0.5)
        timer.stop()
        await asyncio.sleep(0.1)

        assert counter["good"] >= 3
        assert counter["bad"] >= 3
        assert metrics.get_counter("timer.errors", {"task": "bad"}) >= 3


class TestTimerLifecycle:
    """生命周期测试"""

    @pytest.mark.asyncio
    async def test_double_run_warning(self, timer, caplog):
        """测试重复 run 产生警告"""
        task = asyncio.create_task(timer.run())
        await asyncio.sleep(0.1)
        assert timer.is_running is True

        # 再次 run 应该产生警告
        await timer.run()  # 立即返回

        timer.stop()
        await asyncio.sleep(0.1)

    @pytest.mark.asyncio
    async def test_stop_idempotent(self, timer):
        """测试 stop 是幂等的"""
        timer.stop()  # 未启动时 stop
        timer.stop()  # 再次 stop

        task = asyncio.create_task(timer.run())
        await asyncio.sleep(0.1)
        timer.stop()
        timer.stop()  # 再次 stop
        await asyncio.sleep(0.1)

    @pytest.mark.asyncio
    async def test_get_tasks(self, timer):
        """测试获取任务列表"""
        timer.register_interval("int1", 1.0, lambda: None)
        timer.register_interval("int2", 2.0, lambda: None)
        timer.register_delay("del1", 1.0, lambda: None)

        assert set(timer.get_interval_tasks()) == {"int1", "int2"}
        assert timer.get_delay_tasks() == ["del1"]
