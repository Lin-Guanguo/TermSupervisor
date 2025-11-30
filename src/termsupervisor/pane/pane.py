"""Pane - 显示层

职责：
- 处理 StateChange（来自 PaneStateMachine）
- DONE/FAILED → IDLE 时延迟展示（保持显示 DONE/FAILED 5s，状态机已转换到 IDLE）
- state_id 防乱序
- 通知抑制（短任务 < 3s 或 focus）
- 内容更新触发渲染
- 序列化显示状态与内容
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Any, TYPE_CHECKING

from ..telemetry import get_logger, metrics
from ..config import DISPLAY_DELAY_SECONDS, NOTIFICATION_MIN_DURATION_SECONDS
from .types import TaskStatus, StateChange, DisplayState

if TYPE_CHECKING:
    from ..timer import Timer

logger = get_logger(__name__)

# 回调类型
OnDisplayChangeCallback = Callable[[DisplayState], Any]


class Pane:
    """Pane 显示层

    处理显示逻辑，包括延迟显示和通知抑制。

    Attributes:
        pane_id: pane 标识
        display_state: 当前显示状态
        content: pane 内容
        content_hash: 内容 hash
    """

    def __init__(
        self,
        pane_id: str,
        timer: "Timer | None" = None,
        focus_checker: "Callable[[str], bool] | None" = None,
    ):
        """初始化 Pane

        Args:
            pane_id: pane 标识
            timer: Timer 实例（用于延迟显示）
            focus_checker: focus 检查函数
        """
        self.pane_id = pane_id
        self._timer = timer
        self._focus_checker = focus_checker

        # 显示状态
        self._display_state = DisplayState(
            status=TaskStatus.IDLE,
            source="shell",
            description="",
            state_id=0,
        )

        # 内容
        self._content: str = ""
        self._content_hash: str = ""

        # 回调
        self._on_display_change: OnDisplayChangeCallback | None = None

        # 延迟任务名
        self._delay_task_name = f"pane_display_delay_{pane_id[:8]}"

    # === 属性 ===

    @property
    def display_state(self) -> DisplayState:
        return self._display_state

    @property
    def content(self) -> str:
        return self._content

    @property
    def content_hash(self) -> str:
        return self._content_hash

    @property
    def status(self) -> TaskStatus:
        return self._display_state.status

    @property
    def source(self) -> str:
        return self._display_state.source

    @property
    def state_id(self) -> int:
        return self._display_state.state_id

    # === 配置 ===

    def set_timer(self, timer: "Timer") -> None:
        """设置 Timer"""
        self._timer = timer

    def set_focus_checker(self, checker: Callable[[str], bool]) -> None:
        """设置 focus 检查函数"""
        self._focus_checker = checker

    def set_on_display_change(self, callback: OnDisplayChangeCallback | None) -> None:
        """设置显示变化回调"""
        self._on_display_change = callback

    # === 状态处理 ===

    def handle_state_change(self, change: StateChange) -> bool:
        """处理状态变化

        延迟展示策略：
        - DONE/FAILED → IDLE 时，延迟展示 IDLE（保持显示 DONE/FAILED 5s）
        - 其他状态变化立即展示

        Args:
            change: 状态变化记录

        Returns:
            是否更新了显示（延迟展示时返回 False，表示显示暂未改变）
        """
        pane_short = self.pane_id[:8]

        # 1. state_id 防乱序
        if change.state_id < self._display_state.state_id:
            logger.debug(
                f"[Pane:{pane_short}] Rejected stale state_id: "
                f"{change.state_id} < {self._display_state.state_id}"
            )
            metrics.inc("pane.stale_state_id", {"pane": pane_short})
            return False

        old_status = self._display_state.status
        new_status = change.new_status

        # 2. 取消旧的延迟任务（如果有）
        self._cancel_delay_task()

        # 3. 检查是否需要延迟展示
        # DONE/FAILED → IDLE 时，延迟展示（状态机已转换，但显示层保持原状态 5s）
        if old_status in {TaskStatus.DONE, TaskStatus.FAILED} and new_status == TaskStatus.IDLE:
            if self._timer:
                self._register_delayed_display(change)
                logger.debug(
                    f"[Pane:{pane_short}] Delayed display: {old_status.value} → IDLE (5s)"
                )
                return False  # 显示暂未改变

        # 4. 立即更新显示状态
        return self._update_display(change)

    def _update_display(self, change: StateChange) -> bool:
        """更新显示状态

        Args:
            change: 状态变化

        Returns:
            是否有变化
        """
        pane_short = self.pane_id[:8]

        old_state = self._display_state
        self._display_state = DisplayState(
            status=change.new_status,
            source=change.new_source,
            description=change.description,
            state_id=change.state_id,
            started_at=change.started_at,
            running_duration=change.running_duration,
            content_hash=self._content_hash,
        )

        logger.info(
            f"[Pane:{pane_short}] Display: {old_state.status.value} → "
            f"{change.new_status.value} | state_id={change.state_id}"
        )

        # 触发回调
        if self._on_display_change:
            self._on_display_change(self._display_state)

        return True

    def _register_delayed_display(self, change: StateChange) -> None:
        """注册延迟展示任务（DONE/FAILED → IDLE 时保持原显示 5s）

        设计说明：
        - 状态机已经转换到 IDLE，但显示层延迟更新
        - 5s 后再展示 IDLE 状态
        - 如果中间有新状态变化，延迟任务会被取消
        """
        if not self._timer:
            return

        state_id_at_register = change.state_id

        def delayed_update():
            # 检查 state_id 是否被更新的状态覆盖
            # 如果显示的 state_id 已经更新了，说明有新状态，不再展示这个旧的 IDLE
            if self._display_state.state_id >= state_id_at_register:
                logger.debug(
                    f"[Pane:{self.pane_id[:8]}] Delayed display skipped: "
                    f"display state_id ({self._display_state.state_id}) >= {state_id_at_register}"
                )
                return

            # 展示延迟的 IDLE 状态
            self._update_display(change)
            logger.info(f"[Pane:{self.pane_id[:8]}] Delayed display: → IDLE")

        self._timer.register_delay(
            self._delay_task_name,
            DISPLAY_DELAY_SECONDS,
            delayed_update,
        )

    def _cancel_delay_task(self) -> None:
        """取消延迟任务"""
        if self._timer and self._timer.has_delay(self._delay_task_name):
            self._timer.cancel_delay(self._delay_task_name)

    # === 通知抑制 ===

    def should_suppress_notification(self) -> tuple[bool, str]:
        """判断是否应抑制通知

        条件：
        1. 运行时长 < 3s（短任务）
        2. pane 正在 focus

        Returns:
            (是否抑制, 抑制原因)
        """
        status = self._display_state.status

        # 只对 DONE/FAILED 判断
        if status not in {TaskStatus.DONE, TaskStatus.FAILED}:
            return False, ""

        # 条件 1: 短任务
        duration = self._display_state.running_duration
        if duration < NOTIFICATION_MIN_DURATION_SECONDS:
            return True, f"duration={duration:.1f}s"

        # 条件 2: 正在 focus
        if self._focus_checker and self._focus_checker(self.pane_id):
            return True, "focused"

        return False, ""

    # === 内容更新 ===

    def update_content(self, content: str, content_hash: str = "") -> None:
        """更新内容

        Args:
            content: 新内容
            content_hash: 内容 hash（可选）
        """
        self._content = content
        self._content_hash = content_hash
        self._display_state.content_hash = content_hash

        # 触发回调（如果需要）
        if self._on_display_change:
            self._on_display_change(self._display_state)

    # === 序列化 ===

    def to_dict(self) -> dict:
        """序列化为字典"""
        return {
            "pane_id": self.pane_id,
            "display_state": self._display_state.to_dict(),
            "content_hash": self._content_hash,
            # 不持久化 content（太大）
        }

    @classmethod
    def from_dict(
        cls,
        data: dict,
        timer: "Timer | None" = None,
        focus_checker: "Callable[[str], bool] | None" = None,
    ) -> "Pane":
        """从字典反序列化"""
        pane = cls(
            pane_id=data["pane_id"],
            timer=timer,
            focus_checker=focus_checker,
        )

        # 恢复显示状态
        ds = data.get("display_state", {})
        pane._display_state = DisplayState(
            status=TaskStatus(ds.get("status", "idle")),
            source=ds.get("source", "shell"),
            description=ds.get("description", ""),
            state_id=ds.get("state_id", 0),
            started_at=ds.get("started_at"),
            running_duration=ds.get("running_duration", 0.0),
            content_hash=data.get("content_hash", ""),
        )
        pane._content_hash = data.get("content_hash", "")

        return pane

    # === 便捷方法 ===

    def is_running(self) -> bool:
        """是否在运行中"""
        return self._display_state.status in {TaskStatus.RUNNING, TaskStatus.LONG_RUNNING}

    def needs_notification(self) -> bool:
        """是否需要通知"""
        return self._display_state.status.needs_notification

    def needs_attention(self) -> bool:
        """是否需要关注"""
        return self._display_state.status.needs_attention

    def get_display_dict(self) -> dict:
        """获取显示字典（用于 WebSocket）"""
        return self._display_state.to_dict()
