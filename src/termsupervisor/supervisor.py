"""TermSupervisor: 监控 iTerm2 所有 pane 内容变化"""

import asyncio
import difflib
import logging
from datetime import datetime

import iterm2

from termsupervisor import config
from termsupervisor.models import LayoutData, PaneSnapshot, UpdateCallback, PaneChange, PaneHistory, PaneChangeQueue
from termsupervisor.iterm import get_layout, normalize_session_id, session_id_match
from termsupervisor.analysis import create_analyzer, TaskStatus

logger = logging.getLogger(__name__)


class TermSupervisor:
    """iTerm2 终端监控服务"""

    def __init__(
        self,
        interval: float = 5.0,
        exclude_names: list[str] | None = None,
        debug: bool = False,
        min_changed_lines: int = 1,
    ):
        self.interval = interval
        self.exclude_names = exclude_names or []
        self.snapshots: dict[str, PaneSnapshot] = {}
        self._running = False
        self.debug = debug
        self.min_changed_lines = min_changed_lines
        self._callbacks: list[UpdateCallback] = []
        self.layout: LayoutData = LayoutData()

        # 状态分析
        self.pane_histories: dict[str, PaneHistory] = {}
        self.analyzer = create_analyzer()  # 返回空分析器，状态由 HookManager 管理

        # 变化队列 (用于智能节流)
        self.pane_queues: dict[str, PaneChangeQueue] = {}

    def on_update(self, callback: UpdateCallback):
        """注册更新回调"""
        self._callbacks.append(callback)

    async def _notify_callbacks(self):
        """通知所有回调"""
        for callback in self._callbacks:
            try:
                await callback(self.layout)
            except Exception as e:
                self._debug(f"Callback error: {e}")

    def _debug(self, msg: str):
        """打印调试信息"""
        if self.debug:
            now = datetime.now().strftime("%H:%M:%S")
            print(f"[{now}] [DEBUG] {msg}")

    def _get_diff_lines(self, old_content: str, new_content: str) -> list[str]:
        """获取变更的行"""
        diff = difflib.unified_diff(
            old_content.split("\n"),
            new_content.split("\n"),
            lineterm="",
            n=0
        )
        return [
            line for line in diff
            if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
        ]

    def _has_significant_change(self, old_content: str, new_content: str) -> tuple[bool, list[str]]:
        """判断是否有显著变化"""
        if old_content == new_content:
            return False, []

        changed_lines = self._get_diff_lines(old_content, new_content)
        added = sum(1 for line in changed_lines if line.startswith("+"))
        removed = sum(1 for line in changed_lines if line.startswith("-"))

        self._debug(f"变更: +{added} -{removed} (总计 {len(changed_lines)} 行)")

        return len(changed_lines) >= self.min_changed_lines, changed_lines

    def _create_pane_change(
        self,
        content: str,
        changed_lines: list[str],
    ) -> PaneChange:
        """创建 PaneChange 记录"""
        # 获取屏幕最后 N 行
        lines = content.split('\n')
        last_n_lines = lines[-config.SCREEN_LAST_N_LINES:]

        # 构建变化摘要
        added_lines = [l[1:] for l in changed_lines if l.startswith('+')]
        diff_summary = ' | '.join(added_lines[:3])  # 取前 3 行新增内容

        return PaneChange(
            timestamp=datetime.now(),
            change_type="significant",  # 默认，cleaner 会重新分类
            diff_lines=changed_lines,
            diff_summary=diff_summary,
            last_n_lines=last_n_lines,
            changed_line_count=len(changed_lines),
        )

    def _get_or_create_history(self, session_id: str, pane_name: str) -> PaneHistory:
        """获取或创建 PaneHistory"""
        if session_id not in self.pane_histories:
            self.pane_histories[session_id] = PaneHistory(
                session_id=session_id,
                pane_name=pane_name,
            )
        return self.pane_histories[session_id]

    @staticmethod
    def _normalize_content(content: str) -> str:
        """标准化内容"""
        content = content.replace("\xa0", " ")
        return "\n".join(line.rstrip() for line in content.split("\n"))

    async def _get_session_content(self, session: iterm2.Session) -> str:
        """获取 session 的屏幕内容"""
        try:
            contents = await session.async_get_screen_contents()
            lines = [contents.line(i).string for i in range(contents.number_of_lines)]
            return self._normalize_content("\n".join(lines))
        except Exception as e:
            return f"[Error: {e}]"

    def _get_or_create_queue(self, session_id: str) -> PaneChangeQueue:
        """获取或创建 PaneChangeQueue"""
        if session_id not in self.pane_queues:
            self.pane_queues[session_id] = PaneChangeQueue(session_id)
        return self.pane_queues[session_id]

    async def check_updates(self, connection: iterm2.Connection) -> list[str]:
        """检查所有 pane 的更新

        使用 PaneChangeQueue 进行智能节流：
        - 每秒读取内容，更新队列
        - 根据变化大小决定是否触发页面刷新
        - 大变化时记录到队列历史
        """
        app = await iterm2.async_get_app(connection)
        self.layout = await get_layout(app, self.exclude_names)
        now = datetime.now()
        updated_sessions = []
        panes_to_analyze = []

        # 遍历所有 pane 检查更新
        for window in self.layout.windows:
            for tab in window.tabs:
                for pane in tab.panes:
                    session = app.get_session_by_id(pane.session_id)
                    if not session:
                        continue

                    content = await self._get_session_content(session)

                    # 获取或创建变化队列
                    queue = self._get_or_create_queue(pane.session_id)

                    # 使用队列判断是否需要刷新
                    should_refresh = queue.check_and_record(content)

                    if pane.session_id in self.snapshots:
                        if should_refresh:
                            # 需要刷新页面
                            old_snapshot = self.snapshots[pane.session_id]
                            _, changed_lines = self._has_significant_change(
                                old_snapshot.content, content
                            )
                            updated_sessions.append(pane.session_id)
                            self._log_update(now, pane, changed_lines)
                            self.snapshots[pane.session_id] = PaneSnapshot(
                                session_id=pane.session_id,
                                index=pane.index,
                                content=content,
                                updated_at=now,
                            )

                            # 记录变化到 PaneHistory (兼容旧逻辑)
                            history = self._get_or_create_history(pane.session_id, pane.name)
                            pane_change = self._create_pane_change(content, changed_lines)
                            history.add_change(pane_change)
                            panes_to_analyze.append(history)
                    else:
                        # 新发现的 pane
                        print(f"[{now.strftime('%H:%M:%S')}] 发现新 Panel [{pane.index}]: {pane.name}")
                        self.snapshots[pane.session_id] = PaneSnapshot(
                            session_id=pane.session_id,
                            index=pane.index,
                            content=content,
                            updated_at=now,
                        )
                        # 新 pane 也创建历史记录
                        self._get_or_create_history(pane.session_id, pane.name)
                        # 新 pane 直接加入刷新列表
                        updated_sessions.append(pane.session_id)

        # 执行状态分析
        await self._analyze_panes(panes_to_analyze)

        # 检查已关闭的 session
        self._cleanup_closed_sessions(now)

        self.layout.updated_sessions = updated_sessions
        return updated_sessions

    async def _analyze_panes(self, panes: list[PaneHistory]):
        """分析需要分析的 pane 状态"""
        for pane in panes:
            if self.analyzer.should_analyze(pane):
                try:
                    old_status = pane.current_status
                    new_status = await self.analyzer.analyze(pane)

                    # 状态变化时记录日志
                    if old_status != new_status:
                        self._debug(f"Pane {pane.session_id} 状态: {old_status} -> {new_status.value}")

                        # 需要通知的状态变化
                        if new_status.needs_notification:
                            print(f"[状态变化] {pane.pane_name}: {new_status.value} - {pane.status_reason}")
                except Exception as e:
                    logger.error(f"分析 pane {pane.session_id} 失败: {e}")

    def _log_update(self, now: datetime, pane, changed_lines: list[str]):
        """记录更新日志"""
        added = sum(1 for line in changed_lines if line.startswith("+"))
        removed = sum(1 for line in changed_lines if line.startswith("-"))
        print(f"[{now.strftime('%H:%M:%S')}] [{pane.index}] {pane.name} 有更新 (+{added} -{removed}):")

        display_lines = changed_lines[-5:]
        if len(changed_lines) > 5:
            print(f"  ... 省略 {len(changed_lines) - 5} 行")
        for line in display_lines:
            print(f"  {line}")

    def _cleanup_closed_sessions(self, now: datetime):
        """清理已关闭的 session"""
        current_ids = {
            pane.session_id
            for window in self.layout.windows
            for tab in window.tabs
            for pane in tab.panes
        }
        closed_ids = set(self.snapshots.keys()) - current_ids
        for session_id in closed_ids:
            old_index = self.snapshots[session_id].index
            print(f"[{now.strftime('%H:%M:%S')}] Panel [{old_index}] {session_id} 已关闭")
            del self.snapshots[session_id]
            # 同时清理 pane_histories
            if session_id in self.pane_histories:
                del self.pane_histories[session_id]
            # 同时清理 pane_queues
            if session_id in self.pane_queues:
                del self.pane_queues[session_id]

    async def run(self, connection: iterm2.Connection):
        """运行监控服务"""
        self._running = True
        poll_interval = config.POLL_INTERVAL
        print(f"TermSupervisor 已启动，轮询间隔: {poll_interval}s")
        print("按 Ctrl+C 停止\n")

        while self._running:
            try:
                await self.check_updates(connection)
                await self._notify_callbacks()
                await asyncio.sleep(poll_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Error: {e}")
                await asyncio.sleep(poll_interval)

        print("\nTermSupervisor 已停止")

    def stop(self):
        """停止监控服务"""
        self._running = False

    def get_pane_location(self, session_id: str) -> tuple[str, str, str]:
        """获取 pane 所在的 window/tab 名称和 pane 名称

        Returns:
            (window_name, tab_name, pane_name)
        """
        tab_index = 0
        for window in self.layout.windows:
            for tab in window.tabs:
                tab_index += 1
                for pane in tab.panes:
                    if session_id_match(pane.session_id, session_id):
                        # Tab 名称：有名字用名字，否则用 Tab{序号}
                        tab_display = tab.name if tab.name else f"Tab{tab_index}"
                        return (
                            window.name or "Window",
                            tab_display,
                            pane.name or "Pane"
                        )
        # 如果在 layout 中找不到，尝试从 pane_histories 获取名称
        pure_id = normalize_session_id(session_id)
        if pure_id in self.pane_histories:
            pane_name = self.pane_histories[pure_id].pane_name
            return ("Window", "Tab", pane_name or "Pane")
        return ("Window", "Tab", "Pane")

    def get_layout_dict(self) -> dict:
        """获取布局数据字典（包含状态信息）"""
        data = self.layout.to_dict()

        # 添加状态信息到每个 pane
        pane_statuses = {}
        for session_id, history in self.pane_histories.items():
            status = history.current_status
            pane_statuses[session_id] = {
                "status": status.value if status else "unknown",
                "status_color": status.color if status else "gray",
                "status_reason": history.status_reason,
                "is_thinking": history.is_thinking,
                "thinking_duration": round(history.get_thinking_duration(), 1),
                "needs_notification": status.needs_notification if status else False,
            }

        data["pane_statuses"] = pane_statuses
        return data
