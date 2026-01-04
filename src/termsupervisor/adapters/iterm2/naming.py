"""iTerm2 命名工具函数

获取和设置 iTerm2 对象（Window/Tab/Session）的名称。
优先级：USER 自定义变量 > iTerm2 内置变量 > 默认值
设置时同时更新 USER 变量和 iTerm2 内置属性。
"""

import iterm2

from termsupervisor import config

# ==================== 获取名称 ====================


async def get_session_name(session: iterm2.Session, default: str = "") -> str:
    """获取 Session 名称

    优先级: user.name > name > default
    """
    # 1. 优先使用 USER 自定义变量
    user_name = await session.async_get_variable(config.USER_NAME_VAR)
    if user_name:
        return user_name

    # 2. 使用 iTerm2 内置 name 变量（标签栏显示的名称）
    name = await session.async_get_variable("name")
    if name:
        return name

    return default


async def get_tab_name(tab: iterm2.Tab, default: str = "") -> str:
    """获取 Tab 名称

    优先级: user.name > title > default

    注意：iTerm2 的 Tab title 变量默认继承自当前活跃 Session 的名称。
    如果用户没有手动命名 Tab，title 会动态显示当前 session 的名称
    （如 -zsh、claude 等）。这是 iTerm2 的设计行为，不是 bug。
    """
    # 1. 优先使用 USER 自定义变量
    user_name = await tab.async_get_variable(config.USER_NAME_VAR)
    if user_name:
        return user_name

    # 2. 使用 iTerm2 内置 title 变量（未命名时会显示当前 session 名称）
    title = await tab.async_get_variable("title")
    if title:
        return title

    return default


async def get_window_name(window: iterm2.Window, default: str = "") -> str:
    """获取 Window 名称

    优先级: user.name > titleOverride > Window {number} > default
    """
    # 1. 优先使用 USER 自定义变量
    user_name = await window.async_get_variable(config.USER_NAME_VAR)
    if user_name:
        return user_name

    # 2. 使用 iTerm2 内置 titleOverride 变量
    title = await window.async_get_variable("titleOverride")
    if title:
        return title

    # 3. 使用 Window 编号
    number = await window.async_get_variable("number")
    if number is not None:
        return f"Window {number}"

    return default


async def get_name(obj: iterm2.Session | iterm2.Tab | iterm2.Window, default: str = "") -> str:
    """获取对象名称（通用接口）

    根据对象类型调用对应的获取函数。
    """
    if isinstance(obj, iterm2.Session):
        return await get_session_name(obj, default)
    elif isinstance(obj, iterm2.Tab):
        return await get_tab_name(obj, default)
    elif isinstance(obj, iterm2.Window):
        return await get_window_name(obj, default)
    return default


# ==================== 设置名称 ====================


async def set_session_name(session: iterm2.Session, name: str) -> bool:
    """设置 Session 名称

    同时设置 USER 变量和 iTerm2 内置 name。
    """
    try:
        await session.async_set_variable(config.USER_NAME_VAR, name)
        await session.async_set_name(name)
        return True
    except Exception as e:
        print(f"[naming] 设置 Session 名称失败: {e}")
        return False


async def set_tab_name(tab: iterm2.Tab, name: str) -> bool:
    """设置 Tab 名称

    同时设置 USER 变量和 iTerm2 内置 title。
    """
    try:
        await tab.async_set_variable(config.USER_NAME_VAR, name)
        await tab.async_set_title(name)
        return True
    except Exception as e:
        print(f"[naming] 设置 Tab 名称失败: {e}")
        return False


async def set_window_name(window: iterm2.Window, name: str) -> bool:
    """设置 Window 名称

    设置 USER 变量（Window 没有内置的 setTitle 方法）。
    """
    try:
        await window.async_set_variable(config.USER_NAME_VAR, name)
        return True
    except Exception as e:
        print(f"[naming] 设置 Window 名称失败: {e}")
        return False


async def set_name(obj: iterm2.Session | iterm2.Tab | iterm2.Window, name: str) -> bool:
    """设置对象名称（通用接口）

    根据对象类型调用对应的设置函数。
    """
    if isinstance(obj, iterm2.Session):
        return await set_session_name(obj, name)
    elif isinstance(obj, iterm2.Tab):
        return await set_tab_name(obj, name)
    elif isinstance(obj, iterm2.Window):
        return await set_window_name(obj, name)
    return False
