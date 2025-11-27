"""iTerm2 API 客户端封装"""

import iterm2

from termsupervisor import config


class ITerm2Client:
    """iTerm2 API 操作封装"""

    def __init__(self, connection: iterm2.Connection):
        self.connection = connection

    async def get_app(self) -> iterm2.App:
        """获取 iTerm2 App 实例"""
        return await iterm2.async_get_app(self.connection)

    async def activate_session(self, session_id: str) -> bool:
        """激活指定的 session"""
        try:
            app = await self.get_app()
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
            for window in app.windows:
                if window.window_id == window_id:
                    await window.async_set_variable(config.USER_NAME_VAR, new_name)
                    print(f"[ITerm2Client] Window {window_id} 重命名为: {new_name}")
                    return True
            print(f"[ITerm2Client] 未找到 Window: {window_id}")
            return False
        except Exception as e:
            print(f"[ITerm2Client] 重命名 Window {window_id} 失败: {e}")
            return False

    async def rename_tab(self, tab_id: str, new_name: str) -> bool:
        """重命名 Tab（设置变量和标题）"""
        try:
            app = await self.get_app()
            for window in app.windows:
                for tab in window.tabs:
                    if tab.tab_id == tab_id:
                        await tab.async_set_variable(config.USER_NAME_VAR, new_name)
                        await tab.async_set_title(new_name)
                        print(f"[ITerm2Client] Tab {tab_id} 重命名为: {new_name}")
                        return True
            print(f"[ITerm2Client] 未找到 Tab: {tab_id}")
            return False
        except Exception as e:
            print(f"[ITerm2Client] 重命名 Tab {tab_id} 失败: {e}")
            return False

    async def rename_session(self, session_id: str, new_name: str) -> bool:
        """重命名 Session（同时设置变量和 title）"""
        try:
            app = await self.get_app()
            session = app.get_session_by_id(session_id)
            if session:
                await session.async_set_variable(config.USER_NAME_VAR, new_name)
                await session.async_set_name(new_name)
                print(f"[ITerm2Client] Session {session_id} 重命名为: {new_name}")
                return True
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

    @staticmethod
    def _normalize_content(content: str) -> str:
        """标准化内容"""
        content = content.replace("\xa0", " ")
        lines = [line.rstrip() for line in content.split("\n")]
        return "\n".join(lines)
