"""内置谓词库

提供 TransitionRule 可用的谓词函数。
谓词函数签名: (event: HookEvent, snapshot: StateSnapshot) -> bool

可用谓词：
- require_exit_code(code): 检查 exit_code 是否匹配
- require_same_generation(): 检查 generation 是否一致
- require_status_in(statuses): 检查状态是否在集合中
- require_running_duration_gt(sec): 检查运行时长是否超过阈值
- require_state_id_at_least(n): 检查 state_id 是否足够大
- require_source_match(): 检查事件源与当前状态源是否一致
"""

from typing import Callable

from .types import HookEvent, StateSnapshot, TaskStatus, Predicate


def require_exit_code(code: int) -> Predicate:
    """创建检查 exit_code 的谓词

    Args:
        code: 期望的 exit_code

    Returns:
        谓词函数
    """
    def predicate(event: HookEvent, snapshot: StateSnapshot) -> bool:
        return event.data.get("exit_code") == code

    return predicate


def require_exit_code_nonzero() -> Predicate:
    """创建检查 exit_code 非零的谓词

    Returns:
        谓词函数
    """
    def predicate(event: HookEvent, snapshot: StateSnapshot) -> bool:
        exit_code = event.data.get("exit_code")
        return exit_code is not None and exit_code != 0

    return predicate


def require_same_generation() -> Predicate:
    """创建检查 generation 一致的谓词

    用于拒绝旧的内容/事件。

    Returns:
        谓词函数
    """
    def predicate(event: HookEvent, snapshot: StateSnapshot) -> bool:
        return event.pane_generation >= snapshot.pane_generation

    return predicate


def require_status_in(statuses: set[TaskStatus]) -> Predicate:
    """创建检查状态是否在集合中的谓词

    Args:
        statuses: 允许的状态集合

    Returns:
        谓词函数
    """
    def predicate(event: HookEvent, snapshot: StateSnapshot) -> bool:
        return snapshot.status in statuses

    return predicate


def require_running_duration_gt(seconds: float) -> Predicate:
    """创建检查运行时长的谓词

    用于 LONG_RUNNING 检测。

    Args:
        seconds: 阈值（秒）

    Returns:
        谓词函数
    """
    def predicate(event: HookEvent, snapshot: StateSnapshot) -> bool:
        if snapshot.started_at is None:
            return False
        duration = snapshot.now - snapshot.started_at
        return duration > seconds

    return predicate


def require_state_id_at_least(n: int) -> Predicate:
    """创建检查 state_id 的谓词

    用于防止旧事件覆盖新状态。

    Args:
        n: 最小 state_id

    Returns:
        谓词函数
    """
    def predicate(event: HookEvent, snapshot: StateSnapshot) -> bool:
        return snapshot.state_id >= n

    return predicate


def require_source_match() -> Predicate:
    """创建检查事件源与状态源一致的谓词

    用于实现源隔离：同源事件只能收敛本源状态。

    Returns:
        谓词函数
    """
    def predicate(event: HookEvent, snapshot: StateSnapshot) -> bool:
        return event.source == snapshot.source

    return predicate


def always_true() -> Predicate:
    """总是返回 True 的谓词（用于测试）"""
    def predicate(event: HookEvent, snapshot: StateSnapshot) -> bool:
        return True

    return predicate


def always_false() -> Predicate:
    """总是返回 False 的谓词（用于测试）"""
    def predicate(event: HookEvent, snapshot: StateSnapshot) -> bool:
        return False

    return predicate


def reject_same_source_in_long_running() -> Predicate:
    """拒绝 LONG_RUNNING 状态下同源事件的谓词

    用于实现 sticky LONG_RUNNING：在 LONG_RUNNING 时，同源的 RUNNING 信号被忽略，
    除非 generation 增加（新会话开始）。

    Returns:
        谓词函数
    """
    def predicate(event: HookEvent, snapshot: StateSnapshot) -> bool:
        # 如果不是 LONG_RUNNING，允许
        if snapshot.status != TaskStatus.LONG_RUNNING:
            return True
        # 如果是跨源，允许
        if event.source != snapshot.source:
            return True
        # 如果 generation 增加（新会话），允许
        if event.pane_generation > snapshot.pane_generation:
            return True
        # 同源 + LONG_RUNNING + 同 generation：拒绝
        return False

    return predicate
