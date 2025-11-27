"""TermSupervisor: 监控 iTerm2 所有 pane 内容变化"""

import asyncio
import difflib
from datetime import datetime

import iterm2

from termsupervisor import config
from termsupervisor.models import LayoutData, PaneSnapshot, UpdateCallback
from termsupervisor.iterm import get_layout


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

    async def check_updates(self, connection: iterm2.Connection) -> list[str]:
        """检查所有 pane 的更新"""
        app = await iterm2.async_get_app(connection)
        self.layout = await get_layout(app, self.exclude_names)
        now = datetime.now()
        updated_sessions = []

        # 遍历所有 pane 检查更新
        for window in self.layout.windows:
            for tab in window.tabs:
                for pane in tab.panes:
                    session = app.get_session_by_id(pane.session_id)
                    if not session:
                        continue

                    content = await self._get_session_content(session)

                    if pane.session_id in self.snapshots:
                        old_snapshot = self.snapshots[pane.session_id]
                        has_change, changed_lines = self._has_significant_change(
                            old_snapshot.content, content
                        )
                        if has_change:
                            updated_sessions.append(pane.session_id)
                            self._log_update(now, pane, changed_lines)
                            self.snapshots[pane.session_id] = PaneSnapshot(
                                session_id=pane.session_id,
                                index=pane.index,
                                content=content,
                                updated_at=now,
                            )
                    else:
                        print(f"[{now.strftime('%H:%M:%S')}] 发现新 Panel [{pane.index}]: {pane.name}")
                        self.snapshots[pane.session_id] = PaneSnapshot(
                            session_id=pane.session_id,
                            index=pane.index,
                            content=content,
                            updated_at=now,
                        )

        # 检查已关闭的 session
        self._cleanup_closed_sessions(now)

        self.layout.updated_sessions = updated_sessions
        return updated_sessions

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

    async def run(self, connection: iterm2.Connection):
        """运行监控服务"""
        self._running = True
        print(f"TermSupervisor 已启动，监控间隔: {self.interval}s")
        print("按 Ctrl+C 停止\n")

        while self._running:
            try:
                await self.check_updates(connection)
                await self._notify_callbacks()
                await asyncio.sleep(self.interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Error: {e}")
                await asyncio.sleep(self.interval)

        print("\nTermSupervisor 已停止")

    def stop(self):
        """停止监控服务"""
        self._running = False

    def get_layout_dict(self) -> dict:
        """获取布局数据字典"""
        return self.layout.to_dict()
