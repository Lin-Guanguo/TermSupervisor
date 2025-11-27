"TermSupervisor: 监控 iTerm2 所有 pane 内容变化"

import asyncio
import difflib
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Callable, Awaitable

import iterm2

from termsupervisor import config


@dataclass
class PaneInfo:
    """Pane 信息"""
    session_id: str
    name: str
    index: int
    x: float
    y: float
    width: float
    height: float


@dataclass
class TabInfo:
    """Tab 信息"""
    tab_id: str
    name: str
    panes: list[PaneInfo] = field(default_factory=list)


@dataclass
class WindowInfo:
    """Window 信息"""
    window_id: str
    name: str
    x: float
    y: float
    width: float
    height: float
    tabs: list[TabInfo] = field(default_factory=list)


@dataclass
class LayoutData:
    """完整布局数据"""
    windows: list[WindowInfo] = field(default_factory=list)
    updated_sessions: list[str] = field(default_factory=list)


@dataclass
class PaneSnapshot:
    """Pane 内容快照"""
    session_id: str
    index: int
    content: str
    updated_at: datetime = field(default_factory=datetime.now)


# 更新回调类型
UpdateCallback = Callable[[LayoutData], Awaitable[None]]


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

    def get_diff_lines(self, old_content: str, new_content: str) -> list[str]:
        """获取变更的行（unified diff 格式）"""
        old_lines = old_content.split("\n")
        new_lines = new_content.split("\n")

        diff = list(difflib.unified_diff(old_lines, new_lines, lineterm="", n=0))
        changed_lines = []
        for line in diff:
            if line.startswith("@@"):
                continue
            if line.startswith("---") or line.startswith("+++"):
                continue
            if line.startswith("+") or line.startswith("-"):
                changed_lines.append(line)

        return changed_lines

    def has_significant_change(self, old_content: str, new_content: str) -> tuple[bool, list[str]]:
        """判断是否有显著变化，返回 (是否变化, 变更行列表)"""
        if old_content == new_content:
            return False, []

        changed_lines = self.get_diff_lines(old_content, new_content)
        added = sum(1 for line in changed_lines if line.startswith("+"))
        removed = sum(1 for line in changed_lines if line.startswith("-"))

        self._debug(f"变更: +{added} -{removed} (总计 {len(changed_lines)} 行)")

        return len(changed_lines) >= self.min_changed_lines, changed_lines

    def normalize_content(self, content: str) -> str:
        """标准化内容，过滤掉选中标记等干扰"""
        content = content.replace("\xa0", " ")
        lines = [line.rstrip() for line in content.split("\n")]
        return "\n".join(lines)

    async def get_session_content(self, session: iterm2.Session) -> str:
        """获取 session 的屏幕内容"""
        try:
            contents = await session.async_get_screen_contents()
            lines = []
            for line_num in range(contents.number_of_lines):
                line = contents.line(line_num)
                lines.append(line.string)
            raw_content = "\n".join(lines)
            return self.normalize_content(raw_content)
        except Exception as e:
            return f"[Error: {e}]"

    async def get_session_info(self, session: iterm2.Session) -> str:
        """获取 session 的显示名称"""
        name = await session.async_get_variable("name") or "Unnamed"
        return f"{name} ({session.session_id})"

    async def should_exclude(self, session: iterm2.Session) -> bool:
        """检查是否应该排除该 session"""
        if not self.exclude_names:
            return False
        name = await session.async_get_variable("name") or ""
        return any(exclude in name for exclude in self.exclude_names)

    async def _traverse_node(
        self, node, abs_x: float, abs_y: float
    ) -> tuple[list[PaneInfo], float, float]:
        """
        递归遍历节点，计算所有子 Session 的绝对坐标。
        返回: (panes, width, height)
        width/height 是该节点占据的总尺寸。
        """
        if isinstance(node, iterm2.Session):
            # Session 节点的 frame.origin 是相对于其父 Splitter 的。
            # 实际上，在我们的递归逻辑中，父 Splitter 已经将累加的偏移量传递给了 abs_x/abs_y。
            # 为了最精确，我们使用 parent 传递的基准 abs_x + node.frame.origin.x
            # (尽管通常 node.frame.origin.x 应该接近于我们计算出的 offset，但直接用 frame 更准)
            
            # 注意：如果 node 是 Root 的直接子 Session，且 Root 是 Splitter，那么 abs_x/y 已经是 (0,0) 或 (offset, 0)。
            # node.frame.origin.x 在这种情况下是相对于 (0,0) 的偏移（如果是第一个子节点则为0）。
            # 所以公式：real_x = abs_x + node.frame.origin.x
            # 是正确的，前提是 abs_x 是"这个节点所属容器的绝对原点"。
            
            # 然而，在 traverse_splitter 中，我们将 child 的 abs_x 计算为 my_abs_x + current_offset。
            # 如果我们这么做，那么我们实质上是在手动计算 origin。
            # 此时 node.frame.origin.x 应该是 0 (或者接近0，除了 margin)。
            # 如果 node.frame.origin.x 很大（例如 605），那说明它是相对于父 Splitter 的偏移。
            # 这样的话，我们不能把 current_offset 和 frame.origin 重复相加。
            
            # 修正逻辑：
            # Splitter 逻辑中，我们不知道 Child 是否有 frame。
            # 如果 Child 是 Session，它有 frame。frame.origin 是相对于 Splitter 的。
            # 所以 Child 的绝对位置 = SplitterAbsPos + Child.frame.origin。
            # 我们完全不需要 current_offset 来计算 Session 的位置，只需要用它来计算 Splitter 的位置。
            
            # 但是，如果 Child 是 Splitter，它没有 frame。
            # 我们必须用 current_offset 来决定 Child Splitter 的位置。
            
            width = node.frame.size.width
            height = node.frame.size.height
            
            # 在这里，我们假设传入的 abs_x 是 "如果这个节点紧接着上一个兄弟节点开始" 的位置。
            # 而 node.frame.origin 是 "相对于父容器" 的位置。
            # 对于 Session，我们优先使用 frame.origin + parent_splitter_abs_pos (我们需要从参数传入 parent_abs)。
            # 但为了简化递归接口，我们假设调用者负责计算正确的 abs_x/abs_y。
            
            # 回到之前的分析：
            # Child 1.1 (Session): x=0, y=605 (relative to Parent Splitter)。
            # 我们传入的 abs_x/abs_y 是通过 current_offset 累加得到的。
            # 如果我们累加正确，abs_x/y 应该非常接近 (ParentAbsX + frame.origin.x, ParentAbsY + frame.origin.y)。
            # 为了最大程度利用 API 的准确性，我们应该在这里检查一下差异？
            # 算了，直接使用传入的 abs_x/abs_y，这对应于 "严格的平铺模型"。
            
            if await self.should_exclude(node):
                return [], width, height

            name = await node.async_get_variable("name") or "Pane"
            # 临时使用 0 作为 index，稍后在 get_layout 中统一修正
            pane = PaneInfo(
                session_id=node.session_id,
                name=name,
                index=0, 
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
                # 计算子节点的绝对起始位置
                # 注意：这里 abs_x/abs_y 是当前 Splitter 的绝对位置
                child_abs_x = abs_x + current_x_offset
                child_abs_y = abs_y + current_y_offset
                
                # 如果 child 是 Session，我们可以利用它的 frame.origin 来"校准"偏移量
                # frame.origin 是相对于 node (当前 Splitter) 的。
                if isinstance(child, iterm2.Session):
                    child_abs_x = abs_x + child.frame.origin.x
                    child_abs_y = abs_y + child.frame.origin.y

                child_panes, child_w, child_h = await self._traverse_node(
                    child, child_abs_x, child_abs_y
                )
                panes.extend(child_panes)
                
                # 更新累加器和自身尺寸
                if is_vertical:
                    # 左右排列
                    current_x_offset += child_w
                    my_width += child_w
                    my_height = max(my_height, child_h)
                else:
                    # 上下排列
                    current_y_offset += child_h
                    my_height += child_h
                    my_width = max(my_width, child_w)
            
            return panes, my_width, my_height
        
        return [], 0, 0

    async def get_layout(self, app: iterm2.App) -> LayoutData:
        """获取 iTerm2 当前布局"""
        layout = LayoutData()
        global_pane_index = 0

        for window in app.windows:
            frame = await window.async_get_frame()
            window_name = await window.async_get_variable("name") or "Window"

            window_info = WindowInfo(
                window_id=window.window_id,
                name=window_name,
                x=frame.origin.x,
                y=frame.origin.y,
                width=frame.size.width,
                height=frame.size.height,
            )

            for tab in window.tabs:
                tab_name = await tab.async_get_variable("name") or "Tab"
                tab_info = TabInfo(tab_id=tab.tab_id, name=tab_name)

                # 使用递归遍历替代简单的 sessions 列表
                # tab.root 是布局树的根节点
                if tab.root:
                    panes, _, _ = await self._traverse_node(tab.root, 0, 0)
                    # 重新分配 index
                    for pane in panes:
                        pane.index = global_pane_index
                        global_pane_index += 1
                        tab_info.panes.append(pane)
                else:
                    # Fallback if no root (shouldn't happen)
                    for session in tab.sessions:
                         # ... (Old logic, omitted for brevity but could kept as backup)
                         pass

                window_info.tabs.append(tab_info)
            layout.windows.append(window_info)

        return layout

    async def check_updates(self, connection: iterm2.Connection) -> list[str]:
        """检查所有 pane 的更新，返回更新的 session_id 列表"""
        app = await iterm2.async_get_app(connection)
        self.layout = await self.get_layout(app)
        now = datetime.now()
        updated_sessions = []

        # 遍历所有 pane 检查更新
        for window in self.layout.windows:
            for tab in window.tabs:
                for pane in tab.panes:
                    session = app.get_session_by_id(pane.session_id)
                    if not session:
                        continue

                    content = await self.get_session_content(session)

                    if pane.session_id in self.snapshots:
                        old_snapshot = self.snapshots[pane.session_id]
                        has_change, changed_lines = self.has_significant_change(
                            old_snapshot.content, content
                        )
                        if has_change:
                            updated_sessions.append(pane.session_id)
                            added = sum(1 for line in changed_lines if line.startswith("+"))
                            removed = sum(1 for line in changed_lines if line.startswith("-"))
                            print(f"[{now.strftime('%H:%M:%S')}] [{pane.index}] {pane.name} 有更新 (+{added} -{removed}):")
                            display_lines = changed_lines[-5:]
                            if len(changed_lines) > 5:
                                print(f"  ... 省略 {len(changed_lines) - 5} 行")
                            for line in display_lines:
                                print(f"  {line}")

                            self.snapshots[pane.session_id] = PaneSnapshot(
                                session_id=pane.session_id,
                                index=pane.index,
                                content=content,
                                updated_at=now,
                            )
                    else:
                        # 新 session
                        print(f"[{now.strftime('%H:%M:%S')}] 发现新 Panel [{pane.index}]: {pane.name}")
                        self.snapshots[pane.session_id] = PaneSnapshot(
                            session_id=pane.session_id,
                            index=pane.index,
                            content=content,
                            updated_at=now,
                        )

        # 检查已关闭的 session
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

        self.layout.updated_sessions = updated_sessions
        return updated_sessions

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
        """获取布局数据字典（用于 JSON 序列化）"""
        return asdict(self.layout)


# 全局 supervisor 实例
_supervisor: TermSupervisor | None = None
_connection: iterm2.Connection | None = None


def get_supervisor() -> TermSupervisor | None:
    """获取全局 supervisor 实例"""
    return _supervisor


async def start_supervisor(connection: iterm2.Connection):
    """启动监控服务"""
    global _supervisor, _connection
    _connection = connection
    _supervisor = TermSupervisor(
        interval=config.INTERVAL,
        exclude_names=config.EXCLUDE_NAMES,
        min_changed_lines=config.MIN_CHANGED_LINES,
        debug=config.DEBUG,
    )
    await _supervisor.run(connection)


def main():
    """入口函数"""
    try:
        iterm2.run_until_complete(start_supervisor)
    except KeyboardInterrupt:
        print("\n已停止")


if __name__ == "__main__":
    main()