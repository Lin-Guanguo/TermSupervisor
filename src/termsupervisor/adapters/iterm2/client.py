"""iTerm2 API 客户端封装"""

import asyncio
import logging
import re
from dataclasses import dataclass

import iterm2

logger = logging.getLogger(__name__)

from termsupervisor import config
from termsupervisor.adapters.iterm2.naming import set_session_name, set_tab_name, set_window_name

# Token-like patterns to mask (API keys, secrets, tokens)
_TOKEN_PATTERNS = [
    re.compile(r"(sk-[a-zA-Z0-9]{20,})"),  # OpenAI keys
    re.compile(r"(ghp_[a-zA-Z0-9]{36,})"),  # GitHub PAT
    re.compile(r"(gho_[a-zA-Z0-9]{36,})"),  # GitHub OAuth
    re.compile(r"(glpat-[a-zA-Z0-9\-]{20,})"),  # GitLab PAT
    re.compile(r"(xox[baprs]-[a-zA-Z0-9\-]{10,})"),  # Slack tokens
    re.compile(r"([a-zA-Z0-9_\-]{32,})"),  # Generic long alphanumeric (likely token)
]


def _mask_tokens(text: str) -> str:
    """Mask token-like patterns in text"""
    result = text
    for pattern in _TOKEN_PATTERNS:
        result = pattern.sub(lambda m: m.group(0)[:4] + "***", result)
    return result


@dataclass
class JobMetadata:
    """Foreground job metadata from iTerm2 Shell Integration"""

    job_name: str = ""
    job_pid: int | None = None
    command_line: str = ""  # Redacted for logging
    tty: str = ""
    path: str = ""  # Current working directory

    def redacted_command_line(self) -> str:
        """Return truncated and token-masked command line for safe logging"""
        if not self.command_line:
            return ""
        # First mask tokens, then truncate
        masked = _mask_tokens(self.command_line)
        max_len = config.COMMAND_LINE_MAX_LENGTH
        if len(masked) <= max_len:
            return masked
        return masked[:max_len] + "..."


