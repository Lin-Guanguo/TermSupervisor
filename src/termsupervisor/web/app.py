"""FastAPI 应用初始化"""

import asyncio
import logging

import iterm2
import uvicorn

from termsupervisor import config
from termsupervisor.iterm import ITerm2Client
from termsupervisor.iterm.utils import normalize_session_id
from termsupervisor.supervisor import TermSupervisor
from termsupervisor.web.server import WebServer

logger = logging.getLogger(__name__)


def create_app(supervisor: TermSupervisor, iterm_client: ITerm2Client) -> WebServer:
    """创建 Web 应用"""
    return WebServer(supervisor, iterm_client)


async def setup_hook_system(
    server: WebServer,
    connection: iterm2.Connection
) -> tuple:
    """设置 Hook 系统

    Returns:
        (hook_manager, shell_source, claude_code_source, iterm_source, timer)
    """
    from termsupervisor.analysis import get_hook_manager, get_timer
    from termsupervisor.hooks import HookReceiver
    from termsupervisor.hooks.sources.shell import ShellHookSource
    from termsupervisor.hooks.sources.claude_code import ClaudeCodeHookSource
    from termsupervisor.hooks.sources.iterm import ItermHookSource

    # 获取 HookManager 和 Timer 单例
    hook_manager = get_hook_manager()
    timer = get_timer()

    # 设置状态变更回调 -> 广播到前端
    async def on_status_change(pane_id: str, status, reason: str, source: str, suppressed: bool):
        """状态变更时广播到前端"""
        # 获取 pane 所在的 window/tab 名称
        window_name, tab_name, pane_name = server.supervisor.get_pane_location(pane_id)
        print(f"[HookStatus] pane_id={pane_id}, window={window_name}, tab={tab_name}, pane={pane_name}")

        # 通知抑制由 StateStore 统一处理，这里直接使用结果
        needs_notification = status.needs_notification and not suppressed

        await server.broadcast({
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
        })

    hook_manager.set_change_callback(on_status_change)

    # 创建适配器
    shell_source = ShellHookSource(hook_manager, connection)
    claude_code_source = ClaudeCodeHookSource(hook_manager)
    iterm_source = ItermHookSource(hook_manager, connection)

    # 设置 focus 检查函数（用于通知抑制判断）
    def check_is_focused(pane_id: str) -> bool:
        focus_session = iterm_source.current_focus_session
        if not focus_session:
            return False
        normalized_pane = normalize_session_id(pane_id)
        normalized_focus = normalize_session_id(focus_session)
        return normalized_pane == normalized_focus

    hook_manager.set_focus_checker(check_is_focused)

    # 创建接收器并注册适配器
    receiver = HookReceiver(hook_manager)
    receiver.register_adapter(claude_code_source)

    # 设置到 WebServer
    server.setup_hook_receiver(receiver)

    # 启动适配器
    await shell_source.start()
    await claude_code_source.start()
    await iterm_source.start()

    logger.info("[HookSystem] Hook 系统已初始化")
    return hook_manager, shell_source, claude_code_source, iterm_source, timer


async def start_server(connection: iterm2.Connection):
    """启动服务器"""
    iterm_client = ITerm2Client(connection)

    supervisor = TermSupervisor(
        interval=config.INTERVAL,
        exclude_names=config.EXCLUDE_NAMES,
        min_changed_lines=config.MIN_CHANGED_LINES,
        debug=config.DEBUG,
    )

    server = create_app(supervisor, iterm_client)

    # 初始化 Hook 系统（状态管理的唯一来源）
    hook_manager, shell_source, claude_code_source, iterm_source, timer = await setup_hook_system(
        server, connection
    )
    print("[HookSystem] Hook 系统已启动 (Shell + Claude Code + iTerm Focus)")

    # 启动 Timer（LONG_RUNNING 检查 + Pane 延迟任务）
    timer_task = asyncio.create_task(timer.run())
    print("[Timer] Timer 已启动")

    supervisor_task = asyncio.create_task(supervisor.run(connection))

    # 定期同步 session 列表到 Shell Hook Source
    async def sync_sessions():
        while True:
            try:
                # 获取当前所有 session_id
                session_ids = set(supervisor.snapshots.keys())
                await shell_source.sync_sessions(session_ids)
            except Exception as e:
                logger.error(f"[HookSystem] 同步 sessions 失败: {e}")
            await asyncio.sleep(config.POLL_INTERVAL)

    sync_task = asyncio.create_task(sync_sessions())

    uvicorn_config = uvicorn.Config(
        server.app,
        host="0.0.0.0",
        port=8765,
        log_level="info"
    )
    uvicorn_server = uvicorn.Server(uvicorn_config)

    print("TermSupervisor Web Server starting at http://localhost:8765")

    try:
        await uvicorn_server.serve()
    finally:
        supervisor.stop()
        timer.stop()
        supervisor_task.cancel()
        timer_task.cancel()
        sync_task.cancel()
        await shell_source.stop()
        await claude_code_source.stop()
        await iterm_source.stop()


def main():
    """入口函数"""
    try:
        iterm2.run_until_complete(start_server)
    except KeyboardInterrupt:
        print("\nServer stopped")
