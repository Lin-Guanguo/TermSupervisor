"""FastAPI 应用初始化"""

import asyncio
import logging
from typing import TYPE_CHECKING

import uvicorn

from termsupervisor import config
from termsupervisor.adapters import TerminalAdapter
from termsupervisor.adapters.factory import (
    create_adapter,
    create_composite_adapter,
    detect_terminal_type,
    is_tmux_available,
)
from termsupervisor.adapters.iterm2 import ITerm2Adapter
from termsupervisor.render import RenderPipeline
from termsupervisor.runtime import (
    RuntimeComponents,
    bootstrap,
    bootstrap_composite,
    bootstrap_tmux,
)
from termsupervisor.state import PaneStatusInfo
from termsupervisor.web.server import WebServer

if TYPE_CHECKING:
    import iterm2

    from termsupervisor.adapters.iterm2 import ITerm2Client

logger = logging.getLogger(__name__)


def create_app(
    pipeline: RenderPipeline,
    adapter: TerminalAdapter,
    iterm_client: "ITerm2Client | None" = None,
) -> WebServer:
    """创建 Web 应用

    Args:
        pipeline: Render pipeline
        adapter: Terminal adapter
        iterm_client: Optional iTerm2 client for iTerm2-specific features

    Returns:
        WebServer instance
    """
    return WebServer(pipeline, adapter=adapter, iterm_client=iterm_client)


async def setup_hook_system_iterm2(
    server: WebServer, connection: "iterm2.Connection"
) -> RuntimeComponents:
    """设置 iTerm2 模式的 Hook 系统

    使用 runtime.bootstrap 创建组件。

    Returns:
        RuntimeComponents 包含所有组件
    """
    components = bootstrap(connection)
    _configure_hook_callbacks(server, components)
    return components


async def setup_hook_system_tmux(server: WebServer) -> RuntimeComponents:
    """设置 tmux 模式的 Hook 系统

    使用 runtime.bootstrap_tmux 创建组件。

    Returns:
        RuntimeComponents 包含所有组件
    """
    from termsupervisor.adapters.tmux import TmuxClient

    tmux_client = TmuxClient()
    components = bootstrap_tmux(tmux_client)
    _configure_hook_callbacks(server, components)
    return components


async def setup_hook_system_composite(
    server: WebServer, connection: "iterm2.Connection"
) -> RuntimeComponents:
    """设置 composite 模式的 Hook 系统

    同时启用 iTerm2 和 tmux 的事件源。

    Returns:
        RuntimeComponents 包含所有组件
    """
    from termsupervisor.adapters.tmux import TmuxClient

    tmux_client = TmuxClient()
    components = bootstrap_composite(connection, tmux_client)
    _configure_hook_callbacks(server, components)
    return components


def _configure_hook_callbacks(server: WebServer, components: RuntimeComponents) -> None:
    """配置 Hook 系统回调"""

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

    logger.info(f"[HookSystem] Hook 系统已配置 (mode={components.terminal_type})")


async def start_server_iterm2(connection: "iterm2.Connection"):
    """启动 iTerm2 模式服务器"""
    # Create adapter wrapping iTerm2 connection
    adapter = ITerm2Adapter(connection, exclude_names=config.EXCLUDE_NAMES)
    iterm_client = adapter.client  # Access underlying client for iTerm2-specific ops

    pipeline = RenderPipeline(
        adapter=adapter,
        exclude_names=config.EXCLUDE_NAMES,
    )

    server = create_app(pipeline, adapter=adapter, iterm_client=iterm_client)

    # 初始化 Hook 系统（状态管理的唯一来源）
    components = await setup_hook_system_iterm2(server, connection)
    await components.start_sources()
    print("[HookSystem] Hook 系统已启动 (Shell + Claude Code + iTerm Focus)")

    # 设置 pipeline 的状态提供者（用于 get_layout_dict 获取状态信息）
    def get_pane_status(pane_id: str) -> PaneStatusInfo | None:
        """获取 pane 状态信息"""
        state = components.hook_manager.get_state(pane_id)
        if state:
            status = state.status
            return PaneStatusInfo(
                status=status.value,
                status_color=status.color,
                status_reason=state.description,
                is_running=status.is_running,
                needs_notification=status.needs_notification,
                needs_attention=status.needs_attention,
                display=status.display,
            )
        return None

    pipeline.set_status_provider(get_pane_status)

    pipeline_task = asyncio.create_task(pipeline.run())

    # 定期同步 session 列表到 Shell Hook Source (iTerm2 only)
    sync_task = None
    if components.shell_source:

        async def sync_sessions():
            while True:
                try:
                    session_ids = pipeline.get_pane_ids()
                    await components.shell_source.sync_sessions(session_ids)
                except Exception as e:
                    logger.error(f"[HookSystem] 同步 sessions 失败: {e}")
                await asyncio.sleep(config.POLL_INTERVAL)

        sync_task = asyncio.create_task(sync_sessions())

    uvicorn_config = uvicorn.Config(
        server.app, host="0.0.0.0", port=8765, log_level="info"
    )
    uvicorn_server = uvicorn.Server(uvicorn_config)

    print("TermSupervisor Web Server starting at http://localhost:8765")

    try:
        await uvicorn_server.serve()
    finally:
        pipeline.stop()
        pipeline_task.cancel()
        if sync_task:
            sync_task.cancel()
        await components.stop_sources()


