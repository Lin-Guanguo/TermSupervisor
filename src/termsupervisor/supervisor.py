"""TermSupervisor: 监控 iTerm2 所有 pane 内容变化"""

import asyncio
import difflib
import logging
import os
from datetime import datetime
from typing import TYPE_CHECKING

from termsupervisor import config
from termsupervisor.iterm.models import LayoutData, PaneSnapshot, UpdateCallback
from termsupervisor.analysis.change_queue import PaneChange, PaneHistory, PaneChangeQueue
from termsupervisor.iterm import get_layout, normalize_session_id, session_id_match, ITerm2Client
from termsupervisor.analysis import ContentCleaner
from termsupervisor.pane import TaskStatus

if TYPE_CHECKING:
    from termsupervisor.hooks.manager import HookManager
    from termsupervisor.analysis.content_heuristic import ContentHeuristicAnalyzer
    from termsupervisor.hooks.sources.shell import ShellHookSource

logger = logging.getLogger(__name__)


class TermSupervisor:
    """iTerm2 终端监控服务

    所有 iTerm2 操作通过 ITerm2Client 进行，不直接调用 iterm2 API。
    """

    def __init__(
        self,
        interval: float = 5.0,
        exclude_names: list[str] | None = None,
        debug: bool = False,
        min_changed_lines: int = 1,
        hook_manager: "HookManager | None" = None,
        iterm_client: ITerm2Client | None = None,
    ):
        self.interval = interval
        self.exclude_names = exclude_names or []
        self.snapshots: dict[str, PaneSnapshot] = {}
        self._running = False
        self.debug = debug
        self.min_changed_lines = min_changed_lines
        self._callbacks: list[UpdateCallback] = []
        self.layout: LayoutData = LayoutData()

        # 状态分析 (legacy, 仅保留 history 用于变化记录)
        self.pane_histories: dict[str, PaneHistory] = {}

        # 依赖注入
        self._hook_manager = hook_manager
        self._iterm_client = iterm_client
        self._heuristic_analyzer: "ContentHeuristicAnalyzer | None" = None
        self._shell_source: "ShellHookSource | None" = None

        # 变化队列 (用于智能节流)
        self.pane_queues: dict[str, PaneChangeQueue] = {}

    def set_hook_manager(self, hook_manager: "HookManager") -> None:
        """设置 HookManager（用于状态获取和事件发送）"""
        self._hook_manager = hook_manager

    def set_iterm_client(self, client: ITerm2Client) -> None:
        """设置 ITerm2Client"""
        self._iterm_client = client

    def set_heuristic_analyzer(self, analyzer: "ContentHeuristicAnalyzer") -> None:
        """设置 ContentHeuristicAnalyzer（用于内容启发式分析）"""
        self._heuristic_analyzer = analyzer

    def set_shell_source(self, shell_source: "ShellHookSource") -> None:
        """设置 ShellHookSource（用于获取 PromptMonitor 状态）"""
        self._shell_source = shell_source

    def _get_hook_manager(self) -> "HookManager":
        """获取 HookManager"""
        if self._hook_manager is None:
            raise RuntimeError("HookManager not set. Call set_hook_manager() first.")
        return self._hook_manager

    def _get_iterm_client(self) -> ITerm2Client:
        """获取 ITerm2Client"""
        if self._iterm_client is None:
            raise RuntimeError("ITerm2Client not set. Call set_iterm_client() first.")
        return self._iterm_client

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

    def _get_or_create_queue(self, session_id: str) -> PaneChangeQueue:
        """获取或创建 PaneChangeQueue"""
        if session_id not in self.pane_queues:
            self.pane_queues[session_id] = PaneChangeQueue(session_id)
        return self.pane_queues[session_id]

    async def check_updates(self) -> list[str]:
        """检查所有 pane 的更新

        使用 PaneChangeQueue 进行智能节流：
        - 每秒读取内容，更新队列
        - 根据变化大小决定是否触发页面刷新
        - 大变化时记录到队列历史

        注意：需要先调用 set_iterm_client() 设置客户端。
        """
        client = self._get_iterm_client()
        app = await client.get_app()
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

                    content = await client.get_session_content(session)
                    # Fetch job metadata (jobName, jobPid, commandLine, tty)
                    job_metadata = await client.get_session_job_metadata(session)

                    # 获取或创建变化队列
                    queue = self._get_or_create_queue(pane.session_id)

                    # 同步 WAITING 状态到队列（影响刷新阈值）
                    hook_manager = self._get_hook_manager()
                    pane_status = hook_manager.get_status(pane.session_id)
                    queue.set_waiting(pane_status == TaskStatus.WAITING_APPROVAL)

                    # 使用队列判断是否需要刷新
                    should_refresh = queue.check_and_record(content)

                    # Always track history for heuristic analysis
                    history = self._get_or_create_history(pane.session_id, pane.name)
                    # Refresh pane_name every poll (user may rename pane/tab)
                    history.pane_name = pane.name
                    # Update job metadata for whitelist matching and tooltip display
                    history.job = job_metadata
                    panes_to_analyze.append(history)

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
                            pane_change = self._create_pane_change(content, changed_lines)
                            history.add_change(pane_change)

                            # 通知 HookManager 内容变化（触发 WAITING_APPROVAL 兜底恢复）
                            hook_manager = self._get_hook_manager()
                            content_hash = ContentCleaner.content_hash(content)
                            await hook_manager.emit_event(
                                source="content",
                                pane_id=pane.session_id,
                                event_type="update",  # Phase 2: renamed from "changed"
                                data={"content": content, "content_hash": content_hash},
                                log=False,  # 内容事件太频繁，禁用日志
                            )
                    else:
                        # 新发现的 pane
                        print(f"[{now.strftime('%H:%M:%S')}] 发现新 Panel [{pane.index}]: {pane.name}")
                        self.snapshots[pane.session_id] = PaneSnapshot(
                            session_id=pane.session_id,
                            index=pane.index,
                            content=content,
                            updated_at=now,
                        )
                        # 新 pane 直接加入刷新列表
                        updated_sessions.append(pane.session_id)

        # 执行状态分析 (runs for ALL panes on every poll)
        await self._analyze_panes(panes_to_analyze)

        # 检查已关闭的 session
        self._cleanup_closed_sessions(now)

        self.layout.updated_sessions = updated_sessions
        return updated_sessions

    async def _analyze_panes(self, panes: list[PaneHistory]):
        """分析需要分析的 pane 状态

        Runs content heuristic analysis for whitelisted panes.
        Passes both job_name (preferred) and pane_title (fallback) for gating.
        """
        if not self._heuristic_analyzer or not self._shell_source:
            return

        hook_manager = self._get_hook_manager()

        for history in panes:
            pane_id = history.session_id

            # Get queue for this pane
            queue = self.pane_queues.get(pane_id)
            if not queue:
                continue

            # Get current state from HookManager
            state = hook_manager.get_state(pane_id)
            if not state:
                continue

            # Get PromptMonitor status from ShellHookSource
            prompt_status = self._shell_source.get_prompt_monitor_status(pane_id)

            # Run heuristic analysis with both job_name and pane_title
            job = history.job
            await self._heuristic_analyzer.process_and_emit(
                pane_id=pane_id,
                pane_title=history.pane_name,
                current_status=state.status,
                current_source=state.source,
                prompt_status=prompt_status,
                queue=queue,
                job_name=job.job_name if job else "",
                command_line=job.redacted_command_line() if job else "",
            )

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

    async def run(self):
        """运行监控服务

        注意：需要先调用 set_iterm_client() 设置客户端。
        """
        self._running = True
        poll_interval = config.POLL_INTERVAL
        print(f"TermSupervisor 已启动，轮询间隔: {poll_interval}s")
        print("按 Ctrl+C 停止\n")

        while self._running:
            try:
                await self.check_updates()
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

    @staticmethod
    def _shorten_path(path: str) -> str:
        """Replace home directory prefix with ~"""
        if not path:
            return ""
        home = os.path.expanduser("~")
        if path.startswith(home):
            return "~" + path[len(home):]
        return path

    def get_layout_dict(self) -> dict:
        """获取布局数据字典（包含状态信息和 job metadata）"""
        data = self.layout.to_dict()

        # 从 HookManager 获取状态信息
        hook_manager = self._get_hook_manager()
        pane_statuses = {}

        # 遍历当前布局中的所有 pane
        for window in self.layout.windows:
            for tab in window.tabs:
                for pane in tab.panes:
                    session_id = pane.session_id
                    state = hook_manager.get_state(session_id)
                    history = self.pane_histories.get(session_id)
                    job = history.job if history else None
                    path = self._shorten_path(job.path) if job else ""

                    if state:
                        status = state.status
                        pane_statuses[session_id] = {
                            "status": status.value,
                            "status_color": status.color,
                            "status_reason": state.description,
                            "is_running": status.is_running,
                            "needs_notification": status.needs_notification,
                            "needs_attention": status.needs_attention,
                            "display": status.display,
                            # Job metadata for tooltip
                            "job_name": job.job_name if job else "",
                            "path": path,
                        }
                    else:
                        # Pane 尚未被 HookManager 跟踪，使用默认 IDLE 状态
                        pane_statuses[session_id] = {
                            "status": TaskStatus.IDLE.value,
                            "status_color": TaskStatus.IDLE.color,
                            "status_reason": "",
                            "is_running": False,
                            "needs_notification": False,
                            "needs_attention": False,
                            "display": "",
                            # Job metadata for tooltip
                            "job_name": job.job_name if job else "",
                            "path": path,
                        }

        data["pane_statuses"] = pane_statuses
        return data
