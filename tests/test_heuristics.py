"""Heuristics 模块测试（Phase 4）"""

import pytest
from unittest.mock import Mock, AsyncMock

from termsupervisor.analysis.heuristics import ContentHeuristic, PaneHeuristicState
from termsupervisor.pane import TaskStatus, DisplayState
from termsupervisor.telemetry import metrics


@pytest.fixture
def mock_hook_manager():
    """创建 mock HookManager"""
    manager = Mock()
    manager.emit_event = AsyncMock()
    manager.get_state = Mock(return_value=None)
    return manager


@pytest.fixture
def heuristic(mock_hook_manager):
    """创建启用的 ContentHeuristic"""
    h = ContentHeuristic(mock_hook_manager)
    h.set_enabled(True)
    return h


@pytest.fixture(autouse=True)
def reset_metrics():
    """每次测试前重置指标"""
    metrics.reset()
    yield
    metrics.reset()


class TestHeuristicBasics:
    """基本功能测试"""

    def test_reads_config_on_init(self):
        """初始化时读取配置"""
        from termsupervisor import config
        h = ContentHeuristic()
        # enabled 应该与配置一致
        assert h.enabled is config.HEURISTICS_ENABLED

    def test_can_toggle_enabled(self, heuristic):
        """可以动态切换启用状态"""
        heuristic.set_enabled(False)
        assert heuristic.enabled is False
        heuristic.set_enabled(True)
        assert heuristic.enabled is True

    def test_no_analysis_when_disabled(self, mock_hook_manager):
        """禁用时不分析"""
        h = ContentHeuristic(mock_hook_manager)
        h.set_enabled(False)

        result = h.analyze("pane-1", "content", "hash", 10)

        assert result is None

    def test_no_analysis_without_hook_manager(self):
        """无 HookManager 时不分析"""
        h = ContentHeuristic()
        h.set_enabled(True)

        result = h.analyze("pane-1", "content", "hash", 10)

        assert result is None


class TestActivityDetection:
    """活动检测测试"""

    def test_start_emitted_on_sufficient_activity(self, heuristic, mock_hook_manager):
        """足够活动时发出 start"""
        # 模拟多次内容变化
        heuristic.analyze("pane-1", "c1", "hash1", 1)
        heuristic.analyze("pane-1", "c2", "hash2", 1)
        result = heuristic.analyze("pane-1", "c3", "hash3", 1)

        assert result == "start"
        # 注：emit_event 在实际运行时通过 event loop 调用
        # 这里验证返回值正确即表示触发了 start 逻辑

    def test_no_start_below_threshold(self, heuristic, mock_hook_manager):
        """低于阈值不发出 start"""
        result = heuristic.analyze("pane-1", "c1", "hash1", 1)

        assert result is None

    def test_start_only_once(self, heuristic, mock_hook_manager):
        """start 只发出一次"""
        # 触发 start
        heuristic.analyze("pane-1", "c1", "hash1", 3)

        # 继续活动不应再发 start
        result = heuristic.analyze("pane-1", "c2", "hash2", 5)

        assert result is None


class TestIdleDetection:
    """Idle 检测测试"""

    def test_idle_after_timeout(self, heuristic, mock_hook_manager):
        """超时后发出 idle"""
        import time

        # 触发 start
        heuristic.analyze("pane-1", "c1", "hash1", 5)

        # 模拟时间流逝
        state = heuristic._get_state("pane-1")
        state.last_activity_at = time.time() - 100  # 100秒前

        # tick 应该触发 idle
        triggered = heuristic.tick()

        assert "pane-1" in triggered
        # 注：emit_event 在实际运行时通过 event loop 调用

    def test_no_idle_before_timeout(self, heuristic, mock_hook_manager):
        """超时前不发出 idle"""
        # 触发 start
        heuristic.analyze("pane-1", "c1", "hash1", 5)

        # tick 不应触发（还没超时）
        triggered = heuristic.tick()

        assert triggered == []


class TestPaneSkipping:
    """Pane 跳过测试"""

    def test_skip_shell_controlled_pane(self, heuristic, mock_hook_manager):
        """跳过 shell 控制的 pane"""
        mock_hook_manager.get_state.return_value = Mock(
            source="shell",
            status=Mock(is_running=False),
        )

        result = heuristic.analyze("pane-1", "c1", "hash1", 10)

        assert result is None

    def test_skip_claude_controlled_pane(self, heuristic, mock_hook_manager):
        """跳过 claude-code 控制的 pane"""
        mock_hook_manager.get_state.return_value = Mock(
            source="claude-code",
            status=Mock(is_running=False),
        )

        result = heuristic.analyze("pane-1", "c1", "hash1", 10)

        assert result is None

    def test_skip_running_pane(self, heuristic, mock_hook_manager):
        """跳过正在运行的 pane"""
        mock_hook_manager.get_state.return_value = Mock(
            source="gemini",
            status=Mock(is_running=True),
        )

        result = heuristic.analyze("pane-1", "c1", "hash1", 10)

        assert result is None

    def test_allow_idle_pane_with_allowed_source(self, heuristic, mock_hook_manager):
        """允许空闲的允许源 pane"""
        mock_hook_manager.get_state.return_value = Mock(
            source="gemini",
            status=Mock(is_running=False),
        )

        result = heuristic.analyze("pane-1", "c1", "hash1", 5)

        assert result == "start"


class TestStateManagement:
    """状态管理测试"""

    def test_remove_pane(self, heuristic):
        """移除 pane"""
        heuristic._get_state("pane-1")
        assert "pane-1" in heuristic._states

        heuristic.remove_pane("pane-1")

        assert "pane-1" not in heuristic._states

    def test_get_stats(self, heuristic):
        """获取统计"""
        # 创建一些状态
        heuristic._get_state("pane-1").is_active = True
        heuristic._get_state("pane-2").is_active = False

        stats = heuristic.get_stats()

        assert stats["enabled"] is True
        assert stats["total_panes"] == 2
        assert stats["active_panes"] == 1


class TestMetrics:
    """指标测试"""

    def test_start_increments_counter(self, heuristic, mock_hook_manager):
        """start 递增计数器"""
        heuristic.analyze("pane-1", "c1", "hash1", 5)

        assert metrics.get_counter("heuristics.start", {"pane": "pane-1"}) == 1

    def test_idle_increments_counter(self, heuristic, mock_hook_manager):
        """idle 递增计数器"""
        import time

        # 触发 start
        heuristic.analyze("pane-1", "c1", "hash1", 5)

        # 模拟超时
        state = heuristic._get_state("pane-1")
        state.last_activity_at = time.time() - 100

        heuristic.tick()

        assert metrics.get_counter("heuristics.idle", {"pane": "pane-1"}) == 1