async def start_server_tmux():
    """启动 tmux 模式服务器"""
    from termsupervisor.adapters.tmux import TmuxAdapter

    # Create tmux adapter with exclude_names
    adapter = TmuxAdapter(exclude_names=config.EXCLUDE_NAMES)

    pipeline = RenderPipeline(
        adapter=adapter,
        exclude_names=config.EXCLUDE_NAMES,
    )

    server = create_app(pipeline, adapter=adapter, iterm_client=None)

    # 初始化 Hook 系统（状态管理的唯一来源）
    components = await setup_hook_system_tmux(server)
    await components.start_sources()
    print("[HookSystem] Hook 系统已启动 (Claude Code + Tmux Focus)")

    # 设置 pipeline 的状态提供者
    def get_pane_status(pane_id: str) -> PaneStatusInfo | None:
        """获取 pane 状态信息"""
        state = components.hook_manager.get_state(pane_id)
        if state:
            status = state.status
            return PaneStatusInfo(
                status=status.value,
                status_color=status.color,
                status_reason=state.description,
                is_running=status.is_running,
                needs_notification=status.needs_notification,
                needs_attention=status.needs_attention,
                display=status.display,
            )
        return None

    pipeline.set_status_provider(get_pane_status)

    pipeline_task = asyncio.create_task(pipeline.run())

    uvicorn_config = uvicorn.Config(
        server.app, host="0.0.0.0", port=8765, log_level="info"
    )
    uvicorn_server = uvicorn.Server(uvicorn_config)

    print("TermSupervisor Web Server starting at http://localhost:8765 (tmux mode)")

    try:
        await uvicorn_server.serve()
    finally:
        pipeline.stop()
        pipeline_task.cancel()
        await components.stop_sources()


async def start_server_composite(connection: "iterm2.Connection"):
    """启动 composite 模式服务器（iTerm2 + tmux）"""
    # Create composite adapter
    adapter = create_composite_adapter(
        connection=connection,
        exclude_names=config.EXCLUDE_NAMES,
    )
    iterm_client = adapter._iterm2.client  # Access iTerm2 client for operations

    pipeline = RenderPipeline(
        adapter=adapter,
        exclude_names=config.EXCLUDE_NAMES,
    )

    server = create_app(pipeline, adapter=adapter, iterm_client=iterm_client)

    # 初始化 Hook 系统（同时启用 iTerm2 和 tmux 事件源）
    components = await setup_hook_system_composite(server, connection)
    await components.start_sources()
    print("[HookSystem] Hook 系统已启动 (Shell + Claude Code + iTerm Focus + Tmux Focus)")

    # 设置 pipeline 的状态提供者
    def get_pane_status(pane_id: str) -> PaneStatusInfo | None:
        """获取 pane 状态信息"""
        state = components.hook_manager.get_state(pane_id)
        if state:
            status = state.status
            return PaneStatusInfo(
                status=status.value,
                status_color=status.color,
                status_reason=state.description,
                is_running=status.is_running,
                needs_notification=status.needs_notification,
                needs_attention=status.needs_attention,
                display=status.display,
            )
        return None

    pipeline.set_status_provider(get_pane_status)

    pipeline_task = asyncio.create_task(pipeline.run())

    # 定期同步 session 列表到 Shell Hook Source
    # Note: ShellHookSource only monitors iTerm2 sessions, so we need to
    # filter to iTerm2-namespaced IDs and strip the namespace prefix
    from termsupervisor.core.ids import get_native_id, is_iterm2_id

    sync_task = None
    if components.shell_source:

        async def sync_sessions():
            while True:
                try:
                    # Filter to iTerm2 panes and strip namespace
                    all_pane_ids = pipeline.get_pane_ids()
                    native_iterm2_ids = {
                        get_native_id(pid) for pid in all_pane_ids if is_iterm2_id(pid)
                    }
                    await components.shell_source.sync_sessions(native_iterm2_ids)
                except Exception as e:
                    logger.error(f"[HookSystem] 同步 sessions 失败: {e}")
                await asyncio.sleep(config.POLL_INTERVAL)

        sync_task = asyncio.create_task(sync_sessions())

    uvicorn_config = uvicorn.Config(
        server.app, host="0.0.0.0", port=8765, log_level="info"
    )
    uvicorn_server = uvicorn.Server(uvicorn_config)

    print("TermSupervisor Web Server starting at http://localhost:8765 (composite mode: iTerm2 + tmux)")

    try:
        await uvicorn_server.serve()
    finally:
        pipeline.stop()
        pipeline_task.cancel()
        if sync_task:
            sync_task.cancel()
        await components.stop_sources()


def main():
    """入口函数

    根据 TERMINAL_ADAPTER 配置选择启动模式：
    - "iterm2": 使用 iTerm2 Python API
    - "tmux": 使用 tmux subprocess 命令
    - "composite": iTerm2 + tmux 复合模式
    - "auto": 根据环境自动检测（iTerm2 优先，如果有 tmux 则启用 composite）
    """
    terminal_type = config.TERMINAL_ADAPTER

    if terminal_type == "auto":
        # Auto-detect terminal mode:
        # Note: When running in background (nohup), env vars are not available
        # but subprocess calls work for tmux detection.
        #
        # 1. If tmux sessions exist → composite (iTerm2 + tmux)
        # 2. If $TMUX env var set (running directly in tmux) → pure tmux
        # 3. Otherwise → iterm2
        if is_tmux_available():
            terminal_type = "composite"
        elif detect_terminal_type() == "tmux":
            terminal_type = "tmux"
        else:
            terminal_type = "iterm2"

    print(f"[TermSupervisor] Starting in {terminal_type} mode...")

    try:
        if terminal_type == "tmux":
            asyncio.run(start_server_tmux())
        elif terminal_type == "composite":
            import iterm2

            iterm2.run_until_complete(start_server_composite)
        else:
            # iTerm2 mode (default)
            import iterm2

            iterm2.run_until_complete(start_server_iterm2)
    except KeyboardInterrupt:
        print("\nServer stopped")