class ITerm2Client:
    """iTerm2 API 操作封装"""

    def __init__(self, connection: iterm2.Connection):
        self.connection = connection

    async def get_app(self) -> iterm2.App | None:
        """获取 iTerm2 App 实例"""
        return await iterm2.async_get_app(self.connection)

    async def get_session_by_id(self, session_id: str) -> iterm2.Session | None:
        """根据 session_id 获取 Session 对象"""
        try:
            app = await self.get_app()
            if app is None:
                return None
            return app.get_session_by_id(session_id)
        except Exception as e:
            print(f"[ITerm2Client] 获取 session {session_id} 失败: {e}")
            return None

    async def activate_session(self, session_id: str) -> bool:
        """激活指定的 session"""
        try:
            app = await self.get_app()
            if app is None:
                return False
            session = app.get_session_by_id(session_id)
            if session:
                await session.async_activate()
                return True
            return False
        except Exception as e:
            print(f"[ITerm2Client] 激活 session {session_id} 失败: {e}")
            return False

    async def rename_window(self, window_id: str, new_name: str) -> bool:
        """重命名 Window"""
        try:
            app = await self.get_app()
            if app is None:
                return False
            for window in app.windows:
                if window.window_id == window_id:
                    success = await set_window_name(window, new_name)
                    if success:
                        print(f"[ITerm2Client] Window {window_id} 重命名为: {new_name}")
                    return success
            print(f"[ITerm2Client] 未找到 Window: {window_id}")
            return False
        except Exception as e:
            print(f"[ITerm2Client] 重命名 Window {window_id} 失败: {e}")
            return False

    async def rename_tab(self, tab_id: str, new_name: str) -> bool:
        """重命名 Tab"""
        try:
            app = await self.get_app()
            if app is None:
                return False
            for window in app.windows:
                for tab in window.tabs:
                    if tab.tab_id == tab_id:
                        success = await set_tab_name(tab, new_name)
                        if success:
                            print(f"[ITerm2Client] Tab {tab_id} 重命名为: {new_name}")
                        return success
            print(f"[ITerm2Client] 未找到 Tab: {tab_id}")
            return False
        except Exception as e:
            print(f"[ITerm2Client] 重命名 Tab {tab_id} 失败: {e}")
            return False

    async def rename_session(self, session_id: str, new_name: str) -> bool:
        """重命名 Session"""
        try:
            app = await self.get_app()
            if app is None:
                return False
            session = app.get_session_by_id(session_id)
            if session:
                success = await set_session_name(session, new_name)
                if success:
                    print(f"[ITerm2Client] Session {session_id} 重命名为: {new_name}")
                return success
            print(f"[ITerm2Client] 未找到 Session: {session_id}")
            return False
        except Exception as e:
            print(f"[ITerm2Client] 重命名 Session {session_id} 失败: {e}")
            return False

    async def rename_item(self, item_type: str, item_id: str, new_name: str) -> bool:
        """统一的重命名接口"""
        if item_type == "window":
            return await self.rename_window(item_id, new_name)
        elif item_type == "tab":
            return await self.rename_tab(item_id, new_name)
        elif item_type == "session":
            return await self.rename_session(item_id, new_name)
        else:
            print(f"[ITerm2Client] 未知类型: {item_type}")
            return False

    async def create_tab(self, window_id: str, layout: str = "single") -> bool:
        """在指定 Window 中创建新 Tab，支持不同布局

        Args:
            window_id: 窗口 ID
            layout: 布局类型 - single, 2rows, 2cols, 2x2
        """
        try:
            app = await self.get_app()
            if app is None:
                return False
            for window in app.windows:
                if window.window_id == window_id:
                    tab = await window.async_create_tab()
                    if layout != "single":
                        await self._apply_layout(tab, layout)
                    print(f"[ITerm2Client] 在 Window {window_id} 中创建了 {layout} 布局的 Tab")
                    return True
            print(f"[ITerm2Client] 未找到 Window: {window_id}")
            return False
        except Exception as e:
            print(f"[ITerm2Client] 创建 Tab 失败: {e}")
            return False

    async def _apply_layout(self, tab, layout: str):
        """应用指定的分屏布局"""
        session = tab.current_session
        if layout == "2rows":
            # 水平分割：上下两行
            await session.async_split_pane(vertical=False)
        elif layout == "2cols":
            # 垂直分割：左右两列
            await session.async_split_pane(vertical=True)
        elif layout == "2x2":
            # 2x2 网格
            right = await session.async_split_pane(vertical=True)
            await session.async_split_pane(vertical=False)
            await right.async_split_pane(vertical=False)
        elif layout == "2cols-right2rows":
            # 左1右2：左边一列，右边两行
            right = await session.async_split_pane(vertical=True)
            await right.async_split_pane(vertical=False)
        elif layout == "2rows-bottom2cols":
            # 上1下2：上面一行，下面两列
            bottom = await session.async_split_pane(vertical=False)
            await bottom.async_split_pane(vertical=True)

    async def get_session_content(self, session: iterm2.Session) -> str:
        """获取 session 的屏幕内容"""
        try:
            contents = await session.async_get_screen_contents()
            lines = [contents.line(i).string for i in range(contents.number_of_lines)]
            return self._normalize_content("\n".join(lines))
        except Exception as e:
            return f"[Error: {e}]"

    async def get_session_job_name(self, session: iterm2.Session) -> str:
        """获取 session 当前前台进程名 (用于 heuristic whitelist)

        Returns:
            前台进程名 (e.g. "gemini", "python", "node")，失败时返回空字符串
        """
        try:
            job_name = await session.async_get_variable("jobName")
            return job_name or ""
        except Exception as e:
            logger.debug(f"Failed to get job name: {e}")
            return ""

    async def get_session_job_metadata(self, session: iterm2.Session) -> JobMetadata:
        """Fetch foreground job metadata via asyncio.gather

        Requires iTerm2 Shell Integration for job fields; tty always available.
        Missing vars treated as empty; jobPid cast to int when possible.
        """
        try:
            results = await asyncio.gather(
                session.async_get_variable("jobName"),
                session.async_get_variable("jobPid"),
                session.async_get_variable("commandLine"),
                session.async_get_variable("tty"),
                session.async_get_variable("path"),
                return_exceptions=True,
            )
            job_name, job_pid, cmd_line, tty, path = results

            # Sanitize results
            job_name_str = job_name if isinstance(job_name, str) else ""
            tty_str = tty if isinstance(tty, str) else ""
            cmd_line_str = cmd_line if isinstance(cmd_line, str) else ""
            path_str = path if isinstance(path, str) else ""

            # Cast jobPid to int
            job_pid_int: int | None = None
            if isinstance(job_pid, (int, float)) or isinstance(job_pid, str) and job_pid.isdigit():
                job_pid_int = int(job_pid)

            return JobMetadata(
                job_name=job_name_str,
                job_pid=job_pid_int,
                command_line=cmd_line_str,
                tty=tty_str,
                path=path_str,
            )
        except Exception as e:
            logger.debug(f"Failed to get job metadata: {e}")
            return JobMetadata()

    @staticmethod
    def _normalize_content(content: str) -> str:
        """标准化内容"""
        content = content.replace("\xa0", " ")
        lines = [line.rstrip() for line in content.split("\n")]
        return "\n".join(lines)
