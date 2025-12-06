"""FastAPI 应用初始化"""

import asyncio
import logging

import iterm2
import uvicorn

from termsupervisor import config
from termsupervisor.iterm import ITerm2Client
from termsupervisor.iterm.utils import normalize_session_id
from termsupervisor.runtime import RuntimeComponents, bootstrap
from termsupervisor.supervisor import TermSupervisor
from termsupervisor.web.server import WebServer

logger = logging.getLogger(__name__)


def create_app(supervisor: TermSupervisor, iterm_client: ITerm2Client) -> WebServer:
    """创建 Web 应用"""
    return WebServer(supervisor, iterm_client)


async def setup_hook_system(server: WebServer, connection: iterm2.Connection) -> RuntimeComponents:
    """设置 Hook 系统

    使用 runtime.bootstrap 创建组件。

    Returns:
        RuntimeComponents 包含所有组件
    """
    # 创建 focus 检查函数（需要先有 iterm_source 来获取 focus）
    # 由于 bootstrap 需要 focus_checker，而 focus_checker 需要 iterm_source
    # 所以先创建组件，再设置 focus_checker
    components = bootstrap(connection)

    # 设置 focus 检查函数（用于通知抑制判断）
    def check_is_focused(pane_id: str) -> bool:
        focus_session = components.iterm_source.current_focus_session
        if not focus_session:
            return False
        normalized_pane = normalize_session_id(pane_id)
        normalized_focus = normalize_session_id(focus_session)
        return normalized_pane == normalized_focus

    components.hook_manager.set_focus_checker(check_is_focused)

    # 设置状态变更回调 -> 广播到前端
    async def on_status_change(pane_id: str, status, reason: str, source: str, suppressed: bool):
        """状态变更时广播到前端"""
        window_name, tab_name, pane_name = server.supervisor.get_pane_location(pane_id)

        needs_notification = status.needs_notification and not suppressed

        await server.broadcast(
            {
                "type": "hook_status",
                "pane_id": pane_id,
                "status": status.value,
                "status_color": status.color,
                "reason": reason,
                "source": source,
                "needs_notification": needs_notification,
                "needs_attention": status.needs_attention,
                "is_running": status.is_running,
                "display": status.display,
                "window_name": window_name,
                "tab_name": tab_name,
                "pane_name": pane_name,
            }
        )

    components.hook_manager.set_change_callback(on_status_change)

    # 设置到 WebServer
    server.setup_hook_receiver(components.receiver)

    # 启动 sources
    await components.start_sources()

    logger.info("[HookSystem] Hook 系统已初始化 (via bootstrap)")
    return components


async def start_server(connection: iterm2.Connection):
    """启动服务器"""
    iterm_client = ITerm2Client(connection)

    supervisor = TermSupervisor(
        interval=config.INTERVAL,
        exclude_names=config.EXCLUDE_NAMES,
        min_changed_lines=config.MIN_CHANGED_LINES,
        debug=config.DEBUG,
        iterm_client=iterm_client,
    )

    server = create_app(supervisor, iterm_client)

    # 初始化 Hook 系统（状态管理的唯一来源）
    components = await setup_hook_system(server, connection)
    print("[HookSystem] Hook 系统已启动 (Shell + Claude Code + iTerm Focus)")

    # 注入 hook_manager 到 supervisor（用于状态获取和 content.changed 事件）
    supervisor.set_hook_manager(components.hook_manager)
    supervisor.set_shell_source(components.shell_source)

    # 启动 Timer（LONG_RUNNING 检查 + Pane 延迟任务）
    timer_task = asyncio.create_task(components.timer.run())
    print("[Timer] Timer 已启动")

    supervisor_task = asyncio.create_task(supervisor.run())

    # 定期同步 session 列表到 Shell Hook Source
    async def sync_sessions():
        while True:
            try:
                session_ids = set(supervisor.snapshots.keys())
                await components.shell_source.sync_sessions(session_ids)
            except Exception as e:
                logger.error(f"[HookSystem] 同步 sessions 失败: {e}")
            await asyncio.sleep(config.POLL_INTERVAL)

    sync_task = asyncio.create_task(sync_sessions())

    uvicorn_config = uvicorn.Config(server.app, host="0.0.0.0", port=8765, log_level="info")
    uvicorn_server = uvicorn.Server(uvicorn_config)

    print("TermSupervisor Web Server starting at http://localhost:8765")

    try:
        await uvicorn_server.serve()
    finally:
        supervisor.stop()
        components.timer.stop()
        supervisor_task.cancel()
        timer_task.cancel()
        sync_task.cancel()
        await components.stop_sources()


def main():
    """入口函数"""
    try:
        iterm2.run_until_complete(start_server)
    except KeyboardInterrupt:
        print("\nServer stopped")
