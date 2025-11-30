"""Telemetry - 统一日志和指标入口

提供统一的日志工厂和指标 facade，便于观测性追踪。

日志格式: [module:pane[:8]] msg
指标示例: queue.depth, queue.dropped, transition.ok/fail, timer.errors
"""

import logging
from typing import Any

# 全局日志配置
_LOG_FORMAT = "[%(name)s] %(message)s"


def get_logger(name: str) -> logging.Logger:
    """获取带模块前缀的 logger

    Args:
        name: 模块名（通常使用 __name__）

    Returns:
        配置好的 Logger 实例
    """
    logger = logging.getLogger(name)
    return logger


def format_pane_log(module: str, pane_id: str, msg: str) -> str:
    """格式化带 pane_id 的日志消息

    Args:
        module: 模块名
        pane_id: pane 标识
        msg: 日志消息

    Returns:
        格式化的消息: [module:pane_id[:8]] msg
    """
    pane_short = pane_id[:8] if pane_id else "unknown"
    return f"[{module}:{pane_short}] {msg}"


class Metrics:
    """指标收集 facade

    提供简单的计数器和 gauge 接口。
    当前实现为内存存储，可扩展为 Prometheus/StatsD 等。
    """

    def __init__(self):
        self._counters: dict[str, int] = {}
        self._gauges: dict[str, float] = {}

    def inc(self, name: str, labels: dict[str, str] | None = None, value: int = 1) -> None:
        """递增计数器

        Args:
            name: 指标名（如 "queue.dropped"）
            labels: 可选标签（如 {"pane": pane_id}）
            value: 递增值，默认 1
        """
        key = self._make_key(name, labels)
        self._counters[key] = self._counters.get(key, 0) + value

    def gauge(self, name: str, value: float, labels: dict[str, str] | None = None) -> None:
        """设置 gauge 值

        Args:
            name: 指标名（如 "queue.depth"）
            value: gauge 值
            labels: 可选标签
        """
        key = self._make_key(name, labels)
        self._gauges[key] = value

    def get_counter(self, name: str, labels: dict[str, str] | None = None) -> int:
        """获取计数器值（用于测试）"""
        key = self._make_key(name, labels)
        return self._counters.get(key, 0)

    def get_gauge(self, name: str, labels: dict[str, str] | None = None) -> float:
        """获取 gauge 值（用于测试）"""
        key = self._make_key(name, labels)
        return self._gauges.get(key, 0.0)

    def reset(self) -> None:
        """重置所有指标（用于测试）"""
        self._counters.clear()
        self._gauges.clear()

    def _make_key(self, name: str, labels: dict[str, str] | None) -> str:
        """生成指标 key"""
        if not labels:
            return name
        label_str = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
        return f"{name}{{{label_str}}}"

    def get_all_counters(self) -> dict[str, int]:
        """获取所有计数器（用于调试）"""
        return dict(self._counters)

    def get_all_gauges(self) -> dict[str, float]:
        """获取所有 gauge（用于调试）"""
        return dict(self._gauges)


# 全局指标实例
metrics = Metrics()
