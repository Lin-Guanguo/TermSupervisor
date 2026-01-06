"""FastAPI 应用初始化"""

import asyncio
import logging

import iterm2
import uvicorn

from termsupervisor import config
from termsupervisor.adapters.iterm2 import ITerm2Client
from termsupervisor.render import RenderPipeline
from termsupervisor.runtime import RuntimeComponents, bootstrap
from termsupervisor.state import TaskStatus
from termsupervisor.web.server import WebServer

logger = logging.getLogger(__name__)


def create_app(pipeline: RenderPipeline, iterm_client: ITerm2Client) -> WebServer:
    """创建 Web 应用"""
    return WebServer(pipeline, iterm_client)


async def setup_hook_system(server: WebServer, connection: iterm2.Connection) -> RuntimeComponents:
    """设置 Hook 系统

    使用 runtime.bootstrap 创建组件。

    Returns:
        RuntimeComponents 包含所有组件
    """
    components = bootstrap(connection)

    # 设置状态变更回调 -> 广播到前端
    async def on_status_change(pane_id: str, status, reason: str, source: str):
        """状态变更时广播到前端"""
        window_name, tab_name, pane_name = server.pipeline.get_pane_location(pane_id)

        await server.broadcast(
            {
                "type": "hook_status",
                "pane_id": pane_id,
                "status": status.value,
                "status_color": status.color,
                "reason": reason,
                "source": source,
                "needs_notification": status.needs_notification,
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

    pipeline = RenderPipeline(
        iterm_client=iterm_client,
        exclude_names=config.EXCLUDE_NAMES,
    )

    server = create_app(pipeline, iterm_client)

    # 初始化 Hook 系统（状态管理的唯一来源）
    components = await setup_hook_system(server, connection)
    print("[HookSystem] Hook 系统已启动 (Shell + Claude Code + iTerm Focus)")

    # 设置 pipeline 的状态提供者（用于 get_layout_dict 获取状态信息）
    def get_pane_status(pane_id: str) -> dict | None:
        """获取 pane 状态信息"""
        state = components.hook_manager.get_state(pane_id)
        if state:
            status = state.status
            return {
                "status": status.value,
                "status_color": status.color,
                "status_reason": state.description,
                "is_running": status.is_running,
                "needs_notification": status.needs_notification,
                "needs_attention": status.needs_attention,
                "display": status.display,
            }
        return None

    pipeline.set_status_provider(get_pane_status)

    # 设置 WAITING 状态检查器（用于渲染阈值调整）
    def check_is_waiting(pane_id: str) -> bool:
        status = components.hook_manager.get_status(pane_id)
        return status == TaskStatus.WAITING_APPROVAL

    pipeline.set_waiting_provider(check_is_waiting)

    pipeline_task = asyncio.create_task(pipeline.run())

    # 定期同步 session 列表到 Shell Hook Source
    async def sync_sessions():
        while True:
            try:
                session_ids = pipeline.get_pane_ids()
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
        pipeline.stop()
        pipeline_task.cancel()
        sync_task.cancel()
        await components.stop_sources()


def main():
    """入口函数"""
    try:
        iterm2.run_until_complete(start_server)
    except KeyboardInterrupt:
        print("\nServer stopped")
