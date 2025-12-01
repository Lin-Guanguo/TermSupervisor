"""PaneStateMachine - 每个 pane 的状态机

职责：
- 维护 status/source/started_at/state_id/history
- 根据流转表匹配规则
- 匹配成功生成 StateChange 回调 Pane
- 支持序列化/反序列化
"""

import itertools
from collections import deque
from datetime import datetime

from ..telemetry import get_logger, metrics
from ..config import STATE_HISTORY_MAX_LENGTH, STATE_HISTORY_PERSIST_LENGTH
from .types import (
    TaskStatus,
    HookEvent,
    StateChange,
    StateHistoryEntry,
    StateSnapshot,
)
from .transitions import find_matching_rules

logger = get_logger(__name__)

# 全局 state_id 计数器
_state_id_counter = itertools.count(1)


def _next_state_id() -> int:
    """获取下一个 state_id（自增）"""
    return next(_state_id_counter)


class PaneStateMachine:
    """每个 Pane 的状态机

    维护单个 pane 的状态和历史。

    Attributes:
        pane_id: pane 标识
        status: 当前状态
        source: 状态来源
        started_at: RUNNING 开始时间（用于计算 LONG_RUNNING）
        state_id: 状态唯一 ID（每次成功流转自增）
        history: 状态变化历史（环形队列）
        pane_generation: pane 代次
    """

    def __init__(
        self,
        pane_id: str,
        status: TaskStatus = TaskStatus.IDLE,
        source: str = "shell",
        started_at: float | None = None,
        state_id: int | None = None,
        pane_generation: int = 1,
    ):
        self.pane_id = pane_id
        self._status = status
        self._source = source
        self._started_at = started_at
        self._state_id = state_id if state_id is not None else _next_state_id()
        self._pane_generation = pane_generation
        self._description = ""

        # 环形历史队列
        self._history: deque[StateHistoryEntry] = deque(maxlen=STATE_HISTORY_MAX_LENGTH)

    # === 属性 ===

    @property
    def status(self) -> TaskStatus:
        return self._status

    @property
    def source(self) -> str:
        return self._source

    @property
    def started_at(self) -> float | None:
        return self._started_at

    @property
    def state_id(self) -> int:
        return self._state_id

    @property
    def pane_generation(self) -> int:
        return self._pane_generation

    @property
    def description(self) -> str:
        return self._description

    @property
    def history(self) -> list[StateHistoryEntry]:
        return list(self._history)

    # === 核心方法 ===

    def process(self, event: HookEvent) -> StateChange | None:
        """处理事件

        根据流转表匹配规则，执行状态转换。

        Args:
            event: Hook 事件

        Returns:
            StateChange 对象（发生转换时），或 None（无转换）
        """
        signal = event.signal
        pane_short = self.pane_id[:8]

        # 1. 检查 generation（拒绝旧事件）
        if event.pane_generation < self._pane_generation:
            logger.debug(
                f"[SM:{pane_short}] Rejected stale event: "
                f"generation {event.pane_generation} < {self._pane_generation}"
            )
            metrics.inc("transition.stale_generation", {"pane": pane_short})
            self._add_history(
                signal,
                self._status,
                self._status,
                success=False,
                description="stale_generation",
            )
            return None

        # 2. 查找所有可能匹配的规则
        rules = find_matching_rules(signal, self._status, self._source)

        if not rules:
            logger.debug(f"[SM:{pane_short}] No rule matched for {signal}")
            self._add_history(
                signal,
                self._status,
                self._status,
                success=False,
                description="no_rule_matched",
            )
            return None

        # 3. 构建状态快照
        snapshot = StateSnapshot(
            status=self._status,
            source=self._source,
            state_id=self._state_id,
            started_at=self._started_at,
            pane_generation=self._pane_generation,
            now=datetime.now().timestamp(),
        )

        # 4. 检查每个规则的谓词，找到第一个满足的
        rule = None
        for candidate in rules:
            if candidate.check_predicates(event, snapshot):
                rule = candidate
                break

        if rule is None:
            logger.debug(f"[SM:{pane_short}] All predicates failed for {signal}")
            self._add_history(
                signal,
                self._status,
                self._status,
                success=False,
                description="predicate_failed",
            )
            metrics.inc("transition.predicate_fail", {"pane": pane_short})
            return None

        # 5. 执行状态转换
        old_status = self._status
        old_source = self._source
        old_started_at = self._started_at

        new_status = rule.to_status
        new_source = rule.get_target_source(self._source)
        new_description = rule.format_description(event.data)

        # 特殊处理：PreToolUse 同源时不重置 started_at
        should_reset_started_at = rule.reset_started_at
        if signal == "claude-code.PreToolUse" and old_source == "claude-code":
            should_reset_started_at = False

        if should_reset_started_at:
            new_started_at = datetime.now().timestamp()
        else:
            new_started_at = old_started_at

        # 计算运行时长（在更新 started_at 之前）
        running_duration = 0.0
        if old_started_at:
            running_duration = datetime.now().timestamp() - old_started_at

        # 更新状态
        self._status = new_status
        self._source = new_source
        self._description = new_description
        self._started_at = new_started_at
        self._state_id = _next_state_id()

        # 记录历史
        self._add_history(signal, old_status, new_status, success=True, description=new_description)

        # 记录指标
        metrics.inc("transition.ok", {"pane": pane_short})

        logger.info(
            f"[SM:{pane_short}] {old_status.value} → {new_status.value} | "
            f"signal={signal} | source={new_source} | state_id={self._state_id}"
        )

        # 6. 构建状态变化对象
        change = StateChange(
            old_status=old_status,
            new_status=new_status,
            old_source=old_source,
            new_source=new_source,
            description=new_description,
            state_id=self._state_id,
            started_at=self._started_at,
            running_duration=running_duration,
        )

        return change

    def increment_generation(self) -> int:
        """递增 pane_generation

        在 pane 重建或 session 重用时调用。

        Returns:
            新的 generation
        """
        self._pane_generation += 1
        return self._pane_generation

    # === 历史 ===

    def _add_history(
        self,
        signal: str,
        from_status: TaskStatus,
        to_status: TaskStatus,
        success: bool,
        description: str = "",
    ) -> None:
        """添加历史记录"""
        entry = StateHistoryEntry(
            signal=signal,
            from_status=from_status,
            to_status=to_status,
            success=success,
            description=description,
        )
        self._history.append(entry)

    def get_history_log(self) -> str:
        """获取历史日志（调试用）"""
        if not self._history:
            return "  (no history)"
        return "\n".join(f"  {entry}" for entry in self._history)

    # === 序列化 ===

    def to_dict(self) -> dict:
        """序列化为字典"""
        return {
            "pane_id": self.pane_id,
            "status": self._status.value,
            "source": self._source,
            "started_at": self._started_at,
            "state_id": self._state_id,
            "pane_generation": self._pane_generation,
            "description": self._description,
            # 只持久化最近 N 条历史
            "history": [
                {
                    "signal": e.signal,
                    "from_status": e.from_status.value,
                    "to_status": e.to_status.value,
                    "success": e.success,
                    "description": e.description,
                    "timestamp": e.timestamp,
                }
                for e in list(self._history)[-STATE_HISTORY_PERSIST_LENGTH:]
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PaneStateMachine":
        """从字典反序列化"""
        machine = cls(
            pane_id=data["pane_id"],
            status=TaskStatus(data["status"]),
            source=data["source"],
            started_at=data.get("started_at"),
            state_id=data.get("state_id"),
            pane_generation=data.get("pane_generation", 1),
        )
        machine._description = data.get("description", "")

        # 恢复历史
        for h in data.get("history", []):
            entry = StateHistoryEntry(
                signal=h["signal"],
                from_status=TaskStatus(h["from_status"]),
                to_status=TaskStatus(h["to_status"]),
                success=h["success"],
                description=h.get("description", ""),
                timestamp=h.get("timestamp", 0.0),
            )
            machine._history.append(entry)

        # 加载后递增 generation（避免旧事件干扰）
        machine.increment_generation()

        return machine

    # === 便捷方法 ===

    def get_running_duration(self) -> float:
        """获取运行时长（秒）"""
        if self._started_at is None:
            return 0.0
        return datetime.now().timestamp() - self._started_at

    def is_running(self) -> bool:
        """是否在运行中"""
        return self._status in {TaskStatus.RUNNING, TaskStatus.LONG_RUNNING}

    def should_check_long_running(self, threshold_seconds: float) -> bool:
        """是否应该检查 LONG_RUNNING

        Args:
            threshold_seconds: 阈值（秒）

        Returns:
            是否应该触发 timer.check
        """
        if self._status != TaskStatus.RUNNING:
            return False
        return self.get_running_duration() > threshold_seconds

    def get_state_snapshot(self) -> StateSnapshot:
        """获取状态快照"""
        return StateSnapshot(
            status=self._status,
            source=self._source,
            state_id=self._state_id,
            started_at=self._started_at,
            pane_generation=self._pane_generation,
        )
