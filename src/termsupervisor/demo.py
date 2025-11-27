"""Demo: iTerm2 Pane 操作演示"""

import iterm2


async def get_all_panes(app: iterm2.App) -> list[tuple[int, iterm2.Session, str, str]]:
    """获取所有 pane 信息"""
    panes: list[tuple[int, iterm2.Session, str, str]] = []
    index = 0

    for window in app.windows:
        window_name = await window.async_get_variable("name") or "Unnamed Window"
        for tab in window.tabs:
            tab_name = await tab.async_get_variable("name") or "Unnamed Tab"
            for session in tab.sessions:
                panes.append((index, session, window_name, tab_name))
                index += 1

    return panes


async def display_panes(panes: list[tuple[int, iterm2.Session, str, str]]):
    """显示所有 pane 列表"""
    print("\n可用的 Panes:")
    print("-" * 60)
    for idx, session, win_name, tab_name in panes:
        name = await session.async_get_variable("name") or "Unnamed"
        tty = await session.async_get_variable("tty") or "N/A"
        print(f"  [{idx}] {win_name} > {tab_name} > {name}")
        print(f"      TTY: {tty}, Session ID: {session.session_id}")
    print("-" * 60)


async def select_pane(panes: list[tuple[int, iterm2.Session, str, str]]) -> iterm2.Session | None:
    """让用户选择一个 pane"""
    await display_panes(panes)
    try:
        choice = int(input(f"\n请输入 pane 编号 (0-{len(panes)-1}): "))
        if 0 <= choice < len(panes):
            return panes[choice][1]
        else:
            print("无效的编号")
            return None
    except ValueError:
        print("请输入有效的数字")
        return None


async def activate_pane(connection: iterm2.Connection):
    """功能1: 激活指定 pane"""
    app = await iterm2.async_get_app(connection)
    panes = await get_all_panes(app)

    if not panes:
        print("没有找到任何 pane")
        return

    session = await select_pane(panes)
    if session:
        await session.async_activate()
        print("已激活该 pane")


async def get_pane_content(connection: iterm2.Connection):
    """功能2: 获取 pane 内容"""
    app = await iterm2.async_get_app(connection)
    panes = await get_all_panes(app)

    if not panes:
        print("没有找到任何 pane")
        return

    session = await select_pane(panes)
    if session:
        # 获取屏幕内容
        contents = await session.async_get_screen_contents()

        print("\n" + "=" * 60)
        print("Pane 内容:")
        print("=" * 60)

        # 遍历每一行
        for line_num in range(contents.number_of_lines):
            line = contents.line(line_num)
            print(line.string)

        print("=" * 60)
        print(f"总行数: {contents.number_of_lines}")


async def main_menu(connection: iterm2.Connection):
    """主菜单"""
    while True:
        print("\n" + "=" * 40)
        print("  TermSupervisor Demo")
        print("=" * 40)
        print("  [1] 列出并激活 Pane")
        print("  [2] 获取 Pane 内容")
        print("  [0] 退出")
        print("=" * 40)

        choice = input("请选择功能: ").strip()

        if choice == "1":
            await activate_pane(connection)
        elif choice == "2":
            await get_pane_content(connection)
        elif choice == "0":
            print("再见!")
            break
        else:
            print("无效选择，请重试")


def main():
    """运行 demo"""
    iterm2.run_until_complete(main_menu)


if __name__ == "__main__":
    main()
