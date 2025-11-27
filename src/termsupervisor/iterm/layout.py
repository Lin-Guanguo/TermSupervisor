"""iTerm2 布局遍历"""

from typing import Union

import iterm2

from termsupervisor import config
from termsupervisor.models import PaneInfo, TabInfo, WindowInfo, LayoutData


async def get_name(obj, default: str = "") -> str:
    """获取对象名称（优先使用 user.name，否则用内置变量）

    iTerm2 变量参考:
    - Session: name (标签栏显示名), presentationName, jobName
    - Tab: title (标签栏完整标题)
    - Window: titleOverride, number
    """
    # 优先使用自定义变量
    user_name = await obj.async_get_variable(config.USER_NAME_VAR)
    if user_name:
        return user_name

    # 使用 iTerm2 内置变量
    if isinstance(obj, iterm2.Session):
        # Session 使用 name 变量（标签栏显示的名称）
        name = await obj.async_get_variable("name")
        return name or default
    elif isinstance(obj, iterm2.Tab):
        # Tab 使用 title 变量
        title = await obj.async_get_variable("title")
        return title or default
    elif isinstance(obj, iterm2.Window):
        # Window 使用 titleOverride，如果没有则用 number
        title = await obj.async_get_variable("titleOverride")
        if title:
            return title
        number = await obj.async_get_variable("number")
        if number is not None:
            return f"Window {number}"
        return default

    return default


async def traverse_node(
    node: Union[iterm2.Session, iterm2.Splitter],
    abs_x: float,
    abs_y: float,
    exclude_names: list[str] | None = None
) -> tuple[list[PaneInfo], float, float]:
    """
    递归遍历节点，计算所有子 Session 的绝对坐标。
    返回: (panes, width, height)
    """
    exclude_names = exclude_names or []

    if isinstance(node, iterm2.Session):
        width = node.frame.size.width
        height = node.frame.size.height

        # 获取显示名称
        display_name = await get_name(node, "Pane")

        # 检查是否排除
        if any(exclude in display_name for exclude in exclude_names):
            return [], width, height

        pane = PaneInfo(
            session_id=node.session_id,
            name=display_name,
            index=0,  # 稍后统一分配
            x=abs_x,
            y=abs_y,
            width=width,
            height=height,
        )
        return [pane], width, height

    elif isinstance(node, iterm2.Splitter):
        panes = []
        is_vertical = node.vertical

        current_x_offset = 0
        current_y_offset = 0
        my_width = 0
        my_height = 0

        for child in node.children:
            child_abs_x = abs_x + current_x_offset
            child_abs_y = abs_y + current_y_offset

            # Session 使用 frame.origin 校准位置
            if isinstance(child, iterm2.Session):
                child_abs_x = abs_x + child.frame.origin.x
                child_abs_y = abs_y + child.frame.origin.y

            child_panes, child_w, child_h = await traverse_node(
                child, child_abs_x, child_abs_y, exclude_names
            )
            panes.extend(child_panes)

            if is_vertical:
                current_x_offset += child_w
                my_width += child_w
                my_height = max(my_height, child_h)
            else:
                current_y_offset += child_h
                my_height += child_h
                my_width = max(my_width, child_w)

        return panes, my_width, my_height

    return [], 0, 0


async def get_layout(app: iterm2.App, exclude_names: list[str] | None = None) -> LayoutData:
    """获取 iTerm2 当前布局"""
    layout = LayoutData()
    global_pane_index = 0

    # 获取当前 active session
    try:
        current_window = app.current_window
        if current_window and current_window.current_tab:
            current_session = current_window.current_tab.current_session
            if current_session:
                layout.active_session_id = current_session.session_id
    except Exception:
        pass

    for window in app.windows:
        frame = await window.async_get_frame()
        window_name = await get_name(window, "Window")

        window_info = WindowInfo(
            window_id=window.window_id,
            name=window_name,
            x=frame.origin.x,
            y=frame.origin.y,
            width=frame.size.width,
            height=frame.size.height,
        )

        for tab in window.tabs:
            tab_name = await get_name(tab, "Tab")
            tab_info = TabInfo(tab_id=tab.tab_id, name=tab_name)

            if tab.root:
                panes, _, _ = await traverse_node(tab.root, 0, 0, exclude_names)
                for pane in panes:
                    pane.index = global_pane_index
                    global_pane_index += 1
                    tab_info.panes.append(pane)

            window_info.tabs.append(tab_info)
        layout.windows.append(window_info)

    return layout
